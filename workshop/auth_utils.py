import secrets
import hashlib
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from django.core.cache import cache
from .models import EmailVerificationToken
from .models import PasswordResetToken
from .currency import format_rand


def send_verification_email(request, user, ttl_minutes=30):
    raw_token, token_obj = EmailVerificationToken.generate_for_user(user, ttl_minutes=ttl_minutes)
    verify_url = f"{_public_base_url(request)}/verify-email/?token={raw_token}"
    subject = 'Verify Your Uncle Kop\'s Workshop Account'
    customer_name = user.get_full_name() or user.username
    message = (
        f"Hello {customer_name},\n\n"
        "Thank you for registering with Uncle Kop's Workshop.\n\n"
        "Please click the button below to verify your email address and activate your account.\n\n"
        f"[Verify Email]\n{verify_url}\n\n"
        "If you did not create this account, please ignore this email.\n\n"
        "Thank you,\n"
        "Uncle Kop's Workshop"
    )
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email])
    return token_obj


def send_service_request_confirmation(user_email, user_name, appointment, repair_order=None):
    vehicle = appointment.vehicle
    vehicle_summary = 'Unknown vehicle'
    if vehicle:
        parts = [str(vehicle.year), vehicle.make, vehicle.model]
        vehicle_summary = ' '.join(part for part in parts if part)
        if vehicle.license_plate:
            vehicle_summary = f"{vehicle_summary} (Plate: {vehicle.license_plate})"

    reference = f"RO#{repair_order.pk}" if repair_order else 'pending review'
    subject = 'Service Request Received'
    message = (
        f"Hello {user_name or 'Customer'},\n\n"
        "Your service request has been received successfully.\n\n"
        f"Vehicle: {vehicle_summary}\n"
        f"Service: {appointment.service_desc or 'Not specified'}\n"
        f"Reference: {reference}\n\n"
        "You can log in to your account to view your request and track its progress.\n\n"
        "Thank you,\n"
        "Uncle Kop's Workshop"
    )
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user_email])
    return True


def can_resend_verification(user, limit=3, period_seconds=3600):
    key = f"resend_verif:{user.pk}"
    data = cache.get(key, 0)
    if data >= limit:
        return False
    # increment
    cache.incr(key, delta=1) if cache.get(key) is not None else cache.set(key, 1, timeout=period_seconds)
    return True


def can_request_password_reset(user, limit=3, period_seconds=3600):
    window_start = timezone.now() - timezone.timedelta(seconds=period_seconds)
    recent_requests = PasswordResetToken.objects.filter(
        user=user,
        created_at__gte=window_start,
    ).count()
    return recent_requests < limit


def send_password_reset_email(request, user, ttl_minutes=30):
    raw_token, token_obj = PasswordResetToken.generate_for_user(user, ttl_minutes=ttl_minutes)
    reset_url = f"{_public_base_url(request)}/reset-password/?token={raw_token}"
    subject = 'Reset Your Password'
    customer_name = user.get_full_name() or user.username
    message = (
        f"Hello {customer_name},\n\n"
        "We received a request to reset your Uncle Kop's Workshop password.\n\n"
        "Click the button below to create a new password.\n\n"
        f"[Reset Password]\n{reset_url}\n\n"
        "If you did not request this, please ignore this email.\n\n"
        "Thank you,\n"
        "Uncle Kop's Workshop"
    )
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email])
    return token_obj


def _public_base_url(request):
    configured_url = getattr(settings, 'PUBLIC_BASE_URL', '').rstrip('/')
    if configured_url:
        return configured_url
    return request.build_absolute_uri('/').rstrip('/')


def send_invoice_ready_email(request, invoice):
    customer = invoice.repair_order.vehicle.customer
    vehicle = invoice.repair_order.vehicle
    vehicle_summary = ' '.join(
        part for part in [str(vehicle.year), vehicle.make, vehicle.model] if part
    )
    invoice_url = request.build_absolute_uri(f'/invoices/{invoice.pk}/')
    subject = 'Your Invoice Is Ready'
    message = (
        f"Hello {customer.full_name},\n\n"
        "Your invoice is ready.\n\n"
        f"Invoice: #{invoice.pk}\n"
        f"Vehicle: {vehicle_summary}\n"
        f"Balance Due: {format_rand(invoice.balance_due)}\n\n"
        "Please log in to view the invoice and contact the workshop to arrange payment.\n\n"
        f"[View Invoice]\n{invoice_url}\n\n"
        "Thank you,\n"
        "Uncle Kop's Workshop"
    )
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [customer.email])
    return True
