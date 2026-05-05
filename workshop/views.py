from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Sum, Q
from django.utils import timezone
from datetime import date, timedelta

from .models import Customer, Vehicle, RepairOrder, LaborLine, PartsLine, Invoice, Appointment, Part, ServiceItem, UserProfile
from .forms  import (CustomerForm, VehicleForm, RepairOrderForm, LaborLineForm,
                     PartsLineForm, InvoiceForm, AppointmentForm, PartForm, ServiceItemForm, UserRegistrationForm,
                     EmployeeForm, EmployeeEditForm)


# ─────────────────────────────────────────────
#  AUTH
# ─────────────────────────────────────────────
def register(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            role = form.cleaned_data.get('role')
            if role == 'admin':
                user.is_staff = True
            user.save()

            UserProfile.objects.create(user=user, role=role)

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

            login(request, user)
            messages.success(request, 'Account created successfully.')
            return redirect('dashboard')
    else:
        form = UserRegistrationForm()
    return render(request, 'workshop/register.html', {'form': form})


# ─────────────────────────────────────────────
#  EMPLOYEES (MECHANICS)
# ─────────────────────────────────────────────
@login_required
def employee_list(request):
    if not request.user.is_staff:
        messages.error(request, 'Access denied.')
        return redirect('dashboard')
    mechanics = UserProfile.objects.filter(role='mechanic').select_related('user')
    return render(request, 'workshop/employee_list.html', {'mechanics': mechanics})


@login_required
def employee_create(request):
    if not request.user.is_staff:
        messages.error(request, 'Access denied.')
        return redirect('dashboard')
    if request.method == 'POST':
        form = EmployeeForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            user.save()
            UserProfile.objects.create(user=user, role='mechanic')
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
    profile = get_object_or_404(UserProfile, pk=pk, role='mechanic')
    user = profile.user
    if request.method == 'POST':
        form = EmployeeEditForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, "Mechanic updated.")
            return redirect('employee_list')
    else:
        form = EmployeeEditForm(instance=user)
    return render(request, 'workshop/employee_form.html', {'form': form, 'title': 'Edit mechanic', 'profile': profile})


# ─────────────────────────────────────────────
#  DASHBOARD
# ─────────────────────────────────────────────
@login_required
def dashboard(request):
    profile = getattr(request.user, 'userprofile', None)
    role = profile.role if profile else ('admin' if request.user.is_staff else '')

    if role == 'customer':
        customer = Customer.objects.filter(email=request.user.email).first()
        repair_orders = []
        pending_approval = []
        if customer:
            repair_orders = RepairOrder.objects.select_related('vehicle__customer').filter(vehicle__customer=customer).order_by('-date_created')
            pending_approval = repair_orders.filter(approved=False).order_by('-date_created')

        return render(request, 'workshop/customer_dashboard.html', {
            'customer': customer,
            'repair_orders': repair_orders,
            'pending_approval': pending_approval,
            'notifications': [],
        })

    if role == 'mechanic':
        assigned_orders = RepairOrder.objects.select_related('vehicle__customer').filter(assigned_tech=request.user).order_by('-date_created')
        active_orders = assigned_orders.exclude(status='completed')[:8]
        return render(request, 'workshop/mechanic_dashboard.html', {
            'assigned_orders': assigned_orders,
            'active_orders': active_orders,
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
            'recent_orders':         RepairOrder.objects.select_related('vehicle__customer').order_by('-date_created')[:8],
            'upcoming_appointments': Appointment.objects.filter(date_time__gte=timezone.now()).select_related('customer', 'vehicle').order_by('date_time')[:5],
            'weekly_revenue':        Invoice.objects.filter(issue_date__gte=week_start, payment_status='paid').aggregate(total=Sum('repair_order__labor_lines__rate'))['total'] or 0,
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
        'recent_orders':         RepairOrder.objects.select_related('vehicle__customer').order_by('-date_created')[:8],
        'upcoming_appointments': Appointment.objects.filter(date_time__gte=timezone.now()).select_related('customer', 'vehicle').order_by('date_time')[:5],
        'weekly_revenue':        Invoice.objects.filter(issue_date__gte=week_start, payment_status='paid').aggregate(total=Sum('repair_order__labor_lines__rate'))['total'] or 0,
    }
    return render(request, 'workshop/dashboard.html', context)


def models_low_stock():
    from django.db.models import F
    return F('reorder_level')


# ─────────────────────────────────────────────
#  CUSTOMERS
# ─────────────────────────────────────────────
@login_required
def customer_list(request):
    q = request.GET.get('q', '')
    customers = Customer.objects.annotate(vehicle_count=Count('vehicles'))
    if q:
        customers = customers.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q))
    return render(request, 'workshop/customer_list.html', {'customers': customers, 'q': q})


@login_required
def customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    vehicles = customer.vehicles.all()
    appointments = customer.appointments.order_by('-date_time')[:5]
    return render(request, 'workshop/customer_detail.html', {'customer': customer, 'vehicles': vehicles, 'appointments': appointments})


@login_required
def customer_profile(request):
    customer = Customer.objects.filter(email=request.user.email).first()
    return render(request, 'workshop/customer_profile.html', {'customer': customer})


@login_required
def customer_create(request):
    form = CustomerForm(request.POST or None)
    if form.is_valid():
        customer = form.save()
        messages.success(request, f"Customer '{customer.full_name}' created.")
        return redirect('customer_detail', pk=customer.pk)
    return render(request, 'workshop/customer_form.html', {'form': form, 'title': 'Add Customer'})


@login_required
def customer_edit(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    form = CustomerForm(request.POST or None, instance=customer)
    if form.is_valid():
        form.save()
        messages.success(request, "Customer updated.")
        return redirect('customer_detail', pk=pk)
    return render(request, 'workshop/customer_form.html', {'form': form, 'title': 'Edit Customer', 'customer': customer})


# ─────────────────────────────────────────────
#  VEHICLES
# ─────────────────────────────────────────────
@login_required
def vehicle_list(request):
    vehicles = Vehicle.objects.select_related('customer').all()
    q = request.GET.get('q', '')
    if q:
        vehicles = vehicles.filter(Q(make__icontains=q) | Q(model__icontains=q) | Q(license_plate__icontains=q) | Q(vin__icontains=q))
    return render(request, 'workshop/vehicle_list.html', {'vehicles': vehicles, 'q': q})


@login_required
def vehicle_detail(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk)
    repair_orders = vehicle.repair_orders.order_by('-date_created')
    return render(request, 'workshop/vehicle_detail.html', {'vehicle': vehicle, 'repair_orders': repair_orders})


@login_required
def vehicle_create(request):
    initial = {}
    customer_id = request.GET.get('customer')
    if customer_id:
        initial['customer'] = customer_id
    form = VehicleForm(request.POST or None, initial=initial)
    if form.is_valid():
        vehicle = form.save()
        messages.success(request, f"Vehicle '{vehicle}' added.")
        return redirect('vehicle_detail', pk=vehicle.pk)
    return render(request, 'workshop/vehicle_form.html', {'form': form, 'title': 'Add Vehicle'})


@login_required
def vehicle_edit(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk)
    form = VehicleForm(request.POST or None, instance=vehicle)
    if form.is_valid():
        form.save()
        messages.success(request, "Vehicle updated.")
        return redirect('vehicle_detail', pk=pk)
    return render(request, 'workshop/vehicle_form.html', {'form': form, 'title': 'Edit Vehicle', 'vehicle': vehicle})


# ─────────────────────────────────────────────
#  REPAIR ORDERS
# ─────────────────────────────────────────────
@login_required
def repair_order_list(request):
    status = request.GET.get('status', '')
    orders = RepairOrder.objects.select_related('vehicle__customer', 'assigned_tech')
    profile = getattr(request.user, 'userprofile', None)
    if profile and profile.role == 'customer':
        customer = Customer.objects.filter(email=request.user.email).first()
        if customer:
            orders = orders.filter(vehicle__customer=customer)
        else:
            orders = orders.none()
    if status:
        orders = orders.filter(status=status)
    return render(request, 'workshop/repair_order_list.html', {
        'orders': orders,
        'status': status,
        'status_choices': RepairOrder.STATUS_CHOICES,
    })


@login_required
def repair_order_detail(request, pk):
    order = get_object_or_404(RepairOrder, pk=pk)
    labor_lines = order.labor_lines.select_related('service_item')
    parts_lines = order.parts_lines.select_related('part')
    return render(request, 'workshop/repair_order_detail.html', {
        'order': order, 'labor_lines': labor_lines, 'parts_lines': parts_lines,
    })


@login_required
def repair_order_create(request):
    form = RepairOrderForm(request.POST or None)
    if form.is_valid():
        order = form.save()
        messages.success(request, f"Repair Order #{order.pk} created.")
        return redirect('repair_order_detail', pk=order.pk)
    return render(request, 'workshop/repair_order_form.html', {'form': form, 'title': 'New Repair Order'})


@login_required
def repair_order_edit(request, pk):
    order = get_object_or_404(RepairOrder, pk=pk)
    form = RepairOrderForm(request.POST or None, instance=order)
    if form.is_valid():
        form.save()
        messages.success(request, "Repair Order updated.")
        return redirect('repair_order_detail', pk=pk)
    return render(request, 'workshop/repair_order_form.html', {'form': form, 'title': 'Edit Repair Order', 'order': order})


@login_required
def add_labor_line(request, ro_pk):
    order = get_object_or_404(RepairOrder, pk=ro_pk)
    form = LaborLineForm(request.POST or None)
    if form.is_valid():
        line = form.save(commit=False)
        line.repair_order = order
        line.save()
        messages.success(request, "Labor line added.")
        return redirect('repair_order_detail', pk=ro_pk)
    return render(request, 'workshop/line_item_form.html', {'form': form, 'order': order, 'title': 'Add Labor Line'})


@login_required
def add_parts_line(request, ro_pk):
    order = get_object_or_404(RepairOrder, pk=ro_pk)
    form = PartsLineForm(request.POST or None)
    if form.is_valid():
        line = form.save(commit=False)
        line.repair_order = order
        line.save()
        messages.success(request, "Parts line added.")
        return redirect('repair_order_detail', pk=ro_pk)
    return render(request, 'workshop/line_item_form.html', {'form': form, 'order': order, 'title': 'Add Parts Line'})


# ─────────────────────────────────────────────
#  INVOICES
# ─────────────────────────────────────────────
@login_required
def invoice_list(request):
    invoices = Invoice.objects.select_related('repair_order__vehicle__customer').order_by('-issue_date')
    status = request.GET.get('status', '')
    if status:
        invoices = invoices.filter(payment_status=status)
    return render(request, 'workshop/invoice_list.html', {'invoices': invoices, 'status': status})


@login_required
def invoice_detail(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    return render(request, 'workshop/invoice_detail.html', {'invoice': invoice})


@login_required
def invoice_create(request):
    form = InvoiceForm(request.POST or None)
    if form.is_valid():
        invoice = form.save()
        messages.success(request, f"Invoice #{invoice.pk} created.")
        return redirect('invoice_detail', pk=invoice.pk)
    return render(request, 'workshop/invoice_form.html', {'form': form, 'title': 'Create Invoice'})


@login_required
def invoice_edit(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    form = InvoiceForm(request.POST or None, instance=invoice)
    if form.is_valid():
        form.save()
        messages.success(request, "Invoice updated.")
        return redirect('invoice_detail', pk=pk)
    return render(request, 'workshop/invoice_form.html', {'form': form, 'title': 'Edit Invoice', 'invoice': invoice})


# ─────────────────────────────────────────────
#  APPOINTMENTS
# ─────────────────────────────────────────────
@login_required
def appointment_list(request):
    appointments = Appointment.objects.select_related('customer', 'vehicle').order_by('date_time')
    profile = getattr(request.user, 'userprofile', None)
    if profile and profile.role == 'customer':
        customer = Customer.objects.filter(email=request.user.email).first()
        if customer:
            appointments = appointments.filter(customer=customer)
        else:
            appointments = appointments.none()
    return render(request, 'workshop/appointment_list.html', {'appointments': appointments})


@login_required
def appointment_create(request):
    form = AppointmentForm(request.POST or None)
    if form.is_valid():
        appt = form.save()
        messages.success(request, "Appointment booked.")
        return redirect('appointment_list')
    return render(request, 'workshop/appointment_form.html', {'form': form, 'title': 'Book Appointment'})


@login_required
def appointment_edit(request, pk):
    appt = get_object_or_404(Appointment, pk=pk)
    form = AppointmentForm(request.POST or None, instance=appt)
    if form.is_valid():
        form.save()
        messages.success(request, "Appointment updated.")
        return redirect('appointment_list')
    return render(request, 'workshop/appointment_form.html', {'form': form, 'title': 'Edit Appointment', 'appt': appt})


# ─────────────────────────────────────────────
#  PARTS INVENTORY
# ─────────────────────────────────────────────
@login_required
def parts_list(request):
    parts = Part.objects.all()
    q = request.GET.get('q', '')
    if q:
        parts = parts.filter(Q(name__icontains=q) | Q(part_number__icontains=q))
    low_stock = request.GET.get('low_stock')
    if low_stock:
        from django.db.models import F
        parts = parts.filter(stock_qty__lte=F('reorder_level'))
    return render(request, 'workshop/parts_list.html', {'parts': parts, 'q': q})


@login_required
def part_create(request):
    form = PartForm(request.POST or None)
    if form.is_valid():
        part = form.save()
        messages.success(request, f"Part '{part.name}' added.")
        return redirect('parts_list')
    return render(request, 'workshop/part_form.html', {'form': form, 'title': 'Add Part'})


@login_required
def part_edit(request, pk):
    part = get_object_or_404(Part, pk=pk)
    form = PartForm(request.POST or None, instance=part)
    if form.is_valid():
        form.save()
        messages.success(request, "Part updated.")
        return redirect('parts_list')
    return render(request, 'workshop/part_form.html', {'form': form, 'title': 'Edit Part', 'part': part})


# ─────────────────────────────────────────────
#  SERVICE CATALOGUE
# ─────────────────────────────────────────────
@login_required
def service_list(request):
    services = ServiceItem.objects.all()
    return render(request, 'workshop/service_list.html', {'services': services})


@login_required
def service_create(request):
    form = ServiceItemForm(request.POST or None)
    if form.is_valid():
        svc = form.save()
        messages.success(request, f"Service '{svc.name}' added.")
        return redirect('service_list')
    return render(request, 'workshop/service_form.html', {'form': form, 'title': 'Add Service'})


@login_required
def service_edit(request, pk):
    svc = get_object_or_404(ServiceItem, pk=pk)
    form = ServiceItemForm(request.POST or None, instance=svc)
    if form.is_valid():
        form.save()
        messages.success(request, "Service updated.")
        return redirect('service_list')
    return render(request, 'workshop/service_form.html', {'form': form, 'title': 'Edit Service', 'svc': svc})
