from django.contrib import admin
from .models import Customer, Vehicle, RepairOrder, LaborLine, PartsLine, Invoice, Appointment, Part, ServiceItem


class LaborLineInline(admin.TabularInline):
    model = LaborLine
    extra = 1


class PartsLineInline(admin.TabularInline):
    model = PartsLine
    extra = 1


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display   = ['full_name', 'email', 'phone', 'created_at']
    search_fields  = ['first_name', 'last_name', 'email', 'phone']
    list_filter    = ['created_at']


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display  = ['__str__', 'license_plate', 'vin', 'mileage']
    search_fields = ['make', 'model', 'vin', 'license_plate', 'customer__last_name']
    list_filter   = ['make', 'year']


@admin.register(RepairOrder)
class RepairOrderAdmin(admin.ModelAdmin):
    list_display   = ['__str__', 'status', 'assigned_tech', 'date_created', 'approved']
    list_filter    = ['status', 'approved', 'date_created']
    search_fields  = ['vehicle__make', 'vehicle__model', 'vehicle__customer__last_name']
    inlines        = [LaborLineInline, PartsLineInline]
    readonly_fields = ['date_created', 'date_updated']


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'issue_date', 'due_date', 'payment_status', 'payment_method']
    list_filter  = ['payment_status', 'payment_method', 'issue_date']


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'vehicle', 'duration', 'confirmed']
    list_filter  = ['confirmed', 'date_time']
    search_fields = ['customer__first_name', 'customer__last_name']


@admin.register(Part)
class PartAdmin(admin.ModelAdmin):
    list_display  = ['name', 'part_number', 'stock_qty', 'reorder_level', 'sell_price', 'supplier']
    list_filter   = ['supplier']
    search_fields = ['name', 'part_number']


@admin.register(ServiceItem)
class ServiceItemAdmin(admin.ModelAdmin):
    list_display = ['name', 'labor_hours', 'labor_rate']
    search_fields = ['name']
