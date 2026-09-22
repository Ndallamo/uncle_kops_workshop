from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.conf import settings
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
        return base64.b64decode(key_b64)

    def get_prep_value(self, value):
        # encrypt before saving
        if value is None:
            return None
        key = self._get_key()
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        ct = aesgcm.encrypt(nonce, value.encode('utf-8'), None)
        payload = nonce + ct
        return base64.b64encode(payload).decode('utf-8')

    def from_db_value(self, value, expression, connection):
        if value is None:
            return None
        key = self._get_key()
        aesgcm = AESGCM(key)
        try:
            data = base64.b64decode(value)
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
        # if looks like base64 blob (saved), attempt to decrypt
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


# ─────────────────────────────────────────────
#  LINE ITEMS
# ─────────────────────────────────────────────
class LaborLine(models.Model):
    repair_order = models.ForeignKey(RepairOrder, on_delete=models.CASCADE, related_name='labor_lines')
    service_item = models.ForeignKey(ServiceItem, on_delete=models.PROTECT)
    hours        = models.DecimalField(max_digits=5, decimal_places=2)
    rate         = models.DecimalField(max_digits=8, decimal_places=2)
    notes        = models.TextField(blank=True)

    def __str__(self):
        return f"{self.service_item} x {self.hours}h"

    @property
    def line_total(self):
        return self.hours * self.rate


class PartsLine(models.Model):
    repair_order = models.ForeignKey(RepairOrder, on_delete=models.CASCADE, related_name='parts_lines')
    part         = models.ForeignKey(Part, on_delete=models.PROTECT)
    quantity     = models.PositiveIntegerField(default=1)
    unit_price   = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.part} x {self.quantity}"

    @property
    def line_total(self):
        return self.quantity * self.unit_price


# ─────────────────────────────────────────────
#  INVOICE
# ─────────────────────────────────────────────
class Invoice(models.Model):
    PAYMENT_CHOICES = [
        ('unpaid',  'Unpaid'),
        ('partial', 'Partially Paid'),
        ('paid',    'Paid'),
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

    def __str__(self):
        return f"INV#{self.pk} – {self.repair_order}"

    @property
    def subtotal(self):
        return max(self.service_amount - self.discount, 0)

    @property
    def tax_amount(self):
        return self.subtotal * (max(self.tax_rate, 0) / 100)

    @property
    def total_due(self):
        return self.subtotal + self.tax_amount


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
