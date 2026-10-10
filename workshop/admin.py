from django.contrib import admin
from .models import AuditLog, Customer, Vehicle, RepairOrder, LaborLine, PartsLine, Invoice, InvoicePayment, Appointment, Part, ServiceItem


class ReadOnlyBusinessModelAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]


class LaborLineInline(admin.TabularInline):
    model = LaborLine
    extra = 0
    readonly_fields = [field.name for field in LaborLine._meta.fields]

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class PartsLineInline(admin.TabularInline):
    model = PartsLine
    extra = 0
    readonly_fields = [field.name for field in PartsLine._meta.fields]

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Customer)
class CustomerAdmin(ReadOnlyBusinessModelAdmin):
    list_display   = ['full_name', 'email', 'phone', 'address', 'created_at']
    search_fields  = ['first_name', 'last_name', 'email', 'phone']
    list_filter    = ['created_at']


@admin.register(Vehicle)
class VehicleAdmin(ReadOnlyBusinessModelAdmin):
    list_display  = ['__str__', 'license_plate', 'vin', 'mileage']
    search_fields = ['make', 'model', 'vin', 'license_plate', 'customer__last_name']
    list_filter   = ['make', 'year']


@admin.register(RepairOrder)
class RepairOrderAdmin(ReadOnlyBusinessModelAdmin):
    list_display   = ['__str__', 'status', 'assigned_tech', 'date_created', 'approved']
    list_filter    = ['status', 'approved', 'date_created']
    search_fields  = ['vehicle__make', 'vehicle__model', 'vehicle__customer__last_name']
    inlines        = [LaborLineInline, PartsLineInline]
    readonly_fields = [field.name for field in RepairOrder._meta.fields]


@admin.register(Invoice)
class InvoiceAdmin(ReadOnlyBusinessModelAdmin):
    list_display = ['__str__', 'issue_date', 'due_date', 'payment_status', 'payment_method']
    list_filter  = ['payment_status', 'payment_method', 'issue_date']
    readonly_fields = [field.name for field in Invoice._meta.fields]


@admin.register(InvoicePayment)
class InvoicePaymentAdmin(ReadOnlyBusinessModelAdmin):
    list_display = ['invoice', 'amount', 'payment_method', 'reference', 'received_at', 'recorded_by']
    list_filter = ['payment_method', 'received_at']
    search_fields = ['invoice__pk', 'reference', 'recorded_by__username']
    readonly_fields = [field.name for field in InvoicePayment._meta.fields]


@admin.register(Appointment)
class AppointmentAdmin(ReadOnlyBusinessModelAdmin):
    list_display = ['__str__', 'vehicle', 'duration', 'confirmed']
    list_filter  = ['confirmed', 'date_time']
    search_fields = ['customer__first_name', 'customer__last_name']
    readonly_fields = [field.name for field in Appointment._meta.fields]


@admin.register(Part)
class PartAdmin(ReadOnlyBusinessModelAdmin):
    list_display  = ['name', 'part_number', 'stock_qty', 'reorder_level', 'sell_price', 'supplier']
    list_filter   = ['supplier']
    search_fields = ['name', 'part_number']


@admin.register(ServiceItem)
class ServiceItemAdmin(ReadOnlyBusinessModelAdmin):
    list_display = ['name', 'labor_hours', 'labor_rate']
    search_fields = ['name']


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'actor', 'action', 'object_type', 'object_id', 'repair_order']
    list_filter = ['action', 'object_type', 'created_at']
    search_fields = ['action', 'object_type', 'actor__username']
    ordering = ['-created_at', '-pk']
    readonly_fields = [field.name for field in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
