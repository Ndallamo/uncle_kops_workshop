from django.shortcuts import render, get_object_or_404, redirect
from django import forms

from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction

from django.contrib import messages

from django.db.models import Count, Sum, Q, F
from django.core.paginator import Paginator

from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.http import JsonResponse, HttpResponseBadRequest, HttpResponse, FileResponse

from django.views.decorators.http import require_POST, require_GET

from django.views.decorators.csrf import csrf_exempt

import csv
import json
import logging

logger = logging.getLogger(__name__)


def _filter_datetime_date_range(queryset, field, start_date, end_date):
    if start_date:
        start_at = timezone.make_aware(datetime.combine(start_date, time.min))
        queryset = queryset.filter(**{f'{field}__gte': start_at})
    if end_date:
        end_at = timezone.make_aware(datetime.combine(end_date + timedelta(days=1), time.min))
        queryset = queryset.filter(**{f'{field}__lt': end_at})
    return queryset


def _is_admin(user):
    profile = getattr(user, 'userprofile', None)
    return user.is_staff or (profile and profile.role == 'admin')


def _role(user):
    profile = getattr(user, 'userprofile', None)
    return profile.role if profile else ('admin' if user.is_staff else '')


def _mechanic_status_choices(order):
    allowed_statuses = {
        'pending': {'in_progress'},
        'in_progress': {'ready'},
        'waiting': {'in_progress', 'ready'},
    }.get(order.status, set())
    return [
        (value, label)
        for value, label in RepairOrder.STATUS_CHOICES
        if value in allowed_statuses
    ]


def _deny_access(request):
    messages.error(request, 'Access denied.')
    return redirect('dashboard')


def record_audit_entry(actor, action, obj, *, details=None, repair_order=None):
    return AuditLog.objects.create(
        actor=actor,
        action=action,
        object_type=obj.__class__.__name__,
        object_id=obj.pk,
        repair_order=repair_order,
        details=details or {},
    )


def record_repair_event(order, actor, event_type, *, note='', previous_status='', current_status='', customer_visible=False, metadata=None):
    event_details = metadata or {}
    event = RepairOrderEvent.objects.create(
        repair_order=order,
        actor=actor,
        event_type=event_type,
        previous_status=previous_status,
        current_status=current_status,
        note=note,
        customer_visible=customer_visible,
        metadata=event_details,
    )
    record_audit_entry(
        actor,
        event_type,
        order,
        repair_order=order,
        details={
            'previous_status': previous_status,
            'current_status': current_status,
            'note': note,
            **event_details,
        },
    )
    if customer_visible:
        customer_user = User.objects.filter(email=order.vehicle.customer.email).first()
        if customer_user and customer_user.pk != getattr(actor, 'pk', None):
            Notification.objects.create(
                recipient=customer_user,
                repair_order=order,
                message=note or event.get_event_type_display(),
                link=f'/repairs/{order.pk}/',
            )
    if event_type in {'assignment', 'status_rejected'} and order.assigned_tech_id:
        mechanic = order.assigned_tech
        if mechanic.pk != getattr(actor, 'pk', None):
            Notification.objects.create(
                recipient=mechanic,
                repair_order=order,
                message=note or event.get_event_type_display(),
                link=f'/repairs/{order.pk}/',
            )
    return event


def refresh_pending_estimate(order):
    labor_amount = sum((line.line_total for line in order.estimate_lines.filter(line_type='labor')), Decimal('0.00'))
    parts_amount = sum((line.line_total for line in order.estimate_lines.filter(line_type='part')), Decimal('0.00'))
    estimate = order.estimates.filter(status='pending').first()
    if estimate is None:
        estimate = RepairEstimate.objects.create(
            repair_order=order,
            version=order.estimates.count() + 1,
            status='pending',
        )
    estimate.labor_amount = labor_amount
    estimate.parts_amount = parts_amount
    estimate.total_amount = labor_amount + parts_amount
    estimate.save(update_fields=['labor_amount', 'parts_amount', 'total_amount'])
    return estimate

from django.contrib.auth import authenticate

from django.core.cache import cache

from .models import (
    Customer,
    Vehicle,
    RepairOrder,
    LaborLine,
    PartsLine,
    Invoice,
    InvoicePayment,
    RepairOrderEvent,
    Appointment,
    CollectionRecord,
    Notification,
    RepairDocument,
    AuditLog,
    RepairEstimate,
    RepairEstimateLine,
    Part,
    ServiceItem,
    UserProfile,
    EmailVerificationToken,
    normalize_license_plate,
)
from .currency import format_rand

from .forms import (
    CustomerForm,
    VehicleForm,
    RepairOrderForm,
    RepairDocumentForm,
    EstimateLaborForm,
    EstimatePartForm,
    EstimateNotesForm,
    LaborLineForm,
    PartsLineForm,
    InvoiceForm,
    InvoicePaymentForm,
    AppointmentForm,
    PartForm,
    ServiceItemForm,
    UserRegistrationForm,
    EmailOrUsernameAuthenticationForm,
    EmployeeForm,
    EmployeeEditForm,
)

from .auth_utils import (
    send_verification_email,
    can_resend_verification,
    can_request_password_reset,
    send_password_reset_email,
    send_invoice_ready_email,
    send_service_request_confirmation,
)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  AUTH
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@require_POST
def logout_view(request):
    logout(request)
    return redirect('login')


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST' and request.POST.get('resend_verification'):
        pending_id = request.session.get('pending_verification_user_id')
        user = User.objects.filter(pk=pending_id).first() if pending_id else None
        profile = getattr(user, 'userprofile', None)
        if not user or not profile or profile.is_verified or not user.email:
            messages.error(request, 'Please sign in again to request a new verification email.')
            return redirect('login')
        if not can_resend_verification(user):
            messages.error(request, 'Too many verification emails requested. Please try again later.')
            return redirect('login')
        try:
            send_verification_email(request, user, ttl_minutes=15)
        except Exception:
            logger.exception('Verification email delivery failed for user_id=%s.', user.pk)
            messages.error(request, 'We could not send the email right now. Please try again shortly.')
            return redirect('login')
        request.session.pop('pending_verification_user_id', None)
        messages.success(request, f'A new verification email was sent to {user.email}. Check your inbox and spam folder.')
        return redirect('login')

    form = EmailOrUsernameAuthenticationForm(request, data=request.POST or None)
    needs_verification = False

    if request.method == 'POST' and form.is_valid():
        user = form.get_user()
        profile = getattr(user, 'userprofile', None)

        if profile and profile.role == 'customer' and not profile.is_verified:
            request.session['pending_verification_user_id'] = user.pk
            needs_verification = True
            form.add_error(
                None,
                'Please verify your email address before signing in. '
                'Check your inbox (and spam folder) for the verification link.'
            )
        else:
            login(request, user)
            if profile and profile.role == 'customer':
                customer = Customer.objects.filter(email=user.email).first()
                if not customer or not customer.has_required_contact_details:
                    messages.info(request, 'Please update your phone number and address before continuing.')
                    return redirect('customer_profile')
            redirect_to = request.POST.get('next')
            if not url_has_allowed_host_and_scheme(redirect_to, allowed_hosts={request.get_host()}):
                redirect_to = 'dashboard'
            return redirect(redirect_to)

    return render(
        request,
        'workshop/login.html',
        {
            'form': form,
            'next': request.GET.get('next', ''),
            'needs_verification': needs_verification,
        }
    )

def _unique_username_from_email(email):
    base = (email or 'customer').split('@')[0][:120] or 'customer'
    candidate, n = base, 1
    while User.objects.filter(username__iexact=candidate).exists():
        n += 1
        candidate = f'{base}{n}'
    return candidate


def register(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)

        if form.is_valid():
            # Create user but do NOT auto-login until email verified
            user = form.save(commit=False)
            role = 'customer'
            user.username = _unique_username_from_email(user.email)

            if role == 'admin':
                user.is_staff = True

            user.is_active = True
            with transaction.atomic():
                user.save()
                UserProfile.objects.create(
                    user=user,
                    role=role,
                    is_verified=False
                )

                if role == 'customer':
                    Customer.objects.get_or_create(
                        email=user.email,
                        defaults={
                            'first_name': form.cleaned_data.get('first_name'),
                            'last_name': form.cleaned_data.get('last_name'),
                            'phone': form.cleaned_data.get('phone', ''),
                            'address': form.cleaned_data.get('address', ''),
                            'notes': '',
                        }
                    )
                record_audit_entry(
                    user,
                    'account_registered',
                    user,
                    details={'role': role, 'is_active': user.is_active, 'is_verified': False},
                )

            # Send verification email
            try:
                send_verification_email(
                    request,
                    user,
                    ttl_minutes=15
                )
            except Exception:
                logger.exception('Verification email delivery failed for user_id=%s.', user.pk)
                messages.warning(
                    request,
                    'Account created, but we could not send the verification email. '
                    'Sign in with your username and password to request a new one.'
                )
                return redirect('login')

            messages.success(
                request,
                'Account created. Please check your email to verify your account.'
            )

            return redirect('login')

    else:
        form = UserRegistrationForm()

    return render(
        request,
        'workshop/register.html',
        {'form': form}
    )


def forgot_password(request):
    if request.method == 'POST':
        email = request.POST.get('email')

        if not email:
            messages.error(
                request,
                'Please provide your email address.'
            )
            return redirect('forgot_password')

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            user = None

        if user and can_request_password_reset(user):
            try:
                send_password_reset_email(
                    request,
                    user,
                    ttl_minutes=15
                )
            except Exception:
                logger.exception('Password reset email delivery failed.')
        elif user:
            logger.info('Password reset request limit reached for user_id=%s.', user.pk)

        messages.success(
            request,
            'If an account with that email exists, a reset link has been sent.'
        )

        return redirect('login')

    return render(
        request,
        'workshop/forgot_password.html'
    )


def reset_password(request):
    token = (
        request.GET.get('token')
        if request.method == 'GET'
        else request.POST.get('token')
    )

    if request.method == 'GET':
        if not token:
            messages.error(
                request,
                'Invalid password reset link.'
            )
            return redirect('login')

        return render(
            request,
            'workshop/reset_password.html',
            {'token': token}
        )

    # POST â€” perform reset
    new_password = request.POST.get('password')
    confirm = request.POST.get('password_confirm')

    if not new_password or new_password != confirm:
        messages.error(
            request,
            'Passwords do not match.'
        )

        return render(
            request,
            'workshop/reset_password.html',
            {'token': token}
        )

    from .models import PasswordResetToken

    obj = PasswordResetToken.validate_token(token)

    if not obj:
        messages.error(
            request,
            'Invalid or expired token.'
        )
        return redirect('login')

    user = obj.user

    try:
        validate_password(new_password, user=user)
    except ValidationError as exc:
        for error in exc.messages:
            messages.error(request, error)
        return render(
            request,
            'workshop/reset_password.html',
            {'token': token}
        )

    # Set new password and mark token used
    user.set_password(new_password)
    user.save()

    obj.used = True
    obj.save()

    messages.success(
        request,
        'Your password has been reset. You can now log in.'
    )

    return redirect('login')


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  API ENDPOINTS FOR REGISTRATION AND VERIFICATION
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@csrf_exempt
@require_POST
def api_register(request):
    try:
        data = json.loads(request.body)
    except Exception:
        return HttpResponseBadRequest('Invalid JSON')

    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    first_name = data.get('first_name', '')
    last_name = data.get('last_name', '')
    role = data.get('role', 'customer')

    if not username or not email or not password:
        return JsonResponse(
            {
                'error': 'username, email and password required'
            },
            status=400
        )

    if role != 'customer':
        return JsonResponse(
            {'error': 'Only customer accounts can be created through public registration.'},
            status=400,
        )

    try:
        validate_password(password)
    except ValidationError as exc:
        return JsonResponse({'error': exc.messages}, status=400)

    if (
        User.objects.filter(username=username).exists()
        or User.objects.filter(email=email).exists()
    ):
        return JsonResponse(
            {
                'error': 'user with username or email already exists'
            },
            status=400
        )

    with transaction.atomic():
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name
        )

        UserProfile.objects.create(
            user=user,
            role=role,
            is_verified=False
        )

        if role == 'customer':
            Customer.objects.get_or_create(
                email=user.email,
                defaults={
                    'first_name': first_name,
                    'last_name': last_name
                }
            )
        record_audit_entry(
            user,
            'account_registered',
            user,
            details={'role': role, 'is_active': user.is_active, 'is_verified': False},
        )

    try:
        send_verification_email(
            request,
            user,
            ttl_minutes=15
        )

    except Exception:
        # Still return created but warn
        return JsonResponse(
            {
                'status': 'created',
                'warning': 'failed to send verification email'
            },
            status=201
        )

    return JsonResponse(
        {
            'status': 'created',
            'message': 'verification email sent'
        },
        status=201
    )


@require_GET
def verify_email(request):
    token = request.GET.get('token')

    if not token:
        return render(
            request,
            'workshop/email_verification.html',
            {
                'success': False,
                'message': 'This verification link is missing its token.',
            },
            status=400
        )

    obj = EmailVerificationToken.validate_token(token)

    if not obj:
        return render(
            request,
            'workshop/email_verification.html',
            {
                'success': False,
                'message': 'This verification link is invalid or has expired.',
            },
            status=400
        )

    user = obj.user

    with transaction.atomic():
        obj.used = True
        obj.save()

        profile = getattr(user, 'userprofile', None)

        if profile and not profile.is_verified:
            profile.is_verified = True
            profile.save(update_fields=['is_verified'])
            record_audit_entry(
                user,
                'account_email_verified',
                user,
                details={'is_verified': True},
            )

    # Log the user in after successful verification
    login(request, user)

    return render(
        request,
        'workshop/email_verification.html',
        {
            'success': True,
            'message': 'Your email has been verified. You are now signed in.',
        }
    )


@csrf_exempt
@require_POST
def resend_verification(request):
    try:
        data = json.loads(request.body)
    except Exception:
        return HttpResponseBadRequest('Invalid JSON')

    email = data.get('email')

    if not email:
        return JsonResponse(
            {'error': 'email required'},
            status=400
        )

    generic_response = {
        'status': 'ok',
        'message': 'If the account can be verified, instructions will be sent.',
    }

    try:
        user = User.objects.get(email=email)

    except User.DoesNotExist:
        return JsonResponse(generic_response)

    profile = getattr(user, 'userprofile', None)

    if not profile or profile.is_verified:
        return JsonResponse(generic_response)

    if not can_resend_verification(user):
        logger.info('Verification resend limit reached for user_id=%s.', user.pk)
        return JsonResponse(generic_response)

    try:
        send_verification_email(
            request,
            user,
            ttl_minutes=15
        )

    except Exception:
        logger.exception('Verification email delivery failed.')

    return JsonResponse(generic_response)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  EMPLOYEES (MECHANICS)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@login_required
def employee_list(request):
    if not request.user.is_staff:
        messages.error(request, 'Access denied.')
        return redirect('dashboard')
    mechanics = UserProfile.objects.filter(role__in=['mechanic', 'admin']).select_related('user')
    query = request.GET.get('q', '').strip()
    if query:
        mechanics = mechanics.filter(
            Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
            | Q(user__username__icontains=query)
            | Q(user__email__icontains=query)
        )
    mechanics = Paginator(mechanics.order_by('user__last_name', 'user__first_name', 'pk'), 25).get_page(request.GET.get('page'))
    return render(request, 'workshop/employee_list.html', {'mechanics': mechanics, 'q': query})


@login_required
def employee_create(request):
    if not request.user.is_staff:
        messages.error(request, 'Access denied.')
        return redirect('dashboard')
    if request.method == 'POST':
        form = EmployeeForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                user = form.save()
                profile = UserProfile.objects.create(user=user, role='mechanic')
                record_audit_entry(
                    request.user,
                    'employee_created',
                    user,
                    details={'role': profile.role, 'is_active': user.is_active},
                )
            messages.success(request, f"Mechanic '{user.get_full_name()}' added.")
            return redirect('employee_list')
    else:
        form = EmployeeForm()
    return render(request, 'workshop/employee_form.html', {'form': form, 'title': 'Add mechanic'})


@login_required
def employee_edit(request, pk):
    if not request.user.is_staff:
        messages.error(request, 'Access denied.')
        return redirect('dashboard')
    profile = get_object_or_404(UserProfile, pk=pk, role__in=['mechanic', 'admin'])
    user = profile.user
    previous_role = profile.role
    previous_is_active = user.is_active
    if user.pk != request.user.pk and (user.is_superuser or previous_role == 'admin') and not request.user.is_superuser:
        return _deny_access(request)
    if request.method == 'POST':
        form = EmployeeEditForm(request.POST, instance=user, initial={'role': profile.role})
        if form.is_valid():
            changed_fields = form.changed_data
            new_role = form.cleaned_data['role']
            new_is_active = form.cleaned_data['is_active']
            if user.pk == request.user.pk and (new_role != previous_role or not new_is_active):
                form.add_error('role', 'You cannot change your own role or deactivate your account.')
            else:
                access_changes = {}
                if new_role != previous_role:
                    access_changes['role'] = {'from': previous_role, 'to': new_role}
                if new_is_active != previous_is_active:
                    access_changes['is_active'] = {'from': previous_is_active, 'to': new_is_active}
                with transaction.atomic():
                    if access_changes:
                        list(
                            UserProfile.objects.select_for_update()
                            .filter(role__in=['admin', 'mechanic'])
                            .order_by('pk')
                        )
                    removing_admin_access = (
                        previous_role == 'admin'
                        and (new_role != 'admin' or not new_is_active)
                    )
                    if removing_admin_access and UserProfile.objects.filter(
                        role='admin',
                        user__is_active=True,
                    ).count() <= 1:
                        form.add_error('role', 'At least one active admin account must remain.')
                    else:
                        user = form.save(commit=False)
                        user.is_staff = new_role == 'admin' or user.is_superuser
                        user.save()
                        if new_role != previous_role:
                            profile.role = new_role
                            profile.save(update_fields=['role'])
                        if changed_fields:
                            details = {'changed_fields': changed_fields}
                            if access_changes:
                                details['access_changes'] = access_changes
                            action = 'employee_access_updated' if access_changes else 'employee_updated'
                            record_audit_entry(
                                request.user,
                                action,
                                user,
                                details=details,
                            )
                if not form.errors:
                    messages.success(request, 'Employee account updated.')
                    return redirect('employee_list')
    else:
        form = EmployeeEditForm(instance=user, initial={'role': profile.role})
    return render(request, 'workshop/employee_form.html', {'form': form, 'title': 'Edit employee', 'profile': profile})


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  REPORTS
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@login_required
def report(request):
    profile = getattr(request.user, 'userprofile', None)
    role = profile.role if profile else ('admin' if request.user.is_staff else '')

    if role != 'admin':
        messages.error(request, 'Access denied.')
        return redirect('dashboard')

    start_date = parse_date(request.GET.get('start_date', ''))
    end_date = parse_date(request.GET.get('end_date', ''))
    if request.GET.get('start_date') and not start_date:
        messages.error(request, 'Enter a valid report start date.')
    if request.GET.get('end_date') and not end_date:
        messages.error(request, 'Enter a valid report end date.')
    if start_date and end_date and start_date > end_date:
        messages.error(request, 'The report start date must not be after the end date.')
        start_date = end_date = None

    customers = Customer.objects.all()
    orders = RepairOrder.objects.select_related('vehicle__customer', 'assigned_tech')
    invoices = Invoice.objects.select_related('repair_order__vehicle__customer')
    payments = InvoicePayment.objects.all()
    appointments = Appointment.objects.select_related('customer', 'vehicle')
    if start_date:
        invoices = invoices.filter(issue_date__gte=start_date)
    if end_date:
        invoices = invoices.filter(issue_date__lte=end_date)
    customers = _filter_datetime_date_range(customers, 'created_at', start_date, end_date)
    orders = _filter_datetime_date_range(orders, 'date_created', start_date, end_date)
    payments = _filter_datetime_date_range(payments, 'received_at', start_date, end_date)
    appointments = _filter_datetime_date_range(appointments, 'date_time', start_date, end_date)

    total_customers = customers.count()
    open_repair_orders = orders.exclude(status__in=['completed', 'cancelled']).count()
    completed_repairs = orders.filter(status='completed').count()
    pending_approval = orders.filter(approved=False).count()
    total_revenue = payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    total_invoiced = sum(
        (invoice.total_due for invoice in invoices.select_related(None).only('service_amount', 'discount', 'tax_rate')),
        Decimal('0.00'),
    )
    paid_invoices = invoices.filter(payment_status='paid').count()
    unpaid_invoices = invoices.filter(payment_status='unpaid').count()
    invoices_with_balances = invoices.filter(payment_status__in=['unpaid', 'partial']).select_related(None).annotate(
        report_paid_amount=Sum('payments__amount')
    ).only('service_amount', 'discount', 'tax_rate')
    outstanding_balance = sum(
        (invoice.total_due - (invoice.report_paid_amount or Decimal('0.00')) for invoice in invoices_with_balances),
        Decimal('0.00'),
    )
    paid_invoice_rows = invoices.filter(payment_status='paid').select_related(None).only('service_amount', 'discount', 'tax_rate')
    paid_invoice_totals = [invoice.total_due for invoice in paid_invoice_rows]
    average_invoice = sum(paid_invoice_totals, Decimal('0.00')) / len(paid_invoice_totals) if paid_invoice_totals else Decimal('0.00')

    today = timezone.localdate()
    range_end = end_date or today
    range_end_index = range_end.year * 12 + range_end.month - 1
    range_start_index = (
        start_date.year * 12 + start_date.month - 1
        if start_date else range_end_index - 5
    )
    range_start_index = max(range_start_index, range_end_index - 11)
    monthly_revenue = []
    for month_index in range(range_start_index, range_end_index + 1):
        year, month_zero_indexed = divmod(month_index, 12)
        month_number = month_zero_indexed + 1
        month_start = date(year, month_number, 1)
        month_end = date(year + 1, 1, 1) if month_number == 12 else date(year, month_number + 1, 1)
        month_payments = _filter_datetime_date_range(payments, 'received_at', month_start, month_end - timedelta(days=1))
        month_total = month_payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        monthly_revenue.append({'label': month_start.strftime('%b %y'), 'total': month_total})

    max_monthly_revenue = max((item['total'] for item in monthly_revenue), default=Decimal('0.00')) or Decimal('1.00')
    for item in monthly_revenue:
        item['height_percent'] = max(12, round((item['total'] / max_monthly_revenue) * 100))

    status_breakdown = list(orders.values('status').annotate(total=Count('pk')).order_by('-total'))
    max_status_total = max((item['total'] for item in status_breakdown), default=0) or 1
    for item in status_breakdown:
        item['percentage'] = round(item['total'] / max_status_total * 100)

    payment_range = Q()
    if start_date:
        payment_start = timezone.make_aware(datetime.combine(start_date, time.min))
        payment_range &= Q(vehicles__repair_orders__invoice__payments__received_at__gte=payment_start)
    if end_date:
        payment_end = timezone.make_aware(datetime.combine(end_date + timedelta(days=1), time.min))
        payment_range &= Q(vehicles__repair_orders__invoice__payments__received_at__lt=payment_end)
    top_customers = list(Customer.objects.annotate(
        total_spend=Sum('vehicles__repair_orders__invoice__payments__amount', filter=payment_range)
    ).order_by('-total_spend')[:5])

    recent_paid_invoices = invoices.filter(payment_status='paid').annotate(
        report_paid_amount=Sum('payments__amount')
    ).order_by('-issue_date')[:5]
    appointment_breakdown = list(appointments.values('assignment_status').annotate(total=Count('pk')).order_by('-total'))
    parts_consumption = list(
        PartsLine.objects.filter(repair_order__in=orders)
        .values('part__name', 'part__part_number')
        .annotate(quantity=Sum('quantity'))
        .order_by('-quantity')[:10]
    )
    mechanic_workload = list(
        User.objects.filter(repair_orders__in=orders)
        .annotate(job_count=Count('repair_orders', distinct=True))
        .order_by('-job_count', 'username')[:10]
    )
    service_demand = list(
        LaborLine.objects.filter(repair_order__in=orders)
        .values('service_item__name')
        .annotate(jobs=Count('repair_order', distinct=True), hours=Sum('hours'))
        .order_by('-jobs', 'service_item__name')[:10]
    )
    low_stock_parts = Part.objects.filter(stock_qty__lte=F('reorder_level')).order_by('stock_qty', 'name')[:10]

    context = {
        'total_customers': total_customers,
        'open_repair_orders': open_repair_orders,
        'completed_repairs': completed_repairs,
        'pending_approval': pending_approval,
        'paid_invoices': paid_invoices,
        'unpaid_invoices': unpaid_invoices,
        'outstanding_balance': outstanding_balance,
        'total_revenue': total_revenue,
        'total_invoiced': total_invoiced,
        'average_invoice': average_invoice,
        'monthly_revenue': monthly_revenue,
        'status_breakdown': status_breakdown,
        'top_customers': top_customers,
        'recent_paid_invoices': recent_paid_invoices,
        'appointment_breakdown': appointment_breakdown,
        'parts_consumption': parts_consumption,
        'mechanic_workload': mechanic_workload,
        'service_demand': service_demand,
        'low_stock_parts': low_stock_parts,
        'start_date': start_date,
        'end_date': end_date,
        'period_label': 'Custom range' if start_date or end_date else 'All dates',
    }
    return render(request, 'workshop/report.html', context)


@login_required
def report_export(request):
    profile = getattr(request.user, 'userprofile', None)
    role = profile.role if profile else ('admin' if request.user.is_staff else '')

    if role != 'admin':
        messages.error(request, 'Access denied.')
        return redirect('dashboard')

    start_date = parse_date(request.GET.get('start_date', ''))
    end_date = parse_date(request.GET.get('end_date', ''))
    if (request.GET.get('start_date') and not start_date) or (request.GET.get('end_date') and not end_date):
        return HttpResponseBadRequest('Enter valid start_date and end_date values.')
    if start_date and end_date and start_date > end_date:
        return HttpResponseBadRequest('start_date must not be after end_date.')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="uncle_kops_workshop_report.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Month', 'Revenue Collected (R)', 'Total Invoiced (R)', 'Customers Added',
        'Open Repairs', 'Completed Repairs', 'Unpaid Invoices', 'Outstanding Balance (R)',
    ])
    today = timezone.localdate()
    range_end = end_date or today
    range_end_index = range_end.year * 12 + range_end.month - 1
    range_start_index = start_date.year * 12 + start_date.month - 1 if start_date else range_end_index - 5
    range_start_index = max(range_start_index, range_end_index - 11)

    for month_index in range(range_start_index, range_end_index + 1):
        year, month_zero_indexed = divmod(month_index, 12)
        month_number = month_zero_indexed + 1
        month_start = date(year, month_number, 1)
        month_end = date(year + 1, 1, 1) if month_number == 12 else date(year, month_number + 1, 1)
        period_start = max(start_date, month_start) if start_date else month_start
        period_end = min(end_date, month_end - timedelta(days=1)) if end_date else month_end - timedelta(days=1)
        if period_start > period_end:
            continue

        month_payments = _filter_datetime_date_range(
            InvoicePayment.objects.all(), 'received_at', period_start, period_end
        )
        month_customers = _filter_datetime_date_range(
            Customer.objects.all(), 'created_at', period_start, period_end
        )
        month_orders = _filter_datetime_date_range(
            RepairOrder.objects.all(), 'date_created', period_start, period_end
        )
        month_invoices = Invoice.objects.filter(issue_date__gte=period_start, issue_date__lte=period_end)
        invoice_rows = month_invoices.select_related(None).only('service_amount', 'discount', 'tax_rate')
        invoiced_amount = sum((invoice.total_due for invoice in invoice_rows), Decimal('0.00'))
        unpaid_invoices = month_invoices.filter(payment_status='unpaid')
        outstanding_invoices = month_invoices.filter(payment_status__in=['unpaid', 'partial'])
        unpaid_rows = outstanding_invoices.annotate(report_paid_amount=Sum('payments__amount')).only(
            'service_amount', 'discount', 'tax_rate'
        )
        outstanding = sum(
            (max(invoice.total_due - (invoice.report_paid_amount or Decimal('0.00')), Decimal('0.00')) for invoice in unpaid_rows),
            Decimal('0.00'),
        )
        month_revenue = month_payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        writer.writerow([
            month_start.strftime('%b %y'),
            format_rand(month_revenue),
            format_rand(invoiced_amount),
            month_customers.count(),
            month_orders.exclude(status__in=['completed', 'cancelled']).count(),
            month_orders.filter(status='completed').count(),
            unpaid_invoices.count(),
            format_rand(outstanding),
        ])

    return response


@login_required
@require_GET
def audit_log(request):
    if not _is_admin(request.user):
        return _deny_access(request)

    entries = AuditLog.objects.select_related('actor', 'repair_order')
    query = request.GET.get('q', '').strip()
    if query:
        entries = entries.filter(
            Q(action__icontains=query)
            | Q(object_type__icontains=query)
            | Q(actor__username__icontains=query)
            | Q(object_id__icontains=query)
        )
    audit_entries = Paginator(entries, 50).get_page(request.GET.get('page'))
    return render(request, 'workshop/audit_log.html', {
        'audit_entries': audit_entries,
        'query': query,
    })


@login_required
@require_POST
def notification_mark_read(request, pk):
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notification.is_read = True
    notification.save(update_fields=['is_read'])
    return redirect('dashboard')


@login_required
def dashboard(request):
    profile = getattr(request.user, 'userprofile', None)
    role = profile.role if profile else ('admin' if request.user.is_staff else '')

    if role == 'customer':
        customer = Customer.objects.filter(email=request.user.email).first()
        repair_orders = []
        vehicles = Vehicle.objects.none()
        approved_unassigned_orders = RepairOrder.objects.none()
        pending_approval = []
        notifications = []
        notification_items = Notification.objects.none()
        if customer:
            vehicles = Vehicle.objects.filter(customer=customer).order_by('make', 'model', 'year', 'pk')
            notification_items = Notification.objects.filter(
                recipient=request.user,
                is_read=False,
            )[:5]
            repair_orders = RepairOrder.objects.select_related('vehicle__customer').filter(vehicle__customer=customer).exclude(status='cancelled').order_by('-date_created')
            pending_approval = repair_orders.filter(approved=False, estimate_lines__isnull=False).distinct().order_by('-date_created')

            for order in repair_orders[:3]:
                if order.status == 'pending':
                    notifications.append(f"RO#{order.pk} is pending review by a mechanic.")
                elif order.status == 'in_progress':
                    notifications.append(f"RO#{order.pk} is now in progress.")
                elif order.status == 'waiting':
                    notifications.append(f"RO#{order.pk} is waiting for parts.")
                elif order.status == 'ready':
                    notifications.append(f"RO#{order.pk} is ready for pickup.")
                elif order.status == 'completed':
                    notifications.append(f"RO#{order.pk} has been completed.")

            if pending_approval.exists():
                notifications.insert(0, 'You have cost approvals waiting for review.')

        if request.session.pop('new_service_request', False):
            notifications.insert(0, 'Your service request has been submitted. A mechanic will review it and update your vehicle status soon.')

        return render(request, 'workshop/customer_dashboard.html', {
            'customer': customer,
            'vehicles': vehicles,
            'repair_orders': repair_orders,
            'pending_approval': pending_approval,
            'notifications': notifications,
            'notification_items': notification_items,
        })

    if role == 'mechanic':
        assigned_orders = RepairOrder.objects.select_related('vehicle__customer').filter(
            assigned_tech=request.user,
            approved=True,
        ).exclude(status='cancelled').order_by('-date_created')
        active_orders = assigned_orders.exclude(status__in=['completed', 'pending', 'waiting'])[:8]
        waiting_orders = assigned_orders.filter(status='waiting')
        pending_orders = assigned_orders.filter(status='pending')
        my_assignments = Appointment.objects.select_related('customer', 'vehicle', 'repair_order').filter(
            assigned_mechanic=request.user,
            repair_order__approved=True,
        ).exclude(assignment_status='declined').order_by('date_time')
        return render(request, 'workshop/mechanic_dashboard.html', {
            'assigned_orders': assigned_orders,
            'active_orders': active_orders,
            'waiting_orders': waiting_orders,
            'pending_orders': pending_orders,
            'my_assignments': my_assignments,
            'paid_invoices': Invoice.objects.filter(payment_status='paid').count(),
        })

    if role == 'admin':
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        context = {
            'total_customers':       Customer.objects.count(),
            'open_repair_orders':    RepairOrder.objects.exclude(status__in=['completed', 'cancelled']).count(),
            'ready_for_pickup':      RepairOrder.objects.filter(status='ready').count(),
            'todays_appointments':   Appointment.objects.filter(date_time__date=today).count(),
            'low_stock_parts':       Part.objects.filter(stock_qty__lte=models_low_stock()).count(),
            'unpaid_invoices':       Invoice.objects.filter(payment_status='unpaid').count(),
            'partial_invoices':     Invoice.objects.filter(payment_status='partial').count(),
            'paid_invoices':         Invoice.objects.filter(payment_status='paid').count(),
            'verification_invoices': Invoice.objects.filter(payment_status='unverified').count(),
            'status_proposals':      RepairOrder.objects.exclude(pending_status='').select_related('vehicle__customer', 'assigned_tech').order_by('date_updated'),
            'approved_unassigned_orders': RepairOrder.objects.filter(
                approved=True,
                assigned_tech__isnull=True,
            ).exclude(status__in=['cancelled', 'completed']).select_related('vehicle__customer').order_by('date_created'),
            'recent_orders':         RepairOrder.objects.select_related('vehicle__customer').order_by('-date_created')[:8],
            'upcoming_appointments': Appointment.objects.filter(date_time__gte=timezone.now()).select_related('customer', 'vehicle').order_by('date_time')[:5],
            'weekly_revenue':        InvoicePayment.objects.filter(received_at__date__gte=week_start, received_at__date__lte=today).aggregate(total=Sum('amount'))['total'] or 0,
        }
        return render(request, 'workshop/admin_dashboard.html', context)

    # Fallback for no role or unknown role
    today = date.today()
    week_start = today - timedelta(days=today.weekday())

    context = {
        'total_customers':       Customer.objects.count(),
        'open_repair_orders':    RepairOrder.objects.exclude(status__in=['completed', 'cancelled']).count(),
        'ready_for_pickup':      RepairOrder.objects.filter(status='ready').count(),
        'todays_appointments':   Appointment.objects.filter(date_time__date=today).count(),
        'low_stock_parts':       Part.objects.filter(stock_qty__lte=models_low_stock()).count(),
        'unpaid_invoices':       Invoice.objects.filter(payment_status='unpaid').count(),
        'partial_invoices':     Invoice.objects.filter(payment_status='partial').count(),
        'recent_orders':         RepairOrder.objects.select_related('vehicle__customer').order_by('-date_created')[:8],
        'upcoming_appointments': Appointment.objects.filter(date_time__gte=timezone.now()).select_related('customer', 'vehicle').order_by('date_time')[:5],
        'weekly_revenue':        InvoicePayment.objects.filter(received_at__date__gte=week_start, received_at__date__lte=date.today()).aggregate(total=Sum('amount'))['total'] or 0,
    }
    return render(request, 'workshop/dashboard.html', context)


def models_low_stock():
    from django.db.models import F
    return F('reorder_level')


def privacy_policy(request):
    return render(request, 'workshop/privacy_policy.html', {'page_title': 'Privacy Policy'})


def terms_and_conditions(request):
    return render(request, 'workshop/terms_and_conditions.html', {'page_title': 'Terms and Conditions'})


def custom_404(request, exception):
    return render(request, '404.html', {'exception': exception}, status=404)


def custom_500(request):
    return render(request, '500.html', status=500)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  CUSTOMERS
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@login_required
def customer_list(request):
    role = _role(request.user)
    if role == 'customer':
        customer = Customer.objects.filter(email=request.user.email).first()
        customers = Customer.objects.filter(pk=customer.pk) if customer else Customer.objects.none()
    elif role == 'admin' or request.user.is_staff:
        customers = Customer.objects.annotate(vehicle_count=Count('vehicles'))
    else:
        return _deny_access(request)
    q = request.GET.get('q', '')
    if q:
        customers = customers.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q))
    sort = request.GET.get('sort', 'name')
    customer_ordering = {
        'name': ('last_name', 'first_name', 'pk'),
        'name_desc': ('-last_name', '-first_name', '-pk'),
        'newest': ('-created_at', '-pk'),
        'oldest': ('created_at', 'pk'),
    }
    customers = Paginator(customers.order_by(*customer_ordering.get(sort, customer_ordering['name'])), 25).get_page(request.GET.get('page'))
    return render(request, 'workshop/customer_list.html', {'customers': customers, 'q': q, 'sort': sort})


@login_required
def customer_detail(request, pk):
    role = _role(request.user)
    if role == 'customer':
        customer = Customer.objects.filter(email=request.user.email).first()
        if not customer or customer.pk != pk:
            return _deny_access(request)
    elif role == 'mechanic':
        if not RepairOrder.objects.filter(
            vehicle__customer_id=pk,
            assigned_tech=request.user,
        ).exists():
            return _deny_access(request)
    elif not _is_admin(request.user):
        return _deny_access(request)

    customer = get_object_or_404(Customer, pk=pk)
    vehicles = customer.vehicles.all()
    appointments = customer.appointments.order_by('-date_time')[:5]
    return render(request, 'workshop/customer_detail.html', {'customer': customer, 'vehicles': vehicles, 'appointments': appointments})


@login_required
def customer_profile(request):
    customer = Customer.objects.filter(email=request.user.email).first()
    if not customer:
        customer = Customer.objects.create(
            first_name=request.user.first_name or request.user.username,
            last_name='',
            email=request.user.email,
            phone='',
            address='',
            notes='',
        )

    if request.method == 'POST':
        form = CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            changed_fields = form.changed_data
            with transaction.atomic():
                customer = form.save()
                record_audit_entry(
                    request.user,
                    'customer_profile_updated',
                    customer,
                    details={'changed_fields': changed_fields},
                )
                request.user.email = customer.email
                request.user.first_name = customer.first_name
                request.user.last_name = customer.last_name
                request.user.save()
            messages.success(request, 'Your profile has been updated.')
            if customer.has_required_contact_details:
                return redirect('dashboard')
            return redirect('customer_profile')
    else:
        form = CustomerForm(instance=customer)

    return render(request, 'workshop/customer_profile.html', {'customer': customer, 'form': form})


@login_required
def customer_create(request):
    if not _is_admin(request.user):
        return _deny_access(request)
    form = CustomerForm(request.POST or None)
    if form.is_valid():
        customer = form.save()
        record_audit_entry(request.user, 'customer_created', customer)
        messages.success(request, f"Customer '{customer.full_name}' created.")
        return redirect('customer_detail', pk=customer.pk)
    return render(request, 'workshop/customer_form.html', {'form': form, 'title': 'Add Customer'})


@login_required
def customer_edit(request, pk):
    role = _role(request.user)
    if role == 'customer':
        customer = Customer.objects.filter(email=request.user.email).first()
        if not customer or customer.pk != pk:
            return _deny_access(request)
    elif not _is_admin(request.user):
        return _deny_access(request)

    customer = get_object_or_404(Customer, pk=pk)
    form = CustomerForm(request.POST or None, instance=customer)
    if form.is_valid():
        changed_fields = form.changed_data
        with transaction.atomic():
            customer = form.save()
            record_audit_entry(
                request.user,
                'customer_updated',
                customer,
                details={'changed_fields': changed_fields},
            )
        messages.success(request, "Customer updated.")
        return redirect('customer_detail', pk=pk)
    return render(request, 'workshop/customer_form.html', {'form': form, 'title': 'Edit Customer', 'customer': customer})


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  VEHICLES
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@login_required
def vehicle_list(request):
    role = _role(request.user)
    if role == 'customer':
        customer = Customer.objects.filter(email=request.user.email).first()
        vehicles = Vehicle.objects.filter(customer=customer) if customer else Vehicle.objects.none()
    elif role == 'admin' or request.user.is_staff:
        vehicles = Vehicle.objects.select_related('customer').all()
    else:
        return _deny_access(request)
    q = request.GET.get('q', '')
    if q:
        vehicles = vehicles.filter(
            Q(make__icontains=q)
            | Q(model__icontains=q)
            | Q(license_plate__icontains=q)
            | Q(vin__icontains=q)
            | Q(customer__first_name__icontains=q)
            | Q(customer__last_name__icontains=q)
        )
    sort = request.GET.get('sort', 'recent')
    vehicle_ordering = {
        'recent': ('-pk',),
        'make': ('make', 'model', 'year', 'pk'),
        'year': ('-year', 'make', 'model', 'pk'),
        'customer': ('customer__last_name', 'customer__first_name', 'make', 'model'),
    }
    vehicles = Paginator(vehicles.order_by(*vehicle_ordering.get(sort, vehicle_ordering['recent'])), 25).get_page(request.GET.get('page'))
    return render(request, 'workshop/vehicle_list.html', {'vehicles': vehicles, 'q': q, 'sort': sort})


@login_required
def vehicle_detail(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk)
    role = _role(request.user)
    if role == 'customer':
        customer = Customer.objects.filter(email=request.user.email).first()
        if not customer or vehicle.customer_id != customer.pk:
            return _deny_access(request)
    elif role == 'mechanic':
        if not vehicle.repair_orders.filter(assigned_tech=request.user, approved=True).exists():
            return _deny_access(request)
    elif not _is_admin(request.user):
        return _deny_access(request)

    repair_orders = vehicle.repair_orders.exclude(status='cancelled')
    if role == 'mechanic':
        repair_orders = repair_orders.filter(approved=True)
    repair_orders = repair_orders.order_by('-date_created')
    return render(request, 'workshop/vehicle_detail.html', {'vehicle': vehicle, 'repair_orders': repair_orders})


@login_required
def vehicle_create(request):
    if not (_is_admin(request.user) or _role(request.user) == 'customer'):
        return _deny_access(request)
    initial = {}
    customer_id = request.GET.get('customer')
    if customer_id:
        initial['customer'] = customer_id
    form = VehicleForm(request.POST or None, initial=initial, user=request.user)
    if form.is_valid():
        vehicle = form.save(commit=False)
        profile = getattr(request.user, 'userprofile', None)
        if profile and profile.role == 'customer':
            customer = Customer.objects.filter(email=request.user.email).first()
            if customer:
                vehicle.customer = customer
        vehicle.save()
        record_audit_entry(request.user, 'vehicle_created', vehicle)
        messages.success(request, f"Vehicle '{vehicle}' added.")
        return redirect('vehicle_detail', pk=vehicle.pk)
    return render(request, 'workshop/vehicle_form.html', {'form': form, 'title': 'Add Vehicle'})


@login_required
def vehicle_edit(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk)
    if not _is_admin(request.user):
        return _deny_access(request)
    form = VehicleForm(request.POST or None, instance=vehicle)
    if form.is_valid():
        changed_fields = form.changed_data
        with transaction.atomic():
            vehicle = form.save()
            record_audit_entry(
                request.user,
                'vehicle_updated',
                vehicle,
                details={'changed_fields': changed_fields},
            )
        messages.success(request, "Vehicle updated.")
        return redirect('vehicle_detail', pk=pk)
    return render(request, 'workshop/vehicle_form.html', {'form': form, 'title': 'Edit Vehicle', 'vehicle': vehicle})


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  REPAIR ORDERS
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@login_required
def repair_order_list(request):
    status = request.GET.get('status', '')
    query = request.GET.get('q', '').strip()
    mechanic_id = request.GET.get('mechanic', '').strip()
    orders = RepairOrder.objects.select_related('vehicle__customer', 'assigned_tech')
    profile = getattr(request.user, 'userprofile', None)
    if profile and profile.role == 'customer':
        customer = Customer.objects.filter(email=request.user.email).first()
        if customer:
            orders = orders.filter(vehicle__customer=customer)
        else:
            orders = orders.none()
    elif profile and profile.role == 'mechanic':
        orders = orders.filter(assigned_tech=request.user, approved=True)
    elif not _is_admin(request.user):
        orders = orders.none()

    if query:
        search_filter = (
            Q(vehicle__customer__first_name__icontains=query)
            | Q(vehicle__customer__last_name__icontains=query)
            | Q(vehicle__make__icontains=query)
            | Q(vehicle__model__icontains=query)
            | Q(vehicle__license_plate__icontains=query)
            | Q(assigned_tech__first_name__icontains=query)
            | Q(assigned_tech__last_name__icontains=query)
            | Q(assigned_tech__username__icontains=query)
        )
        if query.isdecimal():
            search_filter |= Q(pk=int(query))
        orders = orders.filter(search_filter)

    if mechanic_id.isdecimal() and _is_admin(request.user):
        orders = orders.filter(assigned_tech_id=int(mechanic_id))

    if status:
        if profile and profile.role in ['mechanic', 'admin']:
            orders = orders.filter(Q(status=status) | Q(pending_status=status))
        else:
            orders = orders.filter(status=status)
    else:
        orders = orders.exclude(status='cancelled')
    orders = Paginator(orders.order_by('-date_created', '-pk'), 25).get_page(request.GET.get('page'))

    return render(request, 'workshop/repair_order_list.html', {
        'orders': orders,
        'status': status,
        'q': query,
        'mechanic': mechanic_id,
        'mechanic_action': request.GET.get('action', ''),
        'mechanics': UserProfile.objects.filter(role='mechanic').select_related('user') if _is_admin(request.user) else (),
        'status_choices': RepairOrder.STATUS_CHOICES,
    })


@login_required
def repair_order_detail(request, pk):
    profile = getattr(request.user, 'userprofile', None)
    is_customer = profile and profile.role == 'customer'
    is_mechanic = profile and profile.role == 'mechanic'
    is_admin = (profile and profile.role == 'admin') or request.user.is_staff
    orders = RepairOrder.objects.select_related('vehicle__customer')
    if is_customer:
        customer = Customer.objects.filter(email=request.user.email).first()
        orders = orders.filter(vehicle__customer=customer) if customer else orders.none()
    elif profile and profile.role == 'mechanic':
        orders = orders.filter(assigned_tech=request.user, approved=True)
    order = get_object_or_404(orders, pk=pk)
    if is_customer:
        labor_lines = order.labor_lines.none()
        parts_lines = order.parts_lines.none()
    else:
        labor_lines = order.labor_lines.select_related('service_item')
        parts_lines = order.parts_lines.select_related('part')
    invoice = Invoice.objects.filter(repair_order=order).first()
    events = order.events.select_related('actor')
    if is_customer:
        events = events.filter(customer_visible=True)
    documents = order.documents.order_by('-uploaded_at')
    if is_customer:
        documents = documents.filter(customer_visible=True)
    estimate = order.estimates.first()
    if estimate is None and not order.approved:
        estimate = refresh_pending_estimate(order)
    estimate_lines = order.estimate_lines.select_related('service_item', 'part')
    status_choices = _mechanic_status_choices(order) if is_mechanic else RepairOrder.STATUS_CHOICES
    # Mirrors the blocking rule in repair_order_customer_decision so the UI never
    # offers an approve/decline action the backend will silently refuse.
    has_estimate_lines = estimate_lines.exists()
    estimate_labor_formset = forms.formset_factory(
        EstimateLaborForm,
        extra=0,
        max_num=50,
        validate_max=True,
    )(prefix='labor')
    estimate_part_formset = forms.formset_factory(
        EstimatePartForm,
        extra=0,
        max_num=50,
        validate_max=True,
    )(prefix='parts')
    estimate_catalog = {}
    if is_admin or is_mechanic:
        estimate_catalog = {
            'labor': {
                str(item.pk): str(item.labor_rate)
                for item in ServiceItem.objects.only('pk', 'labor_rate')
            },
            'parts': {
                str(part.pk): {
                    'price': str(part.sell_price),
                    'stock': part.stock_qty,
                }
                for part in Part.objects.only('pk', 'sell_price', 'stock_qty')
            },
        }
    customer_decision_locked = (
        order.status not in {'pending', 'in_progress', 'waiting'}
        or invoice is not None
        or order.labor_lines.exists()
        or order.parts_lines.exists()
    )
    return render(request, 'workshop/repair_order_detail.html', {
        'order': order,
        'labor_lines': labor_lines,
        'parts_lines': parts_lines,
        'is_customer': is_customer,
        'is_mechanic': is_mechanic,
        'is_admin': is_admin,
        'status_choices': status_choices,
        'invoice': invoice,
        'events': events,
        'documents': documents,
        'document_form': RepairDocumentForm() if not is_customer else None,
        'estimate': estimate,
        'estimate_lines': estimate_lines,
        'estimate_labor_formset': estimate_labor_formset if is_admin or is_mechanic else None,
        'estimate_part_formset': estimate_part_formset if is_admin or is_mechanic else None,
        'estimate_notes_form': EstimateNotesForm() if is_admin or is_mechanic else None,
        'estimate_catalog': estimate_catalog,
        'customer_decision_locked': customer_decision_locked,
        'has_estimate_lines': has_estimate_lines,
    })


@login_required
def repair_estimate_line_add(request, pk):
    order = get_object_or_404(RepairOrder, pk=pk)
    profile = getattr(request.user, 'userprofile', None)
    is_admin = (profile and profile.role == 'admin') or request.user.is_staff
    is_assigned_mechanic = profile and profile.role == 'mechanic' and order.approved and order.assigned_tech_id == request.user.pk
    if not is_admin or order.approved:
        return _deny_access(request)
    labor_formset = forms.formset_factory(
        EstimateLaborForm,
        extra=0,
        max_num=50,
        validate_max=True,
    )(request.POST if request.method == 'POST' else None, prefix='labor')
    part_formset = forms.formset_factory(
        EstimatePartForm,
        extra=0,
        max_num=50,
        validate_max=True,
    )(request.POST if request.method == 'POST' else None, prefix='parts')
    notes_form = EstimateNotesForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        labor_valid = labor_formset.is_valid()
        parts_valid = part_formset.is_valid()
        notes_valid = notes_form.is_valid()
        valid = labor_valid and parts_valid and notes_valid
        labor_lines = [form.cleaned_data for form in labor_formset.forms if form.cleaned_data]
        part_lines = [form.cleaned_data for form in part_formset.forms if form.cleaned_data]
        if not labor_lines and not part_lines:
            messages.error(request, 'Add at least one labor service or part to the estimate.')
        elif valid:
            notes = notes_form.cleaned_data.get('notes', '')
            line_count = 0
            with transaction.atomic():
                for line_data in labor_lines:
                    service_item = line_data['service_item']
                    RepairEstimateLine.objects.create(
                        repair_order=order,
                        line_type='labor',
                        service_item=service_item,
                        quantity=line_data['hours'],
                        unit_price=service_item.labor_rate,
                        notes=notes,
                        created_by=request.user,
                    )
                    line_count += 1
                for line_data in part_lines:
                    part = line_data['part']
                    RepairEstimateLine.objects.create(
                        repair_order=order,
                        line_type='part',
                        part=part,
                        quantity=line_data['quantity'],
                        unit_price=part.sell_price,
                        notes=notes,
                        created_by=request.user,
                    )
                    line_count += 1
                refresh_pending_estimate(order)
                record_repair_event(
                    order,
                    request.user,
                    'work_logged',
                    note=f'Estimate updated with {len(labor_lines)} service item(s) and {len(part_lines)} part(s).',
                    metadata={'service_items': len(labor_lines), 'parts': len(part_lines)},
                )
            messages.success(request, f'Added {line_count} line(s) to the estimate.')
        else:
            for formset in (labor_formset, part_formset):
                for error in formset.non_form_errors():
                    messages.error(request, error)
                for line_form in formset.forms:
                    for field_errors in line_form.errors.values():
                        for error in field_errors:
                            messages.error(request, error)
            for field_errors in notes_form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
    return redirect('repair_order_detail', pk=pk)


@login_required
def repair_document_upload(request, pk):
    order = get_object_or_404(RepairOrder, pk=pk)
    profile = getattr(request.user, 'userprofile', None)
    is_admin = (profile and profile.role == 'admin') or request.user.is_staff
    is_assigned_mechanic = profile and profile.role == 'mechanic' and order.approved and order.assigned_tech_id == request.user.pk
    if not (is_admin or is_assigned_mechanic):
        return _deny_access(request)
    if request.method != 'POST':
        return redirect('repair_order_detail', pk=pk)

    form = RepairDocumentForm(request.POST, request.FILES)
    if form.is_valid():
        document = form.save(commit=False)
        document.repair_order = order
        document.uploaded_by = request.user
        document.save()
        record_repair_event(order, request.user, 'work_logged', note=f'Document uploaded: {document.title}.')
        messages.success(request, 'Repair document uploaded.')
    else:
        for error in form.errors.get('__all__', []):
            messages.error(request, error)
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)
    return redirect('repair_order_detail', pk=pk)


@login_required
def repair_document_download(request, pk):
    document = get_object_or_404(RepairDocument.objects.select_related('repair_order__vehicle__customer'), pk=pk)
    order = document.repair_order
    profile = getattr(request.user, 'userprofile', None)
    is_admin = (profile and profile.role == 'admin') or request.user.is_staff
    is_customer = profile and profile.role == 'customer'
    is_assigned_mechanic = profile and profile.role == 'mechanic' and order.approved and order.assigned_tech_id == request.user.pk
    if is_customer:
        customer = Customer.objects.filter(email=request.user.email).first()
        allowed = customer and order.vehicle.customer_id == customer.pk and document.customer_visible
    else:
        allowed = is_admin or is_assigned_mechanic
    if not allowed:
        return _deny_access(request)
    return FileResponse(
        document.file.open('rb'),
        as_attachment=True,
        filename=document.file.name.rsplit('/', 1)[-1],
    )


@login_required
def repair_order_create(request):
    profile = getattr(request.user, 'userprofile', None)
    is_admin = (profile and profile.role == 'admin') or request.user.is_staff

    if not is_admin:
        messages.error(request, 'Only admins can create repair orders.')
        return redirect('dashboard')

    form = RepairOrderForm(request.POST or None)
    form.fields.pop('status')
    form.fields.pop('approved')
    form.fields.pop('assignment_reason')
    form.fields.pop('assigned_tech')
    if form.is_valid():
        order = form.save()
        record_repair_event(order, request.user, 'created', current_status=order.status, customer_visible=True)
        messages.success(request, f"Repair Order #{order.pk} created.")
        return redirect('repair_order_detail', pk=order.pk)
    return render(request, 'workshop/repair_order_form.html', {'form': form, 'title': 'New Repair Order'})


@login_required
def repair_order_edit(request, pk):
    order = get_object_or_404(RepairOrder, pk=pk)
    profile = getattr(request.user, 'userprofile', None)
    role = profile.role if profile else ('admin' if request.user.is_staff else '')
    if role == 'customer' or (role == 'mechanic' and order.assigned_tech_id != request.user.pk):
        messages.error(request, 'You may only update repair orders assigned to you.')
        return redirect('dashboard')

    previous_assigned_tech_id = order.assigned_tech_id
    form = RepairOrderForm(request.POST or None, instance=order)
    form.fields.pop('status')
    form.fields.pop('approved')
    form.fields['vehicle'].disabled = True
    assignment_locked = role == 'admin' and not order.approved
    if assignment_locked:
        form.fields.pop('assigned_tech')
    if role == 'admin' and not order.approved and request.method == 'POST':
        posted_mechanic_id = request.POST.get('assigned_tech')
        if posted_mechanic_id is not None and posted_mechanic_id != str(previous_assigned_tech_id or ''):
            form.add_error(None, 'The customer must approve this repair before a mechanic can be assigned.')
            return render(request, 'workshop/repair_order_form.html', {'form': form, 'title': 'Edit Repair Order', 'order': order})
    if role == 'mechanic':
        if not order.approved:
            return _deny_access(request)
        for field_name in ['assigned_tech', 'description', 'mileage_in']:
            form.fields[field_name].disabled = True
        form.fields['assignment_reason'].widget = forms.HiddenInput()
    if form.is_valid():
        assignment_reason = (form.cleaned_data.get('assignment_reason') or '').strip()
        assigned_tech_id = getattr(form.cleaned_data.get('assigned_tech'), 'pk', None)
        assignment_changed = 'assigned_tech' in form.cleaned_data and previous_assigned_tech_id != assigned_tech_id
        if role == 'admin' and assignment_changed and not assignment_reason:
            form.add_error('assignment_reason', 'Please explain why the mechanic is being changed.')
            return render(request, 'workshop/repair_order_form.html', {'form': form, 'title': 'Edit Repair Order', 'order': order})
        changed_fields = form.changed_data
        with transaction.atomic():
            order = form.save()
            if changed_fields:
                details = {'changed_fields': changed_fields}
                if previous_assigned_tech_id != order.assigned_tech_id:
                    details['assignment'] = {
                        'from_user_id': previous_assigned_tech_id,
                        'to_user_id': order.assigned_tech_id,
                    }
                record_audit_entry(
                    request.user,
                    'repair_order_updated',
                    order,
                    repair_order=order,
                    details=details,
                )
                if previous_assigned_tech_id != order.assigned_tech_id:
                    previous_mechanic = User.objects.filter(pk=previous_assigned_tech_id).first()
                    current_mechanic = order.assigned_tech
                    assignment_note = (
                        f"Mechanic assignment changed from "
                        f"{previous_mechanic.get_full_name() or previous_mechanic.username if previous_mechanic else 'Unassigned'} "
                        f"to {current_mechanic.get_full_name() or current_mechanic.username if current_mechanic else 'Unassigned'}. "
                        f"Reason: {assignment_reason}"
                    )
                    record_repair_event(
                        order,
                        request.user,
                        'assignment',
                        note=assignment_note,
                        customer_visible=True,
                        metadata={
                            'from_user_id': previous_assigned_tech_id,
                            'to_user_id': order.assigned_tech_id,
                        },
                    )
        messages.success(request, "Repair Order updated.")
        return redirect('repair_order_detail', pk=pk)
    return render(request, 'workshop/repair_order_form.html', {
        'form': form,
        'title': 'Edit Repair Order',
        'order': order,
        'assignment_locked': assignment_locked,
    })


@login_required
@require_POST
def repair_order_decision(request, pk, action):
    if action not in ['accept', 'decline']:
        messages.error(request, 'Invalid job decision.')
        return redirect('dashboard')

    profile = getattr(request.user, 'userprofile', None)
    if not profile or profile.role != 'mechanic':
        messages.error(request, 'Only mechanics can accept or decline assigned jobs.')
        return redirect('dashboard')

    order = get_object_or_404(
        RepairOrder,
        pk=pk,
        assigned_tech=request.user,
        approved=True,
        status='pending',
    )
    if action == 'accept':
        order.pending_status = 'in_progress'
        order.save(update_fields=['pending_status', 'date_updated'])
        record_repair_event(
            order,
            request.user,
            'status_proposed',
            current_status='in_progress',
            note='Mechanic accepted the assigned repair.',
            metadata={'pending': True},
        )
        messages.success(request, f'You accepted repair order #{order.pk}. The status update is awaiting admin approval.')
    else:
        reason = (request.POST.get('reason') or '').strip()
        if not reason:
            messages.error(request, 'Please provide a reason for declining this repair.')
            return redirect('dashboard')
        order.assigned_tech = None
        order.save(update_fields=['assigned_tech', 'date_updated'])
        record_repair_event(
            order,
            request.user,
            'assignment',
            note=f'Mechanic declined the assigned repair. Reason: {reason}',
            customer_visible=True,
        )
        messages.info(request, f'You declined repair order #{order.pk}. It is available for admin reassignment.')

    return redirect('dashboard')


@login_required
@require_POST
@transaction.atomic
def repair_order_customer_decision(request, pk, action):
    if action not in ['approve', 'decline', 'collect']:
        messages.error(request, 'Invalid approval decision.')
        return redirect('dashboard')

    profile = getattr(request.user, 'userprofile', None)
    if not profile or profile.role != 'customer':
        messages.error(request, 'Only customers can approve or decline their repair estimates.')
        return redirect('dashboard')

    customer = Customer.objects.filter(email=request.user.email).first()
    order = get_object_or_404(RepairOrder.objects.select_for_update(), pk=pk)
    if not customer or order.vehicle.customer_id != customer.pk:
        messages.error(request, 'You can only review repairs for your own vehicles.')
        return redirect('dashboard')

    if action == 'collect':
        invoice = getattr(order, 'invoice', None)
        if order.status != 'ready':
            messages.error(request, 'This vehicle is not ready for collection yet.')
        elif not invoice or invoice.payment_status != 'paid':
            messages.error(request, 'Your invoice must be fully paid before we can close this repair as collected.')
        else:
            previous_status = order.status
            order.status = 'completed'
            order.pending_status = ''
            order.date_completed = timezone.now()
            order.save(update_fields=['status', 'pending_status', 'date_completed', 'date_updated'])
            CollectionRecord.objects.get_or_create(
                repair_order=order,
                defaults={'collected_by': request.user},
            )
            record_repair_event(
                order,
                request.user,
                'collected',
                previous_status=previous_status,
                current_status=order.status,
                customer_visible=True,
                note='Customer confirmed vehicle collection.',
            )
            messages.success(request, f'You confirmed pickup for RO#{order.pk}. The repair is now complete.')
        return redirect('repair_order_detail', pk=order.pk)

    if order.approved:
        messages.info(request, f'You have already approved the estimate for RO#{order.pk}. Contact the workshop if you need to discuss a change.')
        return redirect('repair_order_detail', pk=order.pk)
    if not order.estimate_lines.exists():
        messages.error(request, 'No estimate has been prepared for this repair yet. You can approve or decline once the workshop has sent one.')
        return redirect('repair_order_detail', pk=order.pk)
    approval_window_statuses = {'pending', 'in_progress', 'waiting'}
    if (
        order.status not in approval_window_statuses
        or getattr(order, 'invoice', None)
        or order.labor_lines.exists()
        or order.parts_lines.exists()
    ):
        messages.error(request, 'The estimate can no longer be changed after workshop work has started.')
        return redirect('repair_order_detail', pk=order.pk)

    estimate = order.estimates.filter(status='pending').first()
    if estimate is None:
        estimate = refresh_pending_estimate(order)

    order.approved = action == 'approve'
    if action == 'decline':
        order.pending_status = ''
    order.save(update_fields=['approved', 'pending_status', 'date_updated'])
    estimate.status = 'approved' if order.approved else 'declined'
    estimate.decided_by = request.user
    estimate.decided_at = timezone.now()
    estimate.save(update_fields=['status', 'decided_by', 'decided_at'])
    record_repair_event(
        order,
        request.user,
        'approval',
        customer_visible=True,
        note=f'Customer {"approved" if order.approved else "declined"} the repair estimate.',
        metadata={
            'approved': order.approved,
            'estimate_version': estimate.version,
            'estimate_total': str(estimate.total_amount),
        },
    )
    if action == 'approve':
        messages.success(request, f'You approved the repair estimate for RO#{order.pk}. The workshop can proceed.')
    else:
        messages.info(request, f'You declined the repair estimate for RO#{order.pk}. The workshop will review the next steps.')

    return redirect('repair_order_detail', pk=order.pk)


@login_required
@require_POST
def repair_order_status_proposal(request, pk):
    profile = getattr(request.user, 'userprofile', None)
    if not profile or profile.role != 'mechanic':
        messages.error(request, 'Only mechanics can propose repair status changes.')
        return redirect('dashboard')

    order = get_object_or_404(RepairOrder, pk=pk, assigned_tech=request.user, approved=True)
    if order.status in {'completed', 'cancelled'}:
        messages.error(request, 'Closed repair orders cannot receive status proposals.')
        return redirect('repair_order_detail', pk=order.pk)
    if order.pending_status:
        messages.info(request, f'Repair order #{order.pk} already has a status update awaiting approval.')
        return redirect('repair_order_detail', pk=order.pk)

    proposed_status = request.POST.get('status', '')
    valid_statuses = dict(RepairOrder.STATUS_CHOICES)
    allowed_statuses = {value for value, _ in _mechanic_status_choices(order)}
    if proposed_status not in allowed_statuses or proposed_status == order.status:
        messages.error(request, 'Choose a different valid repair status.')
        return redirect('repair_order_detail', pk=order.pk)

    order.pending_status = proposed_status
    order.save(update_fields=['pending_status', 'date_updated'])
    record_repair_event(
        order,
        request.user,
        'status_proposed',
        current_status=proposed_status,
        note='Mechanic proposed a status change.',
        metadata={'pending': True},
    )
    messages.success(request, f'{valid_statuses[proposed_status]} proposed for repair order #{order.pk}. An admin must approve it before customers see the update.')
    return redirect('repair_order_detail', pk=order.pk)


@login_required
@require_POST
def repair_order_finalize(request, pk, action):
    if action not in ['ready', 'complete']:
        messages.error(request, 'Invalid final workshop action.')
        return redirect('dashboard')

    profile = getattr(request.user, 'userprofile', None)
    role = profile.role if profile else ('admin' if request.user.is_staff else '')
    if role != 'admin':
        messages.error(request, 'Only admins can finalize a repair order.')
        return redirect('dashboard')

    order = get_object_or_404(RepairOrder.objects.select_related('vehicle__customer', 'invoice'), pk=pk)
    if not order.approved:
        messages.error(request, 'The customer must approve the repair estimate before the workshop can advance this job.')
        return redirect('repair_order_detail', pk=order.pk)
    if action == 'ready':
        if order.status not in {'in_progress', 'waiting'}:
            messages.error(request, 'A repair order must be in progress or waiting for parts before it can be marked ready.')
            return redirect('repair_order_detail', pk=order.pk)
        previous_status = order.status
        order.status = 'ready'
        order.pending_status = ''
        order.save(update_fields=['status', 'pending_status', 'date_updated'])
        record_repair_event(order, request.user, 'status_changed', previous_status=previous_status, current_status=order.status, customer_visible=True)
        messages.success(request, f'Repair order #{order.pk} is now marked ready for pickup.')
    else:
        invoice = getattr(order, 'invoice', None)
        if order.status != 'ready':
            messages.error(request, 'A repair order must be marked ready for pickup before it can be completed.')
            return redirect('repair_order_detail', pk=order.pk)
        if not invoice or invoice.payment_status != 'paid':
            messages.error(request, 'A repair order can only be marked complete once the invoice is fully paid.')
            return redirect('repair_order_detail', pk=order.pk)
        previous_status = order.status
        order.status = 'completed'
        order.pending_status = ''
        order.date_completed = timezone.now()
        order.save(update_fields=['status', 'pending_status', 'date_completed', 'date_updated'])
        record_repair_event(order, request.user, 'status_changed', previous_status=previous_status, current_status=order.status, customer_visible=True)
        messages.success(request, f'Repair order #{order.pk} has been completed.')
    return redirect('repair_order_detail', pk=order.pk)


@login_required
@require_POST
def repair_order_cancel(request, pk):
    profile = getattr(request.user, 'userprofile', None)
    role = profile.role if profile else ('admin' if request.user.is_staff else '')
    if role != 'admin':
        messages.error(request, 'Only admins can cancel a repair order.')
        return redirect('dashboard')

    with transaction.atomic():
        order = get_object_or_404(
            RepairOrder.objects.select_for_update().prefetch_related('parts_lines__part'),
            pk=pk,
        )
        has_invoice = Invoice.objects.filter(repair_order=order).exists()
        if order.status == 'cancelled':
            messages.info(request, f'Repair order #{order.pk} has already been cancelled.')
            return redirect('repair_order_detail', pk=order.pk)
        if order.status == 'completed' or has_invoice:
            messages.error(request, 'Completed or invoiced repair orders cannot be cancelled.')
            return redirect('repair_order_detail', pk=order.pk)

        for line in order.parts_lines.select_related('part'):
            part = Part.objects.select_for_update().get(pk=line.part.pk)
            stock_before = part.stock_qty
            part.stock_qty += line.quantity
            part.save(update_fields=['stock_qty'])
            record_audit_entry(
                request.user,
                'inventory_stock_restored',
                line,
                repair_order=order,
                details={
                    'part_id': part.pk,
                    'quantity': line.quantity,
                    'stock_before': stock_before,
                    'stock_after': part.stock_qty,
                },
            )

        previous_status = order.status
        order.status = 'cancelled'
        order.pending_status = ''
        order.date_completed = None
        order.save(update_fields=['status', 'pending_status', 'date_completed', 'date_updated'])
        record_repair_event(order, request.user, 'cancelled', previous_status=previous_status, current_status=order.status, customer_visible=True)

    messages.success(request, f'Repair order #{order.pk} has been cancelled and stock has been restored.')
    return redirect('repair_order_detail', pk=order.pk)


@login_required
@require_POST
@require_POST
def repair_order_status_review(request, pk, action):
    profile = getattr(request.user, 'userprofile', None)
    role = profile.role if profile else ('admin' if request.user.is_staff else '')
    if role != 'admin':
        messages.error(request, 'Only admins can review repair status changes.')
        return redirect('dashboard')
    if action not in ['approve', 'reject']:
        messages.error(request, 'Invalid status review action.')
        return redirect('dashboard')

    order = get_object_or_404(RepairOrder.objects.exclude(pending_status=''), pk=pk)
    if action == 'approve':
        allowed_statuses = {value for value, _ in _mechanic_status_choices(order)}
        if order.pending_status not in allowed_statuses:
            order.pending_status = ''
            order.save(update_fields=['pending_status', 'date_updated'])
            messages.error(request, 'This status proposal is no longer valid for the repair order.')
            return redirect('dashboard')
        if not order.approved:
            messages.error(request, 'The customer must approve the estimate before work can begin.')
            return redirect('dashboard')
        previous_status = order.status
        order.status = order.pending_status
        order.pending_status = ''
        order.save(update_fields=['status', 'pending_status', 'date_updated'])
        record_repair_event(order, request.user, 'status_changed', previous_status=previous_status, current_status=order.status, customer_visible=True)
        messages.success(request, f'Status for repair order #{order.pk} approved and published to the customer.')
    else:
        reason = (request.POST.get('reason') or '').strip()
        if not reason:
            messages.error(request, 'Please provide a reason for rejecting this status update.')
            return redirect('dashboard')
        proposed_status = order.pending_status
        with transaction.atomic():
            order.pending_status = ''
            order.save(update_fields=['pending_status', 'date_updated'])
            record_repair_event(
                order,
                request.user,
                'status_rejected',
                current_status=proposed_status,
                note=f'The proposed status "{dict(RepairOrder.STATUS_CHOICES).get(proposed_status, proposed_status)}" was rejected. Reason: {reason}',
                customer_visible=True,
                metadata={'proposed_status': proposed_status, 'reason': reason},
            )
        messages.info(request, f'Status update for repair order #{order.pk} rejected.')
    return redirect('dashboard')


@login_required
def add_labor_line(request, ro_pk):
    order = get_object_or_404(RepairOrder, pk=ro_pk)
    profile = getattr(request.user, 'userprofile', None)
    is_admin = (profile and profile.role == 'admin') or request.user.is_staff
    is_assigned_mechanic = profile and profile.role == 'mechanic' and order.approved and order.assigned_tech_id == request.user.pk
    if not (is_admin or is_assigned_mechanic):
        messages.error(request, 'Only an admin or the assigned mechanic may add labor to this repair order.')
        return redirect('dashboard')
    if Invoice.objects.filter(repair_order=order).exists():
        messages.error(request, 'This repair order already has an invoice; its work lines are locked.')
        return redirect('repair_order_detail', pk=ro_pk)
    if not order.approved:
        messages.error(request, 'The customer must approve the repair estimate before labor can be logged.')
        return redirect('repair_order_detail', pk=ro_pk)
    form = LaborLineForm(request.POST or None)
    if form.is_valid():
        line = form.save(commit=False)
        line.repair_order = order
        with transaction.atomic():
            line.save()
            record_audit_entry(
                request.user,
                'labor_logged',
                line,
                repair_order=order,
                details={
                    'service_item_id': line.service_item_id,
                    'hours': format(line.hours, '.2f'),
                    'rate': str(line.rate),
                    'line_total': str(line.line_total),
                },
            )
        messages.success(request, "Labor line added.")
        return redirect('repair_order_detail', pk=ro_pk)
    return render(request, 'workshop/line_item_form.html', {'form': form, 'order': order, 'title': 'Add Labor Line'})


@login_required
def add_parts_line(request, ro_pk):
    order = get_object_or_404(RepairOrder, pk=ro_pk)
    profile = getattr(request.user, 'userprofile', None)
    is_admin = (profile and profile.role == 'admin') or request.user.is_staff
    is_assigned_mechanic = profile and profile.role == 'mechanic' and order.approved and order.assigned_tech_id == request.user.pk
    if not (is_admin or is_assigned_mechanic):
        messages.error(request, 'Only an admin or the assigned mechanic may add parts to this repair order.')
        return redirect('dashboard')
    if Invoice.objects.filter(repair_order=order).exists():
        messages.error(request, 'This repair order already has an invoice; its work lines are locked.')
        return redirect('repair_order_detail', pk=ro_pk)
    if not order.approved:
        messages.error(request, 'The customer must approve the repair estimate before parts can be logged.')
        return redirect('repair_order_detail', pk=ro_pk)
    form = PartsLineForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        quantity = form.cleaned_data['quantity']
        part = form.cleaned_data['part']
        if quantity <= 0:
            form.add_error('quantity', 'Quantity must be greater than zero.')
        elif part.stock_qty < quantity:
            form.add_error('quantity', f'Not enough stock for {part.name}. Available: {part.stock_qty}.')
        if form.errors:
            return render(request, 'workshop/line_item_form.html', {'form': form, 'order': order, 'title': 'Add Parts Line'})
        with transaction.atomic():
            part = Part.objects.select_for_update().get(pk=part.pk)
            if part.stock_qty < quantity:
                messages.error(request, f'Not enough stock for {part.name}. Available: {part.stock_qty}.')
                return redirect('repair_order_detail', pk=ro_pk)
            line = form.save(commit=False)
            line.repair_order = order
            line.save()
            stock_before = part.stock_qty
            part.stock_qty -= quantity
            part.save(update_fields=['stock_qty'])
            record_audit_entry(
                request.user,
                'inventory_stock_used',
                line,
                repair_order=order,
                details={
                    'part_id': part.pk,
                    'quantity': quantity,
                    'stock_before': stock_before,
                    'stock_after': part.stock_qty,
                    'unit_price': str(line.unit_price),
                },
            )
        messages.success(request, "Parts line added and inventory updated.")
        return redirect('repair_order_detail', pk=ro_pk)
    return render(request, 'workshop/line_item_form.html', {'form': form, 'order': order, 'title': 'Add Parts Line'})


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  INVOICES
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@login_required
def invoice_list(request):
    profile = getattr(request.user, 'userprofile', None)
    if not _is_admin(request.user) and not (profile and profile.role in ['customer', 'mechanic']):
        return _deny_access(request)
    invoices = Invoice.objects.select_related('repair_order__vehicle__customer').annotate(
        report_paid_amount=Sum('payments__amount')
    ).order_by('-issue_date')
    if profile and profile.role == 'customer':
        customer = Customer.objects.filter(email=request.user.email).first()
        if customer:
            invoices = invoices.filter(repair_order__vehicle__customer=customer)
        else:
            invoices = invoices.none()
    elif profile and profile.role == 'mechanic':
        invoices = invoices.filter(repair_order__assigned_tech=request.user)

    status = request.GET.get('status', '')
    if status:
        invoices = invoices.filter(payment_status=status)
    query = request.GET.get('q', '').strip()
    if query:
        search_filter = (
            Q(repair_order__vehicle__customer__first_name__icontains=query)
            | Q(repair_order__vehicle__customer__last_name__icontains=query)
            | Q(repair_order__vehicle__license_plate__icontains=query)
        )
        if query.isdecimal():
            search_filter |= Q(pk=int(query))
        invoices = invoices.filter(search_filter)
    start_date = parse_date(request.GET.get('start_date', ''))
    end_date = parse_date(request.GET.get('end_date', ''))
    if start_date:
        invoices = invoices.filter(issue_date__gte=start_date)
    if end_date:
        invoices = invoices.filter(issue_date__lte=end_date)
    invoices = Paginator(invoices.order_by('-issue_date', '-pk'), 25).get_page(request.GET.get('page'))

    return render(request, 'workshop/invoice_list.html', {
        'invoices': invoices,
        'status': status,
        'q': query,
        'start_date': start_date,
        'end_date': end_date,
        'role': profile.role if profile else ('admin' if request.user.is_staff else ''),
    })


@login_required
def invoice_detail(request, pk):
    profile = getattr(request.user, 'userprofile', None)
    invoice = get_object_or_404(Invoice, pk=pk)
    is_customer = profile and profile.role == 'customer'
    is_admin = (profile and profile.role == 'admin') or request.user.is_staff
    if is_customer:
        customer = Customer.objects.filter(email=request.user.email).first()
        if invoice.repair_order.vehicle.customer != customer:
            return _deny_access(request)
    elif profile and profile.role == 'mechanic':
        if invoice.repair_order.assigned_tech_id != request.user.pk:
            return _deny_access(request)
    elif not is_admin:
        return _deny_access(request)

    return render(request, 'workshop/invoice_detail_fixed.html', {
        'invoice': invoice,
        'is_customer': is_customer,
        'is_admin': is_admin,
    })


@login_required
def invoice_download(request, pk):
    profile = getattr(request.user, 'userprofile', None)
    invoice = get_object_or_404(Invoice.objects.select_related('repair_order__vehicle__customer'), pk=pk)
    is_customer = profile and profile.role == 'customer'
    is_admin = (profile and profile.role == 'admin') or request.user.is_staff
    if is_customer:
        customer = Customer.objects.filter(email=request.user.email).first()
        if not customer or invoice.repair_order.vehicle.customer_id != customer.pk:
            return _deny_access(request)
    elif profile and profile.role == 'mechanic':
        if invoice.repair_order.assigned_tech_id != request.user.pk:
            return _deny_access(request)
    elif not is_admin:
        return _deny_access(request)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="invoice-{invoice.pk}.csv"'
    writer = csv.writer(response)
    writer.writerow(['Invoice', f'#{invoice.pk}'])
    writer.writerow(['Customer', invoice.repair_order.vehicle.customer.full_name])
    writer.writerow(['Vehicle', str(invoice.repair_order.vehicle)])
    writer.writerow(['Payment status', invoice.get_payment_status_display()])
    writer.writerow(['Subtotal', format_rand(invoice.subtotal)])
    writer.writerow(['Tax', format_rand(invoice.tax_amount)])
    writer.writerow(['Total due', format_rand(invoice.total_due)])
    writer.writerow(['Amount paid', format_rand(invoice.paid_amount)])
    writer.writerow(['Balance due', format_rand(invoice.balance_due)])
    writer.writerow([])
    writer.writerow(['Payment date', 'Amount', 'Method', 'Reference'])
    for payment in invoice.payments.all():
        writer.writerow([
            payment.received_at.isoformat(),
            format_rand(payment.amount),
            payment.get_payment_method_display(),
            payment.reference,
        ])
    return response


@login_required
def invoice_create(request):
    profile = getattr(request.user, 'userprofile', None)
    is_admin = (profile and profile.role == 'admin') or request.user.is_staff
    if not is_admin:
        messages.error(request, 'Only an admin can create invoices.')
        return redirect('invoice_list')

    repair_order_id = request.GET.get('ro')
    repair_order = None

    if repair_order_id:
        repair_order = get_object_or_404(
            RepairOrder,
            pk=repair_order_id
        )
        existing_invoice = Invoice.objects.filter(repair_order=repair_order).first()
        if existing_invoice:
            messages.info(request, f'Repair order #{repair_order.pk} already has invoice #{existing_invoice.pk}.')
            return redirect('invoice_detail', pk=existing_invoice.pk)
        if repair_order.status == 'cancelled':
            messages.error(request, 'Cancelled repair orders cannot be invoiced.')
            return redirect('repair_order_detail', pk=repair_order.pk)
        if not repair_order.approved:
            messages.error(request, 'A customer must approve the repair estimate before an invoice can be created.')
            return redirect('repair_order_detail', pk=repair_order.pk)

    initial = {}

    if repair_order:
        initial['repair_order'] = repair_order.pk
        initial['service_amount'] = repair_order.invoice_amount

    form = InvoiceForm(
        request.POST or None,
        initial=initial
    )
    invoice_amounts = {
        str(order.pk): str(order.invoice_amount)
        for order in form.fields['repair_order'].queryset.select_related('vehicle')
    }

    if form.is_valid():
        with transaction.atomic():
            invoice = form.save()
            record_audit_entry(
                request.user,
                'invoice_created',
                invoice,
                repair_order=invoice.repair_order,
                details={
                    'service_amount': str(invoice.service_amount),
                    'total_due': str(invoice.total_due),
                    'due_date': invoice.due_date.isoformat(),
                },
            )

        # Send invoice-ready email to the customer
        try:
            send_invoice_ready_email(
                request,
                invoice
            )
        except Exception:
            messages.warning(
                request,
                'Invoice created, but the notification email could not be sent.'
            )

        messages.success(
            request,
            f"Invoice #{invoice.pk} created."
        )

        return redirect(
            'invoice_detail',
            pk=invoice.pk
        )

    return render(
        request,
        'workshop/invoice_form.html',
        {
            'form': form,
            'title': 'Create Invoice',
            'invoice_amounts': invoice_amounts,
        }
    )

@login_required
def invoice_edit(request, pk):
    profile = getattr(request.user, 'userprofile', None)
    is_admin = (profile and profile.role == 'admin') or request.user.is_staff
    if not is_admin:
        messages.error(request, 'Only an admin can edit invoices.')
        return redirect('invoice_detail', pk=pk)

    invoice = get_object_or_404(Invoice, pk=pk)
    if invoice.payments.exists():
        messages.error(request, 'Invoices with recorded payments cannot be edited. Contact an admin to resolve a billing adjustment.')
        return redirect('invoice_detail', pk=pk)
    tracked_fields = ('service_amount', 'discount', 'tax_rate', 'due_date')
    previous_values = {field: str(getattr(invoice, field)) for field in tracked_fields}
    form = InvoiceForm(request.POST or None, instance=invoice)
    if form.is_valid():
        with transaction.atomic():
            invoice = form.save()
            changes = {
                field: {'from': previous_values[field], 'to': str(getattr(invoice, field))}
                for field in tracked_fields
                if previous_values[field] != str(getattr(invoice, field))
            }
            record_audit_entry(
                request.user,
                'invoice_updated',
                invoice,
                repair_order=invoice.repair_order,
                details={'changes': changes},
            )
        messages.success(request, "Invoice updated.")
        return redirect('invoice_detail', pk=pk)
    return render(request, 'workshop/invoice_form.html', {'form': form, 'title': 'Edit Invoice', 'invoice': invoice})


@login_required
def invoice_pay(request, pk):
    profile = getattr(request.user, 'userprofile', None)
    is_admin = (profile and profile.role == 'admin') or request.user.is_staff
    is_customer = profile and profile.role == 'customer'
    invoice = get_object_or_404(Invoice.objects.select_related('repair_order__vehicle__customer'), pk=pk)

    if is_customer:
        customer = Customer.objects.filter(email=request.user.email).first()
        if not customer or invoice.repair_order.vehicle.customer_id != customer.pk:
            return _deny_access(request)
    elif not is_admin:
        messages.error(request, 'Only an admin can record a verified payment.')
        return redirect('invoice_detail', pk=pk)

    if invoice.payment_status == 'paid':
        messages.info(request, f'Invoice #{invoice.pk} has already been paid.')
        return redirect('invoice_detail', pk=invoice.pk)

    if is_customer:
        valid_methods = dict(Invoice.METHOD_CHOICES)
        payment_method = request.POST.get('payment_method', '').strip()
        if request.method == 'POST' and payment_method in valid_methods:
            with transaction.atomic():
                invoice = Invoice.objects.select_for_update().get(pk=pk)
                amount = invoice.balance_due
                if invoice.payment_status != 'paid' and amount > 0:
                    payment = InvoicePayment.objects.create(
                        invoice=invoice,
                        amount=amount,
                        payment_method=payment_method,
                        notes='Customer-submitted payment method.',
                        recorded_by=request.user,
                    )
                    invoice.refresh_payment_status(payment_method=payment.payment_method)
                    record_repair_event(
                        invoice.repair_order,
                        request.user,
                        'payment',
                        customer_visible=True,
                        note=f'Payment of R {payment.amount:.2f} submitted by customer.',
                        metadata={
                            'amount': str(payment.amount),
                            'payment_method': payment.payment_method,
                            'invoice_id': invoice.pk,
                            'payment_id': payment.pk,
                            'balance_due': str(invoice.balance_due),
                            'payment_status': invoice.payment_status,
                        },
                    )
                    record_audit_entry(
                        request.user,
                        'invoice_payment_recorded',
                        payment,
                        repair_order=invoice.repair_order,
                        details={
                            'invoice_id': invoice.pk,
                            'amount': str(payment.amount),
                            'payment_method': payment.payment_method,
                            'balance_due': str(invoice.balance_due),
                            'payment_status': invoice.payment_status,
                            'customer_submitted': True,
                        },
                    )
                    messages.success(request, f'Payment submitted for invoice #{invoice.pk}.')
                    return redirect('invoice_detail', pk=pk)
                messages.info(request, f'Invoice #{invoice.pk} has already been paid.')
                return redirect('invoice_detail', pk=pk)

        return render(request, 'workshop/invoice_payment.html', {
            'invoice': invoice,
            'is_customer': True,
            'payment_methods': Invoice.METHOD_CHOICES,
            'payment_error': 'Please choose a valid payment method.' if request.method == 'POST' else '',
        })

    form = InvoicePaymentForm(request.POST or None, invoice=invoice)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            invoice = Invoice.objects.select_for_update().get(pk=pk)
            amount = form.cleaned_data['amount']
            if invoice.payment_status == 'paid' or amount > invoice.balance_due:
                form.add_error('amount', 'The invoice balance changed. Refresh and enter an amount up to the current balance.')
            else:
                payment = InvoicePayment.objects.create(
                    invoice=invoice,
                    amount=amount,
                    payment_method=form.cleaned_data['payment_method'],
                    reference=form.cleaned_data['reference'],
                    notes=form.cleaned_data['notes'],
                    recorded_by=request.user,
                )
                invoice.refresh_payment_status(payment_method=payment.payment_method)
                record_repair_event(
                    invoice.repair_order,
                    request.user,
                    'payment',
                    customer_visible=True,
                    note=f'Payment of R {payment.amount:.2f} recorded.',
                    metadata={
                        'amount': str(payment.amount),
                        'payment_method': payment.payment_method,
                        'invoice_id': invoice.pk,
                        'payment_id': payment.pk,
                        'balance_due': str(invoice.balance_due),
                        'payment_status': invoice.payment_status,
                    },
                )
                record_audit_entry(
                    request.user,
                    'invoice_payment_recorded',
                    payment,
                    repair_order=invoice.repair_order,
                    details={
                        'invoice_id': invoice.pk,
                        'amount': str(payment.amount),
                        'payment_method': payment.payment_method,
                        'reference': payment.reference,
                        'balance_due': str(invoice.balance_due),
                        'payment_status': invoice.payment_status,
                    },
                )
        if not form.errors:
            messages.success(request, f"Payment of R {payment.amount:.2f} recorded for invoice #{invoice.pk}.")
            return redirect('invoice_detail', pk=pk)

    return render(request, 'workshop/invoice_payment.html', {
        'invoice': invoice,
        'form': form,
        'is_customer': False,
    })


def get_or_update_vehicle_repair_order(vehicle, *, existing_order=None, create_new=False, assigned_tech=None, status=None, propose_status=False, description=None, internal_notes=None, approved=None):
    if existing_order is not None:
        existing = existing_order
    elif create_new:
        existing = None
    else:
        # Exclude orders where work has already started: reusing one would silently
        # overwrite its approval/status/assignment when an unrelated appointment comes in.
        existing = (
            RepairOrder.objects.filter(vehicle=vehicle)
            .exclude(status__in=['completed', 'cancelled'])
            .exclude(invoice__isnull=False)
            .exclude(labor_lines__isnull=False)
            .exclude(parts_lines__isnull=False)
            .order_by('-date_created')
            .first()
        )
    if existing:
        changed = False

        if assigned_tech is not None and existing.assigned_tech_id != assigned_tech.pk:
            existing.assigned_tech = assigned_tech
            changed = True
        if status and existing.status != status:
            if propose_status:
                if existing.pending_status != status:
                    existing.pending_status = status
                    changed = True
            else:
                existing.status = status
                changed = True
        if description and existing.description != description:
            existing.description = description
            changed = True
        if internal_notes:
            if existing.internal_notes:
                combined = existing.internal_notes + "\n" + internal_notes
            else:
                combined = internal_notes
            if existing.internal_notes != combined:
                existing.internal_notes = combined
                changed = True
        # Customer estimate approval is only ever granted/revoked via the customer's own
        # decision endpoint. Appointment/assignment flows must never downgrade it back to
        # False on an order the customer already approved, or admin approval of the next
        # status proposal becomes permanently blocked.
        if approved and not existing.approved:
            existing.approved = True
            changed = True

        if changed:
            existing.save()
        return existing

    return RepairOrder.objects.create(
        vehicle=vehicle,
        assigned_tech=assigned_tech,
        status='pending' if propose_status else status or 'pending',
        pending_status=status if propose_status and status else '',
        description=description or 'New service request',
        internal_notes=internal_notes or '',
        mileage_in=vehicle.mileage or 0,
        approved=bool(approved),
    )


def get_or_update_appointment_repair_order(appointment, **kwargs):
    repair_order = get_or_update_vehicle_repair_order(
        appointment.vehicle,
        existing_order=appointment.repair_order,
        create_new=appointment.repair_order_id is None,
        **kwargs,
    )
    if appointment.repair_order_id != repair_order.pk:
        appointment.repair_order = repair_order
        appointment.save(update_fields=['repair_order'])
    return repair_order


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  APPOINTMENTS
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@login_required
def appointment_list(request):
    appointments = Appointment.objects.select_related('customer', 'vehicle').order_by('date_time', 'pk')
    profile = getattr(request.user, 'userprofile', None)
    if profile and profile.role == 'customer':
        customer = Customer.objects.filter(email=request.user.email).first()
        if customer:
            appointments = appointments.filter(customer=customer)
        else:
            appointments = appointments.none()
    elif profile and profile.role == 'mechanic':
        appointments = appointments.filter(
            assigned_mechanic=request.user,
            repair_order__approved=True,
        ).exclude(assignment_status='declined')
    elif not _is_admin(request.user):
        return _deny_access(request)
    query = request.GET.get('q', '').strip()
    if query:
        appointments = appointments.filter(
            Q(customer__first_name__icontains=query)
            | Q(customer__last_name__icontains=query)
            | Q(vehicle__license_plate__icontains=query)
            | Q(vehicle__make__icontains=query)
            | Q(vehicle__model__icontains=query)
            | Q(service_desc__icontains=query)
        )
    status = request.GET.get('status', '')
    if status in dict(Appointment.ASSIGNMENT_CHOICES):
        appointments = appointments.filter(assignment_status=status)
    start_date = parse_date(request.GET.get('start_date', ''))
    end_date = parse_date(request.GET.get('end_date', ''))
    if start_date:
        appointments = _filter_datetime_date_range(appointments, 'date_time', start_date, None)
    if end_date:
        appointments = _filter_datetime_date_range(appointments, 'date_time', None, end_date)
    appointments = Paginator(appointments, 25).get_page(request.GET.get('page'))
    if _role(request.user) == 'customer':
        for appointment in appointments:
            appointment.can_delete = customer_can_delete_appointment(appointment)
    return render(request, 'workshop/appointment_list.html', {
        'appointments': appointments,
        'q': query,
        'status': status,
        'start_date': start_date,
        'end_date': end_date,
        'status_choices': Appointment.ASSIGNMENT_CHOICES,
    })


DUPLICATE_REQUEST_WINDOW = timedelta(hours=24)


def _find_matching_vehicle(customer, data):
    vehicles = Vehicle.objects.filter(customer=customer)
    plate = normalize_license_plate(data.get('license_plate'))
    vin = (data.get('vin') or '').strip()
    if plate:
        plate_matches = [
            vehicle for vehicle in vehicles.exclude(license_plate='').order_by('pk')
            if normalize_license_plate(vehicle.license_plate) == plate
        ]
        if len(plate_matches) == 1:
            return plate_matches[0]
    if vin:
        match = vehicles.filter(vin__iexact=vin).first()
        if match:
            return match
    make = (data.get('make') or '').strip()
    model = (data.get('model') or '').strip()
    year = data.get('year') or 0
    if make and model and year:
        return vehicles.filter(make__iexact=make, model__iexact=model, year=year).first()
    return None


@login_required
@require_GET
def vehicle_lookup(request):
    if _role(request.user) != 'customer':
        return JsonResponse({'found': False}, status=403)
    plate = normalize_license_plate(request.GET.get('plate'))
    if not plate:
        return JsonResponse({'found': False})
    customer = Customer.objects.filter(email=request.user.email).first()
    if not customer:
        return JsonResponse({'found': False})
    matches = [
        vehicle for vehicle in Vehicle.objects.filter(customer=customer).exclude(license_plate='').order_by('pk')
        if normalize_license_plate(vehicle.license_plate) == plate
    ]
    if len(matches) != 1:
        return JsonResponse({'found': False, 'ambiguous': len(matches) > 1})
    vehicle = matches[0]
    return JsonResponse({
        'found': True,
        'vehicle': {
            'id': vehicle.pk,
            'license_plate': vehicle.license_plate,
            'make': vehicle.make,
            'model': vehicle.model,
            'year': vehicle.year,
            'vin': vehicle.vin,
            'color': vehicle.color,
            'mileage': vehicle.mileage,
            'service_plan': vehicle.service_plan,
            'recent_service_history': vehicle.recent_service_history,
        },
    })


def _recent_open_request_exists(vehicle, description=''):
    recent = RepairOrder.objects.filter(
        vehicle=vehicle,
        date_created__gte=timezone.now() - DUPLICATE_REQUEST_WINDOW,
    ).exclude(status__in=['cancelled', 'completed'])
    if recent.filter(status='pending').exists():
        return True
    description = (description or '').strip()
    return bool(description) and recent.filter(description__iexact=description).exists()

@login_required
def appointment_create(request):
    if not (_is_admin(request.user) or _role(request.user) == 'customer'):
        return _deny_access(request)
    profile = getattr(request.user, 'userprofile', None)
    initial = {}
    selected_vehicle = None
    if profile and profile.role == 'customer':
        customer = Customer.objects.filter(email=request.user.email).first()
        selected_vehicle_id = request.POST.get('vehicle') or request.GET.get('vehicle')
        selected_vehicle = Vehicle.objects.filter(
            pk=selected_vehicle_id,
            customer=customer,
        ).first() if customer and selected_vehicle_id else None
        if selected_vehicle and request.method == 'GET':
            initial = {
                'vehicle': selected_vehicle.pk,
                'vehicle_make': selected_vehicle.make,
                'vehicle_model': selected_vehicle.model,
                'vehicle_year': selected_vehicle.year,
                'vehicle_vin': selected_vehicle.vin,
                'vehicle_license_plate': selected_vehicle.license_plate,
                'vehicle_color': selected_vehicle.color,
                'vehicle_mileage': selected_vehicle.mileage or None,
                'vehicle_service_plan': selected_vehicle.service_plan,
                'vehicle_recent_service_history': selected_vehicle.recent_service_history,
                'vehicle_notes': selected_vehicle.notes,
            }
        elif selected_vehicle:
            initial = {
                'vehicle': selected_vehicle.pk,
                'vehicle_make': selected_vehicle.make,
                'vehicle_model': selected_vehicle.model,
                'vehicle_year': selected_vehicle.year,
                'vehicle_vin': selected_vehicle.vin,
                'vehicle_license_plate': selected_vehicle.license_plate,
                'vehicle_color': selected_vehicle.color,
                'vehicle_mileage': selected_vehicle.mileage or None,
                'vehicle_service_plan': selected_vehicle.service_plan,
                'vehicle_recent_service_history': selected_vehicle.recent_service_history,
                'vehicle_notes': selected_vehicle.notes,
            }
    form = AppointmentForm(request.POST or None, user=request.user, initial=initial)

    if form.is_valid():
        appt = form.save(commit=False)
        current_mileage = None
        vehicle_mileage_changed = False
        vehicle_service_plan_changed = False

        if profile and profile.role == 'customer':
            customer = Customer.objects.filter(
                email=request.user.email
            ).first()

            if not customer:
                customer = Customer.objects.create(
                    first_name=request.user.first_name or request.user.username,
                    last_name=request.user.last_name or '',
                    email=request.user.email,
                    phone='',
                    address='',
                    notes='',
                )

            appt.customer = customer

            vehicle_id = form.cleaned_data.get('vehicle')

            if vehicle_id:
                appt.vehicle = vehicle_id
                service_plan = (form.cleaned_data.get('vehicle_service_plan') or '').strip()
                if service_plan != vehicle_id.service_plan:
                    vehicle_id.service_plan = service_plan
                    vehicle_service_plan_changed = True
                service_plan = (form.cleaned_data.get('vehicle_service_plan') or '').strip()
                if service_plan != vehicle_id.service_plan:
                    vehicle_id.service_plan = service_plan
                    vehicle_service_plan_changed = True
            else:
                manual_vehicle = form.manual_vehicle_data()

                if any(value not in (None, '', 0) for value in manual_vehicle.values()):
                    vehicle = _find_matching_vehicle(customer, manual_vehicle)
                    if vehicle is None:
                        if not manual_vehicle['make'] or not manual_vehicle['model'] or not manual_vehicle['year']:
                            form.add_error(
                                'vehicle_license_plate',
                                'No vehicle was found for this plate. Enter the make, model, and year to register a new vehicle.',
                            )
                            return render(request, 'workshop/appointment_form.html', {
                                'form': form,
                                'title': f'Book Service for: {selected_vehicle.year} {selected_vehicle.make} {selected_vehicle.model}' if selected_vehicle else 'Book Appointment',
                                'selected_vehicle': selected_vehicle,
                            })
                        other_owner_vehicle = next((
                            candidate for candidate in Vehicle.objects.exclude(customer=customer).exclude(license_plate='')
                            if normalize_license_plate(candidate.license_plate) == normalize_license_plate(manual_vehicle['license_plate'])
                        ), None) if manual_vehicle['license_plate'] else None
                        if other_owner_vehicle:
                            form.add_error(
                                'vehicle_license_plate',
                                'This plate is already registered to another customer. Contact the workshop to resolve ownership.',
                            )
                            return render(request, 'workshop/appointment_form.html', {'form': form, 'title': 'Book Appointment'})
                        vehicle = Vehicle.objects.create(
                            customer=customer,
                            make=manual_vehicle['make'] or 'Unknown',
                            model=manual_vehicle['model'] or '',
                            year=manual_vehicle['year'] or 0,
                            vin=manual_vehicle['vin'] or '',
                            license_plate=manual_vehicle['license_plate'] or '',
                            color=manual_vehicle['color'] or '',
                            mileage=manual_vehicle['mileage'] or 0,
                            service_plan=manual_vehicle['service_plan'] or '',
                            recent_service_history=manual_vehicle['recent_service_history'] or '',
                            notes=manual_vehicle['notes'] or '',
                        )
                    appt.vehicle = vehicle

            if appt.vehicle_id:
                service_plan = (form.cleaned_data.get('vehicle_service_plan') or '').strip()
                if service_plan != appt.vehicle.service_plan:
                    appt.vehicle.service_plan = service_plan
                    vehicle_service_plan_changed = True

            current_mileage = form.cleaned_data.get('vehicle_mileage')
            if appt.vehicle_id and current_mileage:
                if current_mileage < appt.vehicle.mileage:
                    form.add_error('vehicle_mileage', 'Current mileage cannot be less than the mileage already recorded for this vehicle.')
                    return render(request, 'workshop/appointment_form.html', {
                        'form': form,
                        'title': f'Book Service for: {selected_vehicle.year} {selected_vehicle.make} {selected_vehicle.model}' if selected_vehicle else 'Book Appointment',
                        'selected_vehicle': selected_vehicle,
                    })
                if current_mileage != appt.vehicle.mileage:
                    appt.vehicle.mileage = current_mileage
                    vehicle_mileage_changed = True

            requested_services = (
                [] if profile and profile.role == 'customer'
                else list(form.cleaned_data.get('requested_services') or [])
            )
            other_service_details = (form.cleaned_data.get('service_desc') or '').strip()
            service_descriptions = []
            if requested_services:
                service_descriptions.append(
                    'Requested services: ' + ', '.join(service.name for service in requested_services)
                )
            if other_service_details:
                service_descriptions.append(other_service_details)
            appt.service_desc = '\n'.join(service_descriptions)

            if appt.vehicle_id and _recent_open_request_exists(appt.vehicle, appt.service_desc):
                form.add_error(
                    None,
                    'A service request for this vehicle was already submitted recently and is still open. '
                    'Please check "My Appointments" - if it was a mistake, you can delete it there before booking again.',
                )
                return render(request, 'workshop/appointment_form.html', {'form': form, 'title': 'Book Appointment'})
        assigned_mechanic = form.cleaned_data.get('assigned_mechanic')
        assignment_status = form.cleaned_data.get('assignment_status') or 'pending'
        if _is_admin(request.user) and assigned_mechanic:
            form.add_error('assigned_mechanic', 'Create the service request first. A mechanic can be assigned after the customer approves its repair estimate.')
            return render(request, 'workshop/appointment_form.html', {'form': form, 'title': 'Book Appointment'})
        if assigned_mechanic and assignment_status == 'accepted':
            with transaction.atomic():
                User.objects.select_for_update().get(pk=assigned_mechanic.pk)
                if Appointment.has_schedule_conflict(
                    mechanic=assigned_mechanic,
                    date_time=appt.date_time,
                    duration=appt.duration,
                ):
                    form.add_error('assigned_mechanic', 'This mechanic already has an accepted appointment during that time.')
                    return render(request, 'workshop/appointment_form.html', {
                        'form': form,
                        'title': f'Book Service for: {selected_vehicle.year} {selected_vehicle.make} {selected_vehicle.model}' if selected_vehicle else 'Book Appointment',
                        'selected_vehicle': selected_vehicle,
                    })
                vehicle_updates = []
                if vehicle_mileage_changed:
                    vehicle_updates.append('mileage')
                if vehicle_service_plan_changed:
                    vehicle_updates.append('service_plan')
                if vehicle_service_plan_changed:
                    vehicle_updates.append('service_plan')
                if vehicle_updates:
                    appt.vehicle.save(update_fields=vehicle_updates)
                appt.save()
        else:
            vehicle_updates = []
            if vehicle_mileage_changed:
                vehicle_updates.append('mileage')
            if vehicle_service_plan_changed:
                vehicle_updates.append('service_plan')
            if vehicle_service_plan_changed:
                vehicle_updates.append('service_plan')
            if vehicle_updates:
                appt.vehicle.save(update_fields=vehicle_updates)
            appt.save()

        if appt.vehicle_id:
            repair_order = RepairOrder.objects.create(
                vehicle=appt.vehicle,
                status='pending',
                description=appt.service_desc or 'New service request',
                internal_notes=(
                    f"Service request booked for appointment "
                    f"{appt.date_time:%Y-%m-%d %H:%M}"
                    + (f"\nCustomer notes: {appt.notes.strip()}" if appt.notes.strip() else '')
                ),
                mileage_in=appt.vehicle.mileage or 0,
                approved=False,
            )
            appt.repair_order = repair_order
            appt.save(update_fields=['repair_order'])
            record_repair_event(
                repair_order,
                request.user,
                'created',
                current_status=repair_order.status,
                customer_visible=True,
                note='Repair order created from a service request.',
                metadata={'appointment_id': appt.pk},
            )
        else:
            repair_order = None

        record_audit_entry(
            request.user,
            'appointment_created',
            appt,
            repair_order=repair_order,
            details={
                'date_time': appt.date_time.isoformat(),
                'assignment_status': appt.assignment_status,
                'repair_order_id': repair_order.pk if repair_order else None,
            },
        )

        # Send service-request confirmation email to the customer
        try:
            send_service_request_confirmation(
                request.user.email,
                request.user.get_full_name() or request.user.username,
                appt,
                repair_order,
            )
        except Exception:
            messages.warning(
                request,
                'Service request saved, but the confirmation email could not be sent.'
            )

        request.session['new_service_request'] = True

        messages.success(
            request,
            'Service request submitted. A mechanic will review it and update your vehicle status soon.'
        )

        return redirect('dashboard')

    return render(
        request,
        'workshop/appointment_form.html',
        {
            'form': form,
            'title': f'Book Service for: {selected_vehicle.year} {selected_vehicle.make} {selected_vehicle.model}' if selected_vehicle else 'Book Appointment',
            'selected_vehicle': selected_vehicle,
        }
    )

@login_required
def appointment_edit(request, pk):
    appt = get_object_or_404(Appointment, pk=pk)
    profile = getattr(request.user, 'userprofile', None)
    role = profile.role if profile else ('admin' if request.user.is_staff else '')
    if role != 'admin' and (
        request.user != appt.assigned_mechanic
        or (role == 'mechanic' and appt.assignment_status == 'declined')
    ):
        messages.error(request, 'Only the admin or the assigned mechanic can edit this appointment.')
        return redirect('appointment_list')

    previous_values = {
        'date_time': appt.date_time.isoformat(),
        'duration': appt.duration,
        'assigned_mechanic_id': appt.assigned_mechanic_id,
        'assignment_status': appt.assignment_status,
    }
    form = AppointmentForm(request.POST or None, instance=appt, user=request.user)
    if form.is_valid():
        assigned_mechanic = form.cleaned_data.get('assigned_mechanic')
        assignment_changed = previous_values['assigned_mechanic_id'] != getattr(assigned_mechanic, 'pk', None)
        assignment_status = form.cleaned_data.get('assignment_status') or 'pending'
        assignment_state_changed = previous_values['assignment_status'] != assignment_status
        if assigned_mechanic and assignment_status == 'accepted':
            repair_order = appt.repair_order
            if not repair_order or not repair_order.approved:
                form.add_error('assignment_status', 'The customer must approve the repair estimate before a mechanic can accept this appointment.')
                return render(request, 'workshop/appointment_form.html', {'form': form, 'title': 'Edit Appointment', 'appt': appt})
        if role == 'admin' and (assignment_changed or assignment_state_changed) and assigned_mechanic:
            if not appt.repair_order_id or not appt.repair_order.approved:
                form.add_error('assigned_mechanic', 'The customer must approve the repair estimate before a mechanic can be assigned.')
                return render(request, 'workshop/appointment_form.html', {'form': form, 'title': 'Edit Appointment', 'appt': appt})
        assignment_reason = (form.cleaned_data.get('assignment_reason') or '').strip()
        if role == 'admin' and assignment_changed and not assignment_reason:
            form.add_error('assignment_reason', 'Please explain why the mechanic is being changed.')
            return render(request, 'workshop/appointment_form.html', {'form': form, 'title': 'Edit Appointment', 'appt': appt})
        with transaction.atomic():
            if role == 'admin' and assignment_changed and assigned_mechanic:
                assignment_status = 'pending'
            if assigned_mechanic and assignment_status == 'accepted':
                User.objects.select_for_update().get(pk=assigned_mechanic.pk)
                if Appointment.has_schedule_conflict(
                    mechanic=assigned_mechanic,
                    date_time=form.cleaned_data['date_time'],
                    duration=form.cleaned_data.get('duration') or appt.duration,
                    exclude_pk=appt.pk,
                ):
                    form.add_error('assigned_mechanic', 'This mechanic already has an accepted appointment during that time.')
                    return render(request, 'workshop/appointment_form.html', {'form': form, 'title': 'Edit Appointment', 'appt': appt})
            updated_appt = form.save(commit=False)
            updated_appt.assigned_mechanic = assigned_mechanic
            updated_appt.assignment_status = assignment_status
            if assignment_changed:
                updated_appt.assignment_reason = assignment_reason
            else:
                updated_appt.assignment_reason = appt.assignment_reason
            updated_appt.save()
            current_values = {
                'date_time': updated_appt.date_time.isoformat(),
                'duration': updated_appt.duration,
                'assigned_mechanic_id': updated_appt.assigned_mechanic_id,
                'assignment_status': updated_appt.assignment_status,
            }
            changes = {
                field: {'from': previous_values[field], 'to': current_values[field]}
                for field in previous_values
                if previous_values[field] != current_values[field]
            }
            record_audit_entry(
                request.user,
                'appointment_updated',
                updated_appt,
                repair_order=getattr(updated_appt, 'repair_order', None),
                details={'changes': changes},
            )

        if updated_appt.assigned_mechanic and updated_appt.assignment_status == 'accepted':
            get_or_update_appointment_repair_order(
                updated_appt,
                assigned_tech=updated_appt.assigned_mechanic,
                status='in_progress',
                propose_status=role == 'mechanic',
                description=updated_appt.service_desc or 'Workshop appointment accepted',
                internal_notes=f"Mechanic assignment accepted for appointment {updated_appt.date_time:%Y-%m-%d %H:%M}",
                approved=False,
            )
        elif updated_appt.assigned_mechanic and updated_appt.assignment_status == 'declined':
            get_or_update_appointment_repair_order(
                updated_appt,
                assigned_tech=None,
                status='pending' if role == 'admin' else None,
                internal_notes=f"Mechanic assignment declined for appointment {updated_appt.date_time:%Y-%m-%d %H:%M}",
                approved=False,
            )

        if assignment_changed and updated_appt.repair_order_id:
            repair_order = updated_appt.repair_order
            previous_mechanic = User.objects.filter(pk=previous_values['assigned_mechanic_id']).first()
            current_mechanic = updated_appt.assigned_mechanic
            repair_order.assigned_tech = current_mechanic
            repair_order.save(update_fields=['assigned_tech', 'date_updated'])
            record_repair_event(
                repair_order,
                request.user,
                'assignment',
                note=(
                    f"Mechanic assignment changed from "
                    f"{previous_mechanic.get_full_name() or previous_mechanic.username if previous_mechanic else 'Unassigned'} "
                    f"to {current_mechanic.get_full_name() or current_mechanic.username if current_mechanic else 'Unassigned'}. "
                    f"Reason: {assignment_reason}"
                ),
                customer_visible=True,
                metadata={
                    'from_user_id': previous_values['assigned_mechanic_id'],
                    'to_user_id': updated_appt.assigned_mechanic_id,
                },
            )

        messages.success(request, "Appointment updated.")
        return redirect('appointment_list')
    return render(request, 'workshop/appointment_form.html', {'form': form, 'title': 'Edit Appointment', 'appt': appt})


def customer_can_delete_appointment(appt):
    order = appt.repair_order
    if order is None:
        return True
    return (
        order.status == 'pending'
        and not order.approved
        and not order.estimate_lines.exists()
        and not order.labor_lines.exists()
        and not order.parts_lines.exists()
        and not Invoice.objects.filter(repair_order=order).exists()
    )


@login_required
@require_POST
@transaction.atomic
def appointment_delete(request, pk):
    if _role(request.user) != 'customer':
        messages.error(request, 'Only customers can delete their own service requests.')
        return redirect('appointment_list')

    customer = Customer.objects.filter(email=request.user.email).first()
    appt = get_object_or_404(
        Appointment.objects.select_for_update().select_related('repair_order'),
        pk=pk,
        customer=customer,
    ) if customer else None
    if appt is None:
        messages.error(request, 'Service request not found.')
        return redirect('appointment_list')

    if not customer_can_delete_appointment(appt):
        messages.error(
            request,
            'This service request can no longer be deleted because the workshop has already started on it. '
            'Please contact the workshop.'
        )
        return redirect('appointment_list')

    order = appt.repair_order
    record_audit_entry(
        request.user,
        'appointment_deleted',
        appt,
        repair_order=order,
        details={
            'date_time': appt.date_time.isoformat(),
            'repair_order_id': order.pk if order else None,
        },
    )
    appt.delete()

    if order and not order.appointments.exists() and order.status != 'cancelled':
        previous_status = order.status
        order.status = 'cancelled'
        order.pending_status = ''
        order.save(update_fields=['status', 'pending_status', 'date_updated'])
        record_repair_event(
            order,
            request.user,
            'cancelled',
            previous_status=previous_status,
            current_status=order.status,
            customer_visible=True,
            note='Customer deleted the service request.',
        )

    messages.success(request, 'Your service request has been deleted.')
    return redirect('appointment_list')


@login_required
@require_POST
@transaction.atomic
def appointment_decision(request, pk, action):
    if action not in ['accept', 'decline']:
        messages.error(request, 'Invalid assignment decision.')
        return redirect('appointment_list')

    appt = get_object_or_404(Appointment, pk=pk)
    profile = getattr(request.user, 'userprofile', None)
    if not profile or profile.role != 'mechanic' or appt.assigned_mechanic_id != request.user.pk:
        messages.error(request, 'You are not assigned to this appointment.')
        return redirect('appointment_list')

    User.objects.select_for_update().get(pk=request.user.pk)
    appt = get_object_or_404(
        Appointment.objects.select_for_update(),
        pk=pk,
        assigned_mechanic=request.user,
    )
    if appt.assignment_status != 'pending':
        messages.error(request, 'This appointment is no longer awaiting your decision.')
        return redirect('appointment_list')
    if not appt.repair_order_id or not appt.repair_order.approved:
        messages.error(request, 'The customer must approve the repair estimate before a mechanic can accept this appointment.')
        return redirect('appointment_list')
    if action == 'accept' and Appointment.has_schedule_conflict(
            mechanic=request.user,
            date_time=appt.date_time,
            duration=appt.duration,
            exclude_pk=appt.pk,
        ):
            messages.error(request, 'You already have an accepted appointment during that time.')
            return redirect('appointment_list')

    appt.assignment_status = 'accepted' if action == 'accept' else 'declined'
    reason = (request.POST.get('reason') or '').strip()
    if action == 'decline' and not reason:
        messages.error(request, 'Please provide a reason for declining this appointment.')
        return redirect('appointment_list')
    if action == 'decline':
        appt.assignment_reason = reason
    appt.save(update_fields=['assignment_status', 'assignment_reason'])
    record_audit_entry(
        request.user,
        f'appointment_{action}',
        appt,
        details={'assignment_status': appt.assignment_status, 'reason': reason},
        repair_order=getattr(appt, 'repair_order', None),
    )

    if action == 'accept':
        repair_order = get_or_update_appointment_repair_order(
            appt,
            assigned_tech=request.user,
            status='in_progress',
            propose_status=True,
            description=appt.service_desc or 'Workshop appointment accepted',
            internal_notes=f"Mechanic {request.user.get_full_name() or request.user.username} accepted the assignment.",
            approved=False,
        )
        messages.success(request, 'You accepted the service assignment. The status update is awaiting admin approval.')
    else:
        repair_order = get_or_update_appointment_repair_order(
            appt,
            assigned_tech=None,
            internal_notes=f"Mechanic {request.user.get_full_name() or request.user.username} declined the assignment.",
            approved=False,
        )
        if repair_order.assigned_tech_id:
            repair_order.assigned_tech = None
            repair_order.save(update_fields=['assigned_tech', 'date_updated'])
        record_repair_event(
            repair_order,
            request.user,
            'assignment',
            note=f'Mechanic declined the appointment. Reason: {reason}',
            customer_visible=True,
        )
        messages.warning(request, 'You declined the service assignment.')

    return redirect('dashboard')


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  PARTS INVENTORY
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@login_required
def parts_list(request):
    if not (_is_admin(request.user) or _role(request.user) == 'mechanic'):
        return _deny_access(request)
    parts = Part.objects.all()
    q = request.GET.get('q', '')
    if q:
        parts = parts.filter(Q(name__icontains=q) | Q(part_number__icontains=q))
    low_stock = request.GET.get('low_stock')
    if low_stock:
        from django.db.models import F
        parts = parts.filter(stock_qty__lte=F('reorder_level'))
    parts = Paginator(parts.order_by('name', 'pk'), 25).get_page(request.GET.get('page'))
    return render(request, 'workshop/parts_list.html', {'parts': parts, 'q': q, 'low_stock': low_stock})


@login_required
def part_create(request):
    if not _is_admin(request.user):
        return _deny_access(request)
    form = PartForm(request.POST or None)
    if form.is_valid():
        with transaction.atomic():
            part = form.save()
            record_audit_entry(
                request.user,
                'part_created',
                part,
                details={
                    'stock_qty': part.stock_qty,
                    'cost_price': str(part.cost_price),
                    'sell_price': str(part.sell_price),
                },
            )
        messages.success(request, f"Part '{part.name}' added.")
        return redirect('parts_list')
    return render(request, 'workshop/part_form.html', {'form': form, 'title': 'Add Part'})


@login_required
def part_edit(request, pk):
    if not _is_admin(request.user):
        return _deny_access(request)
    part = get_object_or_404(Part, pk=pk)
    fields_to_track = ('stock_qty', 'cost_price', 'sell_price', 'reorder_level')
    previous_values = {field: str(getattr(part, field)) for field in fields_to_track}
    form = PartForm(request.POST or None, instance=part)
    if form.is_valid():
        with transaction.atomic():
            part = form.save()
            changes = {
                field: {'from': previous_values[field], 'to': str(getattr(part, field))}
                for field in fields_to_track
                if previous_values[field] != str(getattr(part, field))
            }
            if changes:
                record_audit_entry(request.user, 'part_updated', part, details={'changes': changes})
        messages.success(request, "Part updated.")
        return redirect('parts_list')
    return render(request, 'workshop/part_form.html', {'form': form, 'title': 'Edit Part', 'part': part})


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  SERVICE CATALOGUE
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@login_required
def service_list(request):
    services = ServiceItem.objects.all()
    return render(request, 'workshop/service_list.html', {'services': services})


@login_required
def service_create(request):
    if not _is_admin(request.user):
        return _deny_access(request)
    form = ServiceItemForm(request.POST or None)
    if form.is_valid():
        with transaction.atomic():
            svc = form.save()
            record_audit_entry(
                request.user,
                'service_created',
                svc,
                details={
                    'labor_hours': str(svc.labor_hours),
                    'labor_rate': str(svc.labor_rate),
                },
            )
        messages.success(request, f"Service '{svc.name}' added.")
        return redirect('service_list')
    return render(request, 'workshop/service_form.html', {'form': form, 'title': 'Add Service'})


@login_required
def service_edit(request, pk):
    if not _is_admin(request.user):
        return _deny_access(request)
    svc = get_object_or_404(ServiceItem, pk=pk)
    tracked_fields = ('name', 'labor_hours', 'labor_rate')
    previous_values = {field: str(getattr(svc, field)) for field in tracked_fields}
    form = ServiceItemForm(request.POST or None, instance=svc)
    if form.is_valid():
        with transaction.atomic():
            svc = form.save()
            changes = {
                field: {'from': previous_values[field], 'to': str(getattr(svc, field))}
                for field in tracked_fields
                if previous_values[field] != str(getattr(svc, field))
            }
            if changes:
                record_audit_entry(request.user, 'service_updated', svc, details={'changes': changes})
        messages.success(request, "Service updated.")
        return redirect('service_list')
    return render(request, 'workshop/service_form.html', {'form': form, 'title': 'Edit Service', 'svc': svc})
