from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.conf import settings
from decimal import Decimal, ROUND_HALF_UP
import base64
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import hashlib
import secrets


# EncryptedTextField: AES-256-GCM at-rest encryption for sensitive fields
class EncryptedTextField(models.TextField):
    description = "Text field that transparently encrypts/decrypts using AES-256-GCM"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _get_key(self):
        key_b64 = getattr(settings, 'ENCRYPTION_KEY', '')
        if not key_b64:
            raise RuntimeError('ENCRYPTION_KEY is not configured in settings')

        raw_key = key_b64.encode('utf-8')
        try:
            key = base64.b64decode(raw_key, altchars=b'-_')
        except Exception:
            key = base64.b64decode(raw_key)

        if len(key) not in (16, 24, 32):
            raise RuntimeError('ENCRYPTION_KEY must decode to a valid AES key length (16, 24, or 32 bytes)')
        return key

    def get_prep_value(self, value):
        # encrypt before saving
        if value is None:
            return None
        if not isinstance(value, str):
            value = str(value)
        key = self._get_key()
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        ct = aesgcm.encrypt(nonce, value.encode('utf-8'), None)
        payload = nonce + ct
        return base64.b64encode(payload).decode('utf-8')

    def from_db_value(self, value, expression, connection):
        if value is None:
            return None
        if isinstance(value, str) and value == '':
            return ''
        key = self._get_key()
        aesgcm = AESGCM(key)
        try:
            data = base64.b64decode(value.encode('utf-8'), altchars=b'-_')
            nonce = data[:12]
            ct = data[12:]
            pt = aesgcm.decrypt(nonce, ct, None)
            return pt.decode('utf-8')
        except Exception:
            return value

    def to_python(self, value):
        # when accessed in Python, decrypt
        if value is None:
            return None
        if isinstance(value, str) and value == '':
            return ''
        try:
            return self.from_db_value(value, None, None)
        except Exception:
            return value


# ─────────────────────────────────────────────
#  CUSTOMER
# ─────────────────────────────────────────────
class Customer(models.Model):
    first_name   = models.CharField(max_length=100)
    last_name    = models.CharField(max_length=100)
    email        = models.EmailField(unique=True)
    phone        = EncryptedTextField(blank=True, null=True)
    address      = EncryptedTextField(blank=True, null=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    notes        = EncryptedTextField(blank=True, null=True)

    class Meta:
        ordering = ['last_name', 'first_name']

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def has_required_contact_details(self):
        return bool((self.phone or '').strip() and (self.address or '').strip())


# Email verification token model (store token hash, short TTL)
class EmailVerificationToken(models.Model):
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='verification_tokens')
    token_hash = models.CharField(max_length=128, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)

    @classmethod
    def generate_for_user(cls, user, ttl_minutes=30):
        raw = secrets.token_urlsafe(32)
        h = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        expires = timezone.now() + timezone.timedelta(minutes=ttl_minutes)
        obj = cls.objects.create(user=user, token_hash=h, expires_at=expires)
        return raw, obj

    @classmethod
    def validate_token(cls, raw_token):
        h = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
        try:
            obj = cls.objects.get(token_hash=h)
        except cls.DoesNotExist:
            return None
        if obj.used:
            return None
        if timezone.now() > obj.expires_at:
            return None
        return obj


# Password reset tokens (store token hash, short TTL)
class PasswordResetToken(models.Model):
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='password_reset_tokens')
    token_hash = models.CharField(max_length=128, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)

    @classmethod
    def generate_for_user(cls, user, ttl_minutes=30):
        cls.objects.filter(user=user, used=False).update(used=True)
        raw = secrets.token_urlsafe(32)
        h = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        expires = timezone.now() + timezone.timedelta(minutes=ttl_minutes)
        obj = cls.objects.create(user=user, token_hash=h, expires_at=expires)
        return raw, obj

    @classmethod
    def validate_token(cls, raw_token):
        h = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
        try:
            obj = cls.objects.get(token_hash=h)
        except cls.DoesNotExist:
            return None
        if obj.used:
            return None
        if timezone.now() > obj.expires_at:
            return None
        return obj


# ─────────────────────────────────────────────
#  USER PROFILE
# ─────────────────────────────────────────────
class UserProfile(models.Model):
    ROLE_CHOICES = [
        ('customer', 'Customer'),
        ('mechanic', 'Mechanic'),
        ('admin', 'Admin'),
    ]

    user = models.OneToOneField('auth.User', on_delete=models.CASCADE, related_name='userprofile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='customer')
    is_verified = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username} ({self.role})"


# ─────────────────────────────────────────────
#  VEHICLE
# ─────────────────────────────────────────────
class Vehicle(models.Model):
    customer    = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='vehicles')
    make        = models.CharField(max_length=50)
    model       = models.CharField(max_length=50)
    year        = models.PositiveIntegerField()
    vin         = models.CharField(max_length=17, blank=True)
    license_plate = models.CharField(max_length=20, blank=True)
    color       = models.CharField(max_length=30, blank=True)
    mileage     = models.PositiveIntegerField(default=0)
    # Service metadata
    service_plan = models.CharField(max_length=200, blank=True)
    recent_service_history = models.TextField(blank=True)
    notes       = models.TextField(blank=True)

    def __str__(self):
        return f"{self.year} {self.make} {self.model} ({self.customer})"
    



# ─────────────────────────────────────────────
#  SERVICE / LABOUR CATALOGUE
# ─────────────────────────────────────────────
class ServiceItem(models.Model):
    name        = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    labor_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    labor_rate  = models.DecimalField(max_digits=8, decimal_places=2, default=0)  # per hour

    class Meta:
        constraints = [
            models.CheckConstraint(check=models.Q(labor_hours__gte=0), name='service_labor_hours_nonnegative'),
            models.CheckConstraint(check=models.Q(labor_rate__gte=0), name='service_labor_rate_nonnegative'),
        ]

    def __str__(self):
        return self.name

    @property
    def labor_cost(self):
        return self.labor_hours * self.labor_rate


# ─────────────────────────────────────────────
#  PARTS INVENTORY
# ─────────────────────────────────────────────
class Part(models.Model):
    name         = models.CharField(max_length=150)
    part_number  = models.CharField(max_length=50, blank=True)
    description  = models.TextField(blank=True)
    cost_price   = models.DecimalField(max_digits=10, decimal_places=2)
    sell_price   = models.DecimalField(max_digits=10, decimal_places=2)
    stock_qty    = models.PositiveIntegerField(default=0)
    reorder_level = models.PositiveIntegerField(default=5)
    supplier     = models.CharField(max_length=150, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(check=models.Q(cost_price__gte=0), name='part_cost_price_nonnegative'),
            models.CheckConstraint(check=models.Q(sell_price__gte=0), name='part_sell_price_nonnegative'),
        ]

    def __str__(self):
        return f"{self.name} ({self.part_number})"

    @property
    def low_stock(self):
        return self.stock_qty <= self.reorder_level


# ─────────────────────────────────────────────
#  REPAIR ORDER
# ─────────────────────────────────────────────
class RepairOrder(models.Model):
    STATUS_CHOICES = [
        ('pending',    'Pending'),
        ('in_progress','In Progress'),
        ('waiting',    'Waiting for Parts'),
        ('ready',      'Ready for Pickup'),
        ('completed',  'Completed'),
        ('cancelled',  'Cancelled'),
    ]

    vehicle         = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name='repair_orders')
    assigned_tech   = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='repair_orders')
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    pending_status  = models.CharField(max_length=20, choices=STATUS_CHOICES, blank=True, default='')
    description     = models.TextField(help_text="Customer complaint / work requested")
    internal_notes  = models.TextField(blank=True)
    mileage_in      = models.PositiveIntegerField(default=0)
    mileage_out     = models.PositiveIntegerField(null=True, blank=True)
    date_created    = models.DateTimeField(auto_now_add=True)
    date_updated    = models.DateTimeField(auto_now=True)
    date_completed  = models.DateTimeField(null=True, blank=True)
    approved        = models.BooleanField(default=False)

    class Meta:
        ordering = ['-date_created']

    def __str__(self):
        return f"RO#{self.pk} – {self.vehicle} ({self.status})"

    @property
    def total_labor(self):
        return sum(item.line_total for item in self.labor_lines.all())

    @property
    def total_parts(self):
        return sum(item.line_total for item in self.parts_lines.all())

    @property
    def grand_total(self):
        return self.total_labor + self.total_parts


class RepairEstimate(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending customer decision'),
        ('approved', 'Approved'),
        ('declined', 'Declined'),
    ]

    repair_order = models.ForeignKey(RepairOrder, on_delete=models.CASCADE, related_name='estimates')
    version = models.PositiveIntegerField(default=1)
    labor_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    parts_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    decided_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='decided_repair_estimates')
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-version', '-created_at']
        constraints = [
            models.UniqueConstraint(fields=['repair_order', 'version'], name='unique_repair_estimate_version'),
        ]

    def __str__(self):
        return f'Estimate v{self.version} for RO#{self.repair_order_id}'


class RepairEstimateLine(models.Model):
    LINE_TYPES = [('labor', 'Labor'), ('part', 'Part')]

    repair_order = models.ForeignKey(RepairOrder, on_delete=models.CASCADE, related_name='estimate_lines')
    line_type = models.CharField(max_length=10, choices=LINE_TYPES)
    service_item = models.ForeignKey(ServiceItem, on_delete=models.PROTECT, null=True, blank=True)
    part = models.ForeignKey(Part, on_delete=models.PROTECT, null=True, blank=True)
    quantity = models.DecimalField(max_digits=7, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='created_estimate_lines')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'pk']
        constraints = [
            models.CheckConstraint(check=models.Q(quantity__gt=0), name='estimate_line_quantity_positive'),
            models.CheckConstraint(check=models.Q(unit_price__gte=0), name='estimate_line_price_nonnegative'),
            models.CheckConstraint(
                check=(
                    models.Q(line_type='labor', service_item__isnull=False, part__isnull=True)
                    | models.Q(line_type='part', service_item__isnull=True, part__isnull=False)
                ),
                name='estimate_line_item_matches_type',
            ),
        ]

    @property
    def line_total(self):
        return (self.quantity * self.unit_price).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


class RepairOrderEvent(models.Model):
    EVENT_CHOICES = [
        ('created', 'Repair order created'),
        ('assignment', 'Mechanic assignment changed'),
        ('status_proposed', 'Status proposed'),
        ('status_changed', 'Status changed'),
        ('approval', 'Customer approval recorded'),
        ('payment', 'Payment recorded'),
        ('work_logged', 'Repair work logged'),
        ('cancelled', 'Repair order cancelled'),
        ('collected', 'Vehicle collected'),
    ]

    repair_order = models.ForeignKey(RepairOrder, on_delete=models.CASCADE, related_name='events')
    event_type = models.CharField(max_length=30, choices=EVENT_CHOICES)
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='repair_order_events')
    previous_status = models.CharField(max_length=20, blank=True)
    current_status = models.CharField(max_length=20, blank=True)
    note = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    customer_visible = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'pk']

    def __str__(self):
        return f'{self.get_event_type_display()} for RO#{self.repair_order_id}'


class CollectionRecord(models.Model):
    repair_order = models.OneToOneField(RepairOrder, on_delete=models.PROTECT, related_name='collection_record')
    collected_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='vehicle_collections')
    collected_at = models.DateTimeField(auto_now_add=True)
    handover_note = models.TextField(blank=True)

    def __str__(self):
        return f'Collection for RO#{self.repair_order_id}'


class Notification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    repair_order = models.ForeignKey(RepairOrder, on_delete=models.CASCADE, null=True, blank=True, related_name='notifications')
    message = models.CharField(max_length=255)
    link = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']

    def __str__(self):
        return self.message


class RepairDocument(models.Model):
    repair_order = models.ForeignKey(RepairOrder, on_delete=models.CASCADE, related_name='documents')
    title = models.CharField(max_length=150)
    file = models.FileField(upload_to='repair_documents/')
    uploaded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='uploaded_repair_documents')
    customer_visible = models.BooleanField(default=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at', '-pk']

    def __str__(self):
        return self.title


class ImmutableAuditLogQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TypeError('Audit log entries are immutable.')

    def delete(self):
        raise TypeError('Audit log entries cannot be deleted.')

    def bulk_update(self, objs, fields, batch_size=None):
        raise TypeError('Audit log entries are immutable.')


class AuditLog(models.Model):
    objects = ImmutableAuditLogQuerySet.as_manager()

    actor = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name='audit_entries')
    action = models.CharField(max_length=100)
    object_type = models.CharField(max_length=100)
    object_id = models.PositiveBigIntegerField(null=True, blank=True)
    repair_order = models.ForeignKey(RepairOrder, on_delete=models.PROTECT, null=True, blank=True, related_name='audit_entries')
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError('Audit log entries are immutable.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError('Audit log entries cannot be deleted.')

    def __str__(self):
        return f'{self.action} {self.object_type}#{self.object_id or ""}'.strip()


# ─────────────────────────────────────────────
#  LINE ITEMS
# ─────────────────────────────────────────────
class LaborLine(models.Model):
    repair_order = models.ForeignKey(RepairOrder, on_delete=models.CASCADE, related_name='labor_lines')
    service_item = models.ForeignKey(ServiceItem, on_delete=models.PROTECT)
    hours        = models.DecimalField(max_digits=5, decimal_places=2)
    rate         = models.DecimalField(max_digits=8, decimal_places=2)
    notes        = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(check=models.Q(hours__gt=0), name='labor_line_hours_positive'),
            models.CheckConstraint(check=models.Q(rate__gte=0), name='labor_line_rate_nonnegative'),
        ]

    def __str__(self):
        return f"{self.service_item} x {self.hours}h"

    @property
    def line_total(self):
        return (self.hours * self.rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


class PartsLine(models.Model):
    repair_order = models.ForeignKey(RepairOrder, on_delete=models.CASCADE, related_name='parts_lines')
    part         = models.ForeignKey(Part, on_delete=models.PROTECT)
    quantity     = models.PositiveIntegerField(default=1)
    unit_price   = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        constraints = [
            models.CheckConstraint(check=models.Q(quantity__gt=0), name='parts_line_quantity_positive'),
            models.CheckConstraint(check=models.Q(unit_price__gte=0), name='parts_line_price_nonnegative'),
        ]

    def __str__(self):
        return f"{self.part} x {self.quantity}"

    @property
    def line_total(self):
        return (self.quantity * self.unit_price).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


# ─────────────────────────────────────────────
#  INVOICE
# ─────────────────────────────────────────────
class Invoice(models.Model):
    PAYMENT_CHOICES = [
        ('unpaid',  'Unpaid'),
        ('partial', 'Partially Paid'),
        ('paid',    'Paid'),
        ('unverified', 'Needs Verification'),
    ]
    METHOD_CHOICES = [
        ('cash',   'Cash'),
        ('card',   'Card'),
        ('eft',    'EFT'),
        ('other',  'Other'),
    ]

    repair_order    = models.OneToOneField(RepairOrder, on_delete=models.PROTECT, related_name='invoice')
    service_amount  = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    issue_date      = models.DateField(default=timezone.now)
    due_date        = models.DateField()
    payment_status  = models.CharField(max_length=10, choices=PAYMENT_CHOICES, default='unpaid')
    payment_method  = models.CharField(max_length=10, choices=METHOD_CHOICES, blank=True)
    discount        = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    tax_rate        = models.DecimalField(max_digits=5, decimal_places=2, default=15)  # % VAT
    notes           = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(check=models.Q(service_amount__gte=0), name='invoice_service_amount_nonnegative'),
            models.CheckConstraint(check=models.Q(discount__gte=0), name='invoice_discount_nonnegative'),
            models.CheckConstraint(check=models.Q(discount__lte=models.F('service_amount')), name='invoice_discount_within_service_amount'),
            models.CheckConstraint(check=models.Q(tax_rate__gte=0), name='invoice_tax_rate_nonnegative'),
            models.CheckConstraint(check=models.Q(due_date__gte=models.F('issue_date')), name='invoice_due_date_not_before_issue'),
        ]

    def __str__(self):
        return f"INV#{self.pk} – {self.repair_order}"

    @property
    def subtotal(self):
        return max(self.service_amount - self.discount, 0)

    @property
    def tax_amount(self):
        tax_rate = max(Decimal(str(self.tax_rate)), Decimal('0.00'))
        return (self.subtotal * (tax_rate / Decimal('100'))).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )

    @property
    def total_due(self):
        return (self.subtotal + self.tax_amount).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )

    @property
    def paid_amount(self):
        if hasattr(self, 'report_paid_amount'):
            return self.report_paid_amount or Decimal('0.00')
        return self.payments.aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')

    @property
    def balance_due(self):
        return max(self.total_due - self.paid_amount, Decimal('0.00'))

    def refresh_payment_status(self, *, payment_method=None):
        paid_amount = self.paid_amount
        if paid_amount >= self.total_due and paid_amount > 0:
            self.payment_status = 'paid'
        elif paid_amount > 0:
            self.payment_status = 'partial'
        else:
            self.payment_status = 'unpaid'
        update_fields = ['payment_status']
        if payment_method:
            self.payment_method = payment_method
            update_fields.append('payment_method')
        self.save(update_fields=update_fields)


class InvoicePayment(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=10, choices=Invoice.METHOD_CHOICES)
    reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    received_at = models.DateTimeField(default=timezone.now)
    recorded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recorded_invoice_payments',
    )

    class Meta:
        ordering = ['-received_at', '-pk']
        constraints = [
            models.CheckConstraint(check=models.Q(amount__gt=0), name='invoice_payment_amount_positive'),
        ]

    def __str__(self):
        return f"Payment R {self.amount} for INV#{self.invoice_id}"


# ─────────────────────────────────────────────
#  APPOINTMENT / BOOKING
# ─────────────────────────────────────────────
class Appointment(models.Model):
    ASSIGNMENT_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('declined', 'Declined'),
    ]

    customer    = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='appointments')
    vehicle     = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name='appointments')
    repair_order = models.ForeignKey(RepairOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name='appointments')
    date_time   = models.DateTimeField()
    duration    = models.PositiveIntegerField(default=60, help_text="Duration in minutes")
    service_desc = models.TextField()
    confirmed   = models.BooleanField(default=False)
    assigned_mechanic = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_appointments')
    assignment_status = models.CharField(max_length=20, choices=ASSIGNMENT_CHOICES, default='pending')
    notes       = models.TextField(blank=True)

    class Meta:
        ordering = ['date_time']

    def __str__(self):
        return f"{self.customer} – {self.date_time:%Y-%m-%d %H:%M}"

    @classmethod
    def has_schedule_conflict(cls, *, mechanic, date_time, duration, exclude_pk=None):
        if not mechanic or not date_time:
            return False

        requested_end = date_time + timezone.timedelta(minutes=duration)
        accepted_appointments = cls.objects.filter(
            assigned_mechanic=mechanic,
            assignment_status='accepted',
        ).only('date_time', 'duration')
        if exclude_pk:
            accepted_appointments = accepted_appointments.exclude(pk=exclude_pk)

        return any(
            date_time < appointment.date_time + timezone.timedelta(minutes=appointment.duration)
            and appointment.date_time < requested_end
            for appointment in accepted_appointments
        )
