from django.urls import path
from . import views

urlpatterns = [
    # Auth API
    path('api/auth/register',        views.api_register,            name='api_register'),
    path('verify-email/',            views.verify_email,           name='verify_email'),
    path('api/auth/resend-verification', views.resend_verification,  name='resend_verification'),
    path('forgot-password/',         views.forgot_password,         name='forgot_password'),
    path('reset-password/',          views.reset_password,          name='reset_password'),
    # Dashboard / Reporting
    path('',                        views.dashboard,              name='dashboard'),
    path('report/',                 views.report,                 name='report'),
    path('report/export/',          views.report_export,           name='report_export'),
    path('audit-log/',              views.audit_log,               name='audit_log'),
    path('privacy-policy/',         views.privacy_policy,         name='privacy_policy'),
    path('terms-and-conditions/',   views.terms_and_conditions,   name='terms_and_conditions'),
    path('notifications/<int:pk>/read/', views.notification_mark_read, name='notification_mark_read'),

    # Customers
    path('customers/',              views.customer_list,          name='customer_list'),
    path('customers/new/',          views.customer_create,        name='customer_create'),
    path('customers/<int:pk>/',     views.customer_detail,        name='customer_detail'),
    path('profile/',                 views.customer_profile,       name='customer_profile'),
    path('customers/<int:pk>/edit/',views.customer_edit,          name='customer_edit'),

    # Vehicles
    path('vehicles/',               views.vehicle_list,           name='vehicle_list'),
    path('vehicles/new/',           views.vehicle_create,         name='vehicle_create'),
    path('vehicles/<int:pk>/',      views.vehicle_detail,         name='vehicle_detail'),
    path('vehicles/<int:pk>/edit/', views.vehicle_edit,           name='vehicle_edit'),

    # Repair Orders
    path('repairs/',                views.repair_order_list,      name='repair_order_list'),
    path('repairs/new/',            views.repair_order_create,    name='repair_order_create'),
    path('repairs/<int:pk>/',       views.repair_order_detail,    name='repair_order_detail'),
    path('repairs/<int:pk>/estimate-lines/add/', views.repair_estimate_line_add, name='repair_estimate_line_add'),
    path('repairs/<int:pk>/documents/upload/', views.repair_document_upload, name='repair_document_upload'),
    path('documents/<int:pk>/download/', views.repair_document_download, name='repair_document_download'),
    path('repairs/<int:pk>/edit/',  views.repair_order_edit,      name='repair_order_edit'),
    path('repairs/<int:pk>/<str:action>/decision/', views.repair_order_decision, name='repair_order_decision'),
    path('repairs/<int:pk>/customer/<str:action>/', views.repair_order_customer_decision, name='repair_order_customer_decision'),
    path('repairs/<int:pk>/cancel/', views.repair_order_cancel, name='repair_order_cancel'),
    path('repairs/<int:pk>/finalize/<str:action>/', views.repair_order_finalize, name='repair_order_finalize'),
    path('repairs/<int:pk>/status/<str:action>/', views.repair_order_status_review, name='repair_order_status_review'),
    path('repairs/<int:pk>/status/', views.repair_order_status_proposal, name='repair_order_status_proposal'),
    path('repairs/<int:ro_pk>/labor/',  views.add_labor_line,     name='add_labor_line'),
    path('repairs/<int:ro_pk>/parts/',  views.add_parts_line,     name='add_parts_line'),

    # Invoices
    path('invoices/',               views.invoice_list,           name='invoice_list'),
    path('invoices/new/',           views.invoice_create,         name='invoice_create'),
    path('invoices/<int:pk>/',      views.invoice_detail,         name='invoice_detail'),
    path('invoices/<int:pk>/download/', views.invoice_download,    name='invoice_download'),
    path('invoices/<int:pk>/pay/',  views.invoice_pay,            name='invoice_pay'),
    path('invoices/<int:pk>/edit/', views.invoice_edit,           name='invoice_edit'),

    # Appointments
    path('appointments/',           views.appointment_list,       name='appointment_list'),
    path('appointments/new/',       views.appointment_create,     name='appointment_create'),
    path('appointments/<int:pk>/edit/', views.appointment_edit,   name='appointment_edit'),
    path('appointments/<int:pk>/delete/', views.appointment_delete, name='appointment_delete'),
    path('appointments/<int:pk>/<str:action>/', views.appointment_decision, name='appointment_decision'),

    # Parts Inventory
    path('parts/',                  views.parts_list,             name='parts_list'),
    path('parts/new/',              views.part_create,            name='part_create'),
    path('parts/<int:pk>/edit/',    views.part_edit,              name='part_edit'),

    # Service Catalogue
    path('services/',               views.service_list,           name='service_list'),
    path('services/new/',           views.service_create,         name='service_create'),
    path('services/<int:pk>/edit/', views.service_edit,           name='service_edit'),

    # Employees (Mechanics)
    path('employees/',              views.employee_list,          name='employee_list'),
    path('employees/new/',          views.employee_create,        name='employee_create'),
    path('employees/<int:pk>/edit/',views.employee_edit,          name='employee_edit'),
]
