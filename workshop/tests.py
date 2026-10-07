from decimal import Decimal
from datetime import date, timedelta
import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection, transaction
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from workshop.forms import CustomerForm, InvoiceForm, InvoicePaymentForm, LaborLineForm, PartsLineForm, RepairOrderForm
from workshop.forms import CustomerForm, InvoiceForm, InvoicePaymentForm, LaborLineForm, PartsLineForm, RepairEstimateLineForm, RepairOrderForm
from workshop.models import AuditLog, Appointment, CollectionRecord, Customer, EmailVerificationToken, Invoice, InvoicePayment, LaborLine, Notification, Part, PartsLine, PasswordResetToken, RepairDocument, RepairEstimate, RepairEstimateLine, RepairOrder, RepairOrderEvent, ServiceItem, UserProfile, Vehicle
from workshop.auth_utils import send_invoice_ready_email, send_password_reset_email, send_verification_email
from workshop.currency import format_rand


def add_estimate_line(order, created_by=None):
    if created_by is None:
        created_by, _ = User.objects.get_or_create(username='estimate-helper')
    service = ServiceItem.objects.create(name=f'Estimate service {order.pk}', labor_hours=1, labor_rate=250)
    return RepairEstimateLine.objects.create(
        repair_order=order,
        line_type='labor',
        service_item=service,
        quantity=1,
        unit_price=250,
        created_by=created_by,
    )


class InvoiceFormTests(TestCase):
    def test_invoice_form_includes_service_amount_field(self):
        form = InvoiceForm()
        self.assertIn('service_amount', form.fields)
        self.assertEqual(form.fields['service_amount'].label, 'Service amount (R)')
        self.assertEqual(form.fields['discount'].label, 'Discount (R)')
        self.assertTrue(form.fields['service_amount'].disabled)
        self.assertEqual(form.fields['repair_order'].empty_label, 'Choose repair/vehicle')
        self.assertNotIn('payment_status', form.fields)
        self.assertNotIn('payment_method', form.fields)

    def test_line_item_forms_use_descriptive_empty_labels(self):
        labor_form = LaborLineForm()
        parts_form = PartsLineForm()

        self.assertEqual(labor_form.fields['service_item'].empty_label, 'Choose service item')
        self.assertEqual(labor_form.fields['rate'].label, 'Rate (R/hour)')
        self.assertEqual(labor_form.fields['total_amount'].label, 'Total amount (R)')
        self.assertIn('total_amount', labor_form.fields)
        self.assertEqual(parts_form.fields['part'].empty_label, 'Choose part')
        self.assertEqual(parts_form.fields['unit_price'].label, 'Unit price (R)')

    def test_invoice_form_excludes_repair_orders_with_existing_invoices(self):
        customer = Customer.objects.create(first_name='A', last_name='B', email='invoice@example.com')
        vehicle = Vehicle.objects.create(customer=customer, make='Toyota', model='Yaris', year=2020)
        order = RepairOrder.objects.create(vehicle=vehicle, description='Service')
        Invoice.objects.create(repair_order=order, due_date=timezone.localdate() + timedelta(days=1))

        form = InvoiceForm()

        self.assertFalse(form.fields['repair_order'].queryset.filter(pk=order.pk).exists())


class CurrencyFormattingTests(TestCase):
    def test_rand_formatter_rounds_half_up_to_two_decimal_places(self):
        self.assertEqual(format_rand(Decimal('12.345')), 'R 12.35')
        self.assertEqual(format_rand(Decimal('12')), 'R 12.00')
        self.assertEqual(format_rand(Decimal('-12.345')), 'R -12.35')

    def test_catalogue_prices_use_two_decimal_rand_values(self):
        admin = User.objects.create_user(username='currency-admin', password='test-password', is_staff=True)
        UserProfile.objects.create(user=admin, role='admin')
        Part.objects.create(
            name='Currency test part',
            cost_price=Decimal('125.50'),
            sell_price=Decimal('250.75'),
        )
        ServiceItem.objects.create(
            name='Currency test service',
            labor_hours=Decimal('1.50'),
            labor_rate=Decimal('350.50'),
        )
        self.client.force_login(admin)

        parts_response = self.client.get(reverse('parts_list'))
        service_response = self.client.get(reverse('service_list'))

        self.assertContains(parts_response, 'R 125.50')
        self.assertContains(parts_response, 'R 250.75')
        self.assertContains(service_response, 'R 350.50')
        self.assertContains(service_response, 'R 525.75')


class RepairPricingWorkflowTests(TestCase):
    def setUp(self):
        customer = Customer.objects.create(first_name='A', last_name='B', email='pricing@example.com')
        vehicle = Vehicle.objects.create(customer=customer, make='Toyota', model='Yaris', year=2020)
        self.order = RepairOrder.objects.create(vehicle=vehicle, description='Service')
        self.service = ServiceItem.objects.create(name='Brake service', labor_hours=2, labor_rate=350)
        self.part = Part.objects.create(
            name='Brake pad',
            part_number='BP-1',
            cost_price=100,
            sell_price=175,
            stock_qty=10,
        )

    def test_labor_rate_comes_from_service_catalog(self):
        form = LaborLineForm(data={
            'service_item': self.service.pk,
            'hours': '2',
            'rate': '1',
            'notes': '',
        })

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['rate'], Decimal('350.00'))

    def test_part_price_comes_from_inventory_catalog(self):
        form = PartsLineForm(data={
            'part': self.part.pk,
            'quantity': '2',
            'unit_price': '1',
        })

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['unit_price'], Decimal('175.00'))

    def test_invoice_work_amount_comes_from_repair_order_lines(self):
        from workshop.models import LaborLine, PartsLine

        self.order.approved = True
        self.order.save(update_fields=['approved'])
        LaborLine.objects.create(repair_order=self.order, service_item=self.service, hours=2, rate=350)
        PartsLine.objects.create(repair_order=self.order, part=self.part, quantity=2, unit_price=175)
        form = InvoiceForm(data={
            'repair_order': self.order.pk,
            'service_amount': '1.00',
            'issue_date': '2026-09-30',
            'due_date': '2026-10-01',
            'payment_status': 'unpaid',
            'payment_method': '',
            'discount': '0',
            'tax_rate': '15',
            'notes': '',
        })

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['service_amount'], Decimal('1050.00'))

    def test_tax_total_is_rounded_to_cents(self):
        invoice = Invoice.objects.create(
            repair_order=self.order,
            due_date=timezone.localdate() + timedelta(days=1),
            service_amount=Decimal('10.05'),
            tax_rate=Decimal('15.00'),
        )

        self.assertEqual(invoice.tax_amount, Decimal('1.51'))
        self.assertEqual(invoice.total_due, Decimal('11.56'))

    def test_work_lines_cannot_be_added_after_invoice_creation(self):
        admin = User.objects.create_user(username='pricingadmin', password='test-password', is_staff=True)
        UserProfile.objects.create(user=admin, role='admin')
        Invoice.objects.create(
            repair_order=self.order,
            due_date=timezone.localdate() + timedelta(days=1),
        )
        self.client.force_login(admin)

        response = self.client.get(reverse('add_labor_line', args=[self.order.pk]))

        self.assertRedirects(response, reverse('repair_order_detail', args=[self.order.pk]))

    def test_part_usage_cannot_exceed_available_inventory(self):
        admin = User.objects.create_user(username='partsadmin', password='test-password', is_staff=True)
        UserProfile.objects.create(user=admin, role='admin')
        self.order.approved = True
        self.order.save(update_fields=['approved'])
        self.part.stock_qty = 2
        self.part.save(update_fields=['stock_qty'])
        self.client.force_login(admin)

        response = self.client.post(
            reverse('add_parts_line', args=[self.order.pk]),
            {
                'part': self.part.pk,
                'quantity': '3',
                'unit_price': '1',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Not enough stock')
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock_qty, 2)
        self.assertFalse(self.order.parts_lines.exists())

    def test_work_line_forms_reject_nonpositive_quantities(self):
        labor_form = LaborLineForm(data={
            'service_item': self.service.pk,
            'hours': '0',
            'notes': '',
        })
        parts_form = PartsLineForm(data={
            'part': self.part.pk,
            'quantity': '0',
        })

        self.assertFalse(labor_form.is_valid())
        self.assertIn('hours', labor_form.errors)
        self.assertFalse(parts_form.is_valid())
        self.assertIn('quantity', parts_form.errors)

    def test_estimate_form_rejects_mismatched_labor_and_part_references(self):
        form = RepairEstimateLineForm(data={
            'line_type': 'labor',
            'service_item': self.service.pk,
            'part': self.part.pk,
            'quantity': '1',
            'unit_price': '',
            'notes': '',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('part', form.errors)

    def test_invoice_form_rejects_excessive_discounts_and_early_due_dates(self):
        self.order.approved = True
        self.order.save(update_fields=['approved'])
        data = {
            'repair_order': self.order.pk,
            'service_amount': '0.00',
            'issue_date': '2026-10-02',
            'due_date': '2026-10-01',
            'discount': '0.00',
            'tax_rate': '15.00',
            'notes': '',
        }
        date_form = InvoiceForm(data=data)
        self.assertFalse(date_form.is_valid())
        self.assertIn('due_date', date_form.errors)

        data['due_date'] = '2026-10-03'
        data['discount'] = '1.00'
        discount_form = InvoiceForm(data=data)
        self.assertFalse(discount_form.is_valid())
        self.assertIn('discount', discount_form.errors)

    def test_database_constraints_reject_invalid_work_lines_and_invoice_pricing(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                LaborLine.objects.create(
                    repair_order=self.order,
                    service_item=self.service,
                    hours=0,
                    rate=100,
                )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.order.parts_lines.create(part=self.part, quantity=0, unit_price=10)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Invoice.objects.create(
                    repair_order=self.order,
                    due_date=date(2026, 10, 2),
                    issue_date=date(2026, 10, 3),
                    service_amount=0,
                    discount=1,
                )

    def test_repair_order_edit_is_audited_with_assignment_ids(self):
        admin = User.objects.create_user(username='repair-editaudit-admin', password='test-password', is_staff=True)
        mechanic = User.objects.create_user(username='repair-editaudit-mechanic', password='test-password')
        UserProfile.objects.create(user=mechanic, role='mechanic')
        self.client.force_login(admin)

        response = self.client.post(reverse('repair_order_edit', args=[self.order.pk]), {
            'vehicle': self.order.vehicle_id,
            'assigned_tech': mechanic.pk,
            'description': 'Updated repair description',
            'internal_notes': '',
            'mileage_in': '100',
        })

        self.assertRedirects(response, reverse('repair_order_detail', args=[self.order.pk]))
        entry = AuditLog.objects.get(action='repair_order_updated', repair_order=self.order)
        self.assertEqual(entry.actor, admin)
        self.assertEqual(entry.details['assignment'], {'from_user_id': None, 'to_user_id': mechanic.pk})
        self.assertIn('mileage_in', entry.details['changed_fields'])

    def test_status_review_is_post_only_and_rejections_are_audited(self):
        admin = User.objects.create_user(username='status-audit-admin', password='test-password', is_staff=True)
        self.order.pending_status = 'waiting'
        self.order.save(update_fields=['pending_status'])
        self.client.force_login(admin)
        url = reverse('repair_order_status_review', args=[self.order.pk, 'reject'])

        get_response = self.client.get(url)

        self.assertEqual(get_response.status_code, 405)
        self.order.refresh_from_db()
        self.assertEqual(self.order.pending_status, 'waiting')

        post_response = self.client.post(url)

        self.assertRedirects(post_response, reverse('dashboard'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.pending_status, '')
        entry = AuditLog.objects.get(action='repair_status_proposal_rejected', repair_order=self.order)
        self.assertEqual(entry.actor, admin)
        self.assertEqual(entry.details, {'proposed_status': 'waiting'})

    def test_part_usage_records_stock_audit(self):
        admin = User.objects.create_user(username='stockauditadmin', password='test-password', is_staff=True)
        self.order.approved = True
        self.order.save(update_fields=['approved'])
        self.client.force_login(admin)

        response = self.client.post(reverse('add_parts_line', args=[self.order.pk]), {
            'part': self.part.pk,
            'quantity': '2',
        })

        self.assertRedirects(response, reverse('repair_order_detail', args=[self.order.pk]))
        line = self.order.parts_lines.get()
        entry = AuditLog.objects.get(action='inventory_stock_used', object_id=line.pk)
        self.assertEqual(entry.actor, admin)
        self.assertEqual(entry.repair_order, self.order)
        self.assertEqual(entry.details['quantity'], 2)
        self.assertEqual(entry.details['stock_before'], 10)
        self.assertEqual(entry.details['stock_after'], 8)

    def test_part_create_and_inventory_edit_are_audited(self):
        admin = User.objects.create_user(username='partauditadmin', password='test-password', is_staff=True)
        self.client.force_login(admin)
        part_data = {
            'name': 'Spark plug',
            'part_number': 'SP-1',
            'description': '',
            'cost_price': '40.00',
            'sell_price': '65.00',
            'stock_qty': '4',
            'reorder_level': '2',
            'supplier': 'Workshop supply',
        }

        create_response = self.client.post(reverse('part_create'), part_data)

        self.assertRedirects(create_response, reverse('parts_list'))
        part = Part.objects.get(part_number='SP-1')
        created_entry = AuditLog.objects.get(action='part_created', object_id=part.pk)
        self.assertEqual(created_entry.actor, admin)
        self.assertEqual(created_entry.details['stock_qty'], 4)

        part_data['stock_qty'] = '6'
        part_data['sell_price'] = '70.00'
        update_response = self.client.post(reverse('part_edit', args=[part.pk]), part_data)

        self.assertRedirects(update_response, reverse('parts_list'))
        updated_entry = AuditLog.objects.get(action='part_updated', object_id=part.pk)
        self.assertEqual(updated_entry.actor, admin)
        self.assertEqual(updated_entry.details['changes']['stock_qty'], {'from': '4', 'to': '6'})
        self.assertEqual(updated_entry.details['changes']['sell_price'], {'from': '65.00', 'to': '70.00'})

    def test_labor_logging_records_cost_and_actor(self):
        admin = User.objects.create_user(username='laborauditadmin', password='test-password', is_staff=True)
        self.order.approved = True
        self.order.save(update_fields=['approved'])
        self.client.force_login(admin)

        response = self.client.post(reverse('add_labor_line', args=[self.order.pk]), {
            'service_item': self.service.pk,
            'hours': '2',
            'notes': 'Brake inspection',
        })

        self.assertRedirects(response, reverse('repair_order_detail', args=[self.order.pk]))
        line = self.order.labor_lines.get()
        entry = AuditLog.objects.get(action='labor_logged', object_id=line.pk)
        self.assertEqual(entry.actor, admin)
        self.assertEqual(entry.repair_order, self.order)
        self.assertEqual(entry.details['hours'], '2.00')
        self.assertEqual(entry.details['rate'], '350.00')
        self.assertEqual(entry.details['line_total'], '700.00')


class EmployeeAuditTests(TestCase):
    def test_mechanic_creation_and_profile_edits_are_audited_without_contact_values(self):
        admin = User.objects.create_superuser(
            username='employeeauditadmin',
            email='employeeauditadmin@example.com',
            password='test-password',
        )
        UserProfile.objects.create(user=admin, role='admin')
        self.client.force_login(admin)
        employee_data = {
            'username': 'audited-mechanic',
            'email': 'audited-mechanic@example.com',
            'first_name': 'Audit',
            'last_name': 'Mechanic',
            'password1': 'Workshop-Mechanic-2026!',
            'password2': 'Workshop-Mechanic-2026!',
        }

        create_response = self.client.post(reverse('employee_create'), employee_data)

        self.assertRedirects(create_response, reverse('employee_list'))
        employee = User.objects.get(username='audited-mechanic')
        profile = UserProfile.objects.get(user=employee)
        created_entry = AuditLog.objects.get(action='employee_created', object_id=employee.pk)
        self.assertEqual(created_entry.actor, admin)
        self.assertEqual(created_entry.details, {'role': 'mechanic', 'is_active': True})

        employee_data = {
            'username': employee.username,
            'email': employee.email,
            'first_name': 'Updated',
            'last_name': employee.last_name,
            'role': 'mechanic',
            'is_active': 'on',
        }
        update_response = self.client.post(reverse('employee_edit', args=[profile.pk]), employee_data)

        self.assertRedirects(update_response, reverse('employee_list'))
        updated_entry = AuditLog.objects.get(action='employee_updated', object_id=employee.pk)
        self.assertEqual(updated_entry.actor, admin)
        self.assertEqual(updated_entry.details, {'changed_fields': ['first_name']})

        employee_data['first_name'] = 'Updated'
        employee_data['role'] = 'admin'
        role_response = self.client.post(reverse('employee_edit', args=[profile.pk]), employee_data)

        self.assertRedirects(role_response, reverse('employee_list'))
        profile.refresh_from_db()
        employee.refresh_from_db()
        self.assertEqual(profile.role, 'admin')
        self.assertTrue(employee.is_staff)
        access_entry = AuditLog.objects.get(action='employee_access_updated', object_id=employee.pk)
        self.assertEqual(access_entry.details['access_changes']['role'], {'from': 'mechanic', 'to': 'admin'})

        employee_data['is_active'] = ''
        deactivate_response = self.client.post(reverse('employee_edit', args=[profile.pk]), employee_data)

        self.assertRedirects(deactivate_response, reverse('employee_list'))
        employee.refresh_from_db()
        self.assertFalse(employee.is_active)
        status_entry = AuditLog.objects.filter(
            action='employee_access_updated',
            object_id=employee.pk,
        ).order_by('-pk').first()
        self.assertEqual(status_entry.details['access_changes']['is_active'], {'from': True, 'to': False})

    def test_admin_cannot_change_own_role_or_deactivate_self(self):
        admin = User.objects.create_user(username='selfmanageadmin', password='test-password', is_staff=True)
        profile = UserProfile.objects.create(user=admin, role='admin')
        self.client.force_login(admin)

        response = self.client.post(reverse('employee_edit', args=[profile.pk]), {
            'username': admin.username,
            'email': admin.email,
            'first_name': admin.first_name,
            'last_name': admin.last_name,
            'role': 'mechanic',
            'is_active': '',
        })

        self.assertEqual(response.status_code, 200)
        profile.refresh_from_db()
        admin.refresh_from_db()
        self.assertEqual(profile.role, 'admin')
        self.assertTrue(admin.is_active)
        self.assertTrue(admin.is_staff)

    def test_staff_admin_cannot_modify_another_admin_account(self):
        admin = User.objects.create_user(username='nonroot-admin', password='test-password', is_staff=True)
        UserProfile.objects.create(user=admin, role='admin')
        other_admin = User.objects.create_user(username='protected-admin', password='test-password', is_staff=True)
        protected_profile = UserProfile.objects.create(user=other_admin, role='admin')
        self.client.force_login(admin)

        response = self.client.post(reverse('employee_edit', args=[protected_profile.pk]), {
            'username': other_admin.username,
            'email': other_admin.email,
            'first_name': other_admin.first_name,
            'last_name': other_admin.last_name,
            'role': 'mechanic',
            'is_active': '',
        })

        self.assertRedirects(response, reverse('dashboard'))
        protected_profile.refresh_from_db()
        other_admin.refresh_from_db()
        self.assertEqual(protected_profile.role, 'admin')
        self.assertTrue(other_admin.is_active)

    def test_superuser_cannot_remove_the_last_active_admin(self):
        root = User.objects.create_superuser(
            username='root-without-profile',
            email='root-without-profile@example.com',
            password='Root-Password-929!',
        )
        admin = User.objects.create_user(username='last-active-admin', password='test-password', is_staff=True)
        profile = UserProfile.objects.create(user=admin, role='admin')
        self.client.force_login(root)

        response = self.client.post(reverse('employee_edit', args=[profile.pk]), {
            'username': admin.username,
            'email': admin.email,
            'first_name': admin.first_name,
            'last_name': admin.last_name,
            'role': 'mechanic',
            'is_active': '',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'At least one active admin account must remain.')
        profile.refresh_from_db()
        admin.refresh_from_db()
        self.assertEqual(profile.role, 'admin')
        self.assertTrue(admin.is_active)


class ServiceCatalogAuditTests(TestCase):
    def test_service_creation_and_rate_changes_are_audited(self):
        admin = User.objects.create_user(username='serviceauditadmin', password='test-password', is_staff=True)
        self.client.force_login(admin)
        service_data = {
            'name': 'Brake inspection',
            'description': '',
            'labor_hours': '1.50',
            'labor_rate': '300.00',
        }

        create_response = self.client.post(reverse('service_create'), service_data)

        self.assertRedirects(create_response, reverse('service_list'))
        service = ServiceItem.objects.get(name='Brake inspection')
        created_entry = AuditLog.objects.get(action='service_created', object_id=service.pk)
        self.assertEqual(created_entry.actor, admin)
        self.assertEqual(created_entry.details['labor_rate'], '300.00')

        service_data['labor_rate'] = '325.00'
        update_response = self.client.post(reverse('service_edit', args=[service.pk]), service_data)

        self.assertRedirects(update_response, reverse('service_list'))
        updated_entry = AuditLog.objects.get(action='service_updated', object_id=service.pk)
        self.assertEqual(updated_entry.actor, admin)
        self.assertEqual(
            updated_entry.details['changes']['labor_rate'],
            {'from': '300.00', 'to': '325.00'},
        )


class AuditLogIntegrityTests(TestCase):
    def test_audit_entries_cannot_be_updated_or_deleted(self):
        actor = User.objects.create_user(username='immutable-audit-actor', password='test-password')
        entry = AuditLog.objects.create(
            actor=actor,
            action='test_action',
            object_type='Customer',
            object_id=123,
            details={'field': 'phone'},
        )

        entry.action = 'rewritten_action'
        with self.assertRaises(TypeError):
            entry.save()
        with self.assertRaises(TypeError):
            AuditLog.objects.filter(pk=entry.pk).update(action='rewritten_action')
        with self.assertRaises(TypeError):
            entry.delete()
        with self.assertRaises(TypeError):
            AuditLog.objects.filter(pk=entry.pk).delete()

        entry.refresh_from_db()
        self.assertEqual(entry.action, 'test_action')

    def test_audit_log_admin_is_read_only(self):
        admin = User.objects.create_superuser(
            username='audit-integrity-admin',
            email='audit-integrity-admin@example.com',
            password='Admin-Password-921!',
        )
        entry = AuditLog.objects.create(
            actor=admin,
            action='admin_test_action',
            object_type='Customer',
            object_id=321,
        )
        self.client.force_login(admin)

        changelist = self.client.get(reverse('admin:workshop_auditlog_changelist'))
        change_url = reverse('admin:workshop_auditlog_change', args=[entry.pk])
        change_page = self.client.get(change_url)

        self.assertEqual(changelist.status_code, 200)
        self.assertContains(changelist, 'admin_test_action')
        self.assertEqual(change_page.status_code, 200)
        self.assertNotContains(change_page, 'name="_save"')
        update_response = self.client.post(change_url, {'action': 'rewritten_action'})
        self.assertEqual(update_response.status_code, 403)


class ReportPageTests(TestCase):
    def test_admin_report_page_loads(self):
        user = User.objects.create_user(username='adminreport', email='admin@example.com', password='Password123!')
        user.is_staff = True
        user.save()
        UserProfile.objects.create(user=user, role='admin', is_verified=True)

        self.client.force_login(user)
        response = self.client.get(reverse('report'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Performance Overview')

    def test_date_filtered_report_uses_real_payments_and_operational_records(self):
        admin = User.objects.create_user(username='reportdata', password='Password123!', is_staff=True)
        UserProfile.objects.create(user=admin, role='admin', is_verified=True)
        customer = Customer.objects.create(first_name='Report', last_name='Customer', email='report-data@example.com')
        vehicle = Vehicle.objects.create(customer=customer, make='Toyota', model='Yaris', year=2020)
        mechanic = User.objects.create_user(username='reportmechanic', first_name='Report', last_name='Mechanic')
        UserProfile.objects.create(user=mechanic, role='mechanic')
        order = RepairOrder.objects.create(vehicle=vehicle, assigned_tech=mechanic, description='Period report repair')
        invoice = Invoice.objects.create(
            repair_order=order,
            due_date=timezone.localdate() + timedelta(days=1),
            service_amount=Decimal('100.00'),
            tax_rate=Decimal('15.00'),
        )
        payment = InvoicePayment.objects.create(
            invoice=invoice,
            amount=Decimal('25.00'),
            payment_method='cash',
            received_at=timezone.now().replace(hour=12, minute=0, second=0, microsecond=0),
        )
        invoice.refresh_payment_status()
        part = Part.objects.create(name='Report part', part_number='RP-1', cost_price=10, sell_price=20, stock_qty=1, reorder_level=3)
        PartsLine.objects.create(repair_order=order, part=part, quantity=2, unit_price=20)
        service = ServiceItem.objects.create(name='Report service', labor_hours=2, labor_rate=100)
        LaborLine.objects.create(repair_order=order, service_item=service, hours=2, rate=100)
        Appointment.objects.create(
            customer=customer,
            vehicle=vehicle,
            date_time=timezone.now(),
            service_desc='Report appointment',
        )

        self.client.force_login(admin)
        payment_date = timezone.localtime(payment.received_at).date().isoformat()
        response = self.client.get(reverse('report'), {'start_date': payment_date, 'end_date': payment_date})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_revenue'], Decimal('25.00'))
        self.assertEqual(response.context['total_invoiced'], Decimal('115.00'))
        self.assertEqual(response.context['outstanding_balance'], Decimal('90.00'))
        self.assertEqual(response.context['parts_consumption'][0]['quantity'], 2)
        self.assertEqual(response.context['mechanic_workload'][0].job_count, 1)
        self.assertEqual(response.context['service_demand'][0]['jobs'], 1)
        self.assertEqual(response.context['appointment_breakdown'][0]['total'], 1)


class AuthUrlTests(TestCase):
    def test_password_reset_routes_exist(self):
        self.assertEqual(reverse('forgot_password'), '/forgot-password/')
        self.assertEqual(reverse('reset_password'), '/reset-password/')

    def test_logout_uses_post_and_clears_authenticated_session(self):
        user = User.objects.create_user(username='logout-user', password='Logout-Password-817!')
        self.client.force_login(user)

        get_response = self.client.get(reverse('logout'))
        self.assertEqual(get_response.status_code, 405)
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

        post_response = self.client.post(reverse('logout'))
        self.assertRedirects(post_response, reverse('login'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_login_rejects_external_redirect_targets(self):
        User.objects.create_user(
            username='redirect-user',
            password='Redirect-Password-817!',
        )

        external_redirect = self.client.post(reverse('login'), {
            'username': 'redirect-user',
            'password': 'Redirect-Password-817!',
            'next': 'https://attacker.example/collect',
        })

        self.assertRedirects(external_redirect, reverse('dashboard'))

        self.client.logout()
        local_redirect = self.client.post(reverse('login'), {
            'username': 'redirect-user',
            'password': 'Redirect-Password-817!',
            'next': '/repairs/',
        })

        self.assertRedirects(local_redirect, '/repairs/')

    @override_settings(PUBLIC_BASE_URL='https://workshop.example/base')
    @patch('workshop.auth_utils.send_mail')
    def test_auth_emails_use_configured_public_origin(self, send_mail_mock):
        user = User.objects.create_user(
            username='public-url-user',
            email='public-url@example.com',
            password='Public-Url-Password-841!',
        )
        request = RequestFactory().get('/', HTTP_HOST='attacker.example')

        send_verification_email(request, user)
        verification_message = send_mail_mock.call_args.args[1]
        self.assertIn('https://workshop.example/base/verify-email/?token=', verification_message)
        self.assertNotIn('attacker.example', verification_message)

        send_password_reset_email(request, user)
        reset_message = send_mail_mock.call_args.args[1]
        self.assertIn('https://workshop.example/base/reset-password/?token=', reset_message)
        self.assertNotIn('attacker.example', reset_message)


class PasswordResetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='reset-account',
            email='reset-account@example.com',
            password='Old-Password-742!',
        )
        self.raw_token, self.token = PasswordResetToken.generate_for_user(self.user)

    def test_new_reset_link_invalidates_previous_tokens(self):
        new_raw_token, new_token = PasswordResetToken.generate_for_user(self.user)

        self.token.refresh_from_db()
        self.assertTrue(self.token.used)
        self.assertIsNone(PasswordResetToken.validate_token(self.raw_token))
        self.assertEqual(PasswordResetToken.validate_token(new_raw_token), new_token)

    def test_forgot_password_response_does_not_reveal_account_or_delivery_state(self):
        generic_message = 'If an account with that email exists, a reset link has been sent.'

        with (
            patch('workshop.views.send_password_reset_email', side_effect=RuntimeError('mail failure')) as send_email,
            patch('workshop.views.logger.exception') as log_failure,
        ):
            existing_account_response = self.client.post(
                reverse('forgot_password'),
                {'email': self.user.email},
                follow=True,
            )
            unknown_account_response = self.client.post(
                reverse('forgot_password'),
                {'email': 'unknown@example.com'},
                follow=True,
            )

        self.assertContains(existing_account_response, generic_message)
        self.assertContains(unknown_account_response, generic_message)
        self.assertNotContains(existing_account_response, 'Failed to send reset email')
        send_email.assert_called_once()
        log_failure.assert_called_once_with('Password reset email delivery failed.')

    def test_reset_requests_are_limited_without_changing_public_response(self):
        generic_message = 'If an account with that email exists, a reset link has been sent.'

        def issue_token(request, user, ttl_minutes):
            return PasswordResetToken.generate_for_user(user, ttl_minutes=ttl_minutes)[1]

        with patch('workshop.views.send_password_reset_email', side_effect=issue_token) as send_email:
            responses = [
                self.client.post(
                    reverse('forgot_password'),
                    {'email': self.user.email},
                    follow=True,
                )
                for _ in range(3)
            ]

        self.assertEqual(send_email.call_count, 2)
        for response in responses:
            self.assertContains(response, generic_message)

    def test_reset_enforces_password_policy_without_consuming_token(self):
        weak_password = 'short'
        response = self.client.post(reverse('reset_password'), {
            'token': self.raw_token,
            'password': weak_password,
            'password_confirm': weak_password,
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'too short')
        self.token.refresh_from_db()
        self.user.refresh_from_db()
        self.assertFalse(self.token.used)
        self.assertTrue(self.user.check_password('Old-Password-742!'))

        strong_password = 'Fresh-Strong-Password-839!'
        successful_response = self.client.post(reverse('reset_password'), {
            'token': self.raw_token,
            'password': strong_password,
            'password_confirm': strong_password,
        })

        self.assertRedirects(successful_response, reverse('login'))
        self.token.refresh_from_db()
        self.user.refresh_from_db()
        self.assertTrue(self.token.used)
        self.assertTrue(self.user.check_password(strong_password))

        reused_response = self.client.post(reverse('reset_password'), {
            'token': self.raw_token,
            'password': 'Another-Strong-Password-421!',
            'password_confirm': 'Another-Strong-Password-421!',
        })
        self.assertRedirects(reused_response, reverse('login'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(strong_password))


class WorkflowAdminGuardTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='workflow-admin',
            email='workflow-admin@example.com',
            password='Admin-Password-942!',
        )
        customer = Customer.objects.create(
            first_name='Admin',
            last_name='Customer',
            email='admin-customer@example.com',
        )
        self.vehicle = Vehicle.objects.create(
            customer=customer,
            make='Toyota',
            model='Corolla',
            year=2022,
        )
        self.order = RepairOrder.objects.create(
            vehicle=self.vehicle,
            description='Brake inspection',
        )
        self.client.force_login(self.admin)

    def test_repair_order_admin_cannot_edit_workflow_or_line_items(self):
        response = self.client.get(reverse('admin:workshop_repairorder_change', args=[self.order.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="status"')
        self.assertNotContains(response, 'name="approved"')
        self.assertEqual(
            self.client.get(reverse('admin:workshop_repairorder_add')).status_code,
            403,
        )

    def test_appointment_admin_cannot_edit_or_create_workflow_records(self):
        appointment = Appointment.objects.create(
            customer=self.order.vehicle.customer,
            vehicle=self.vehicle,
            date_time='2030-05-20T10:30:00Z',
            service_desc='Annual service',
        )

        response = self.client.get(reverse('admin:workshop_appointment_change', args=[appointment.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="assignment_status"')
        self.assertEqual(
            self.client.get(reverse('admin:workshop_appointment_add')).status_code,
            403,
        )

class AppointmentDeleteTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('delcust', 'delcust@example.com', 'pw-12345-xyz')
        UserProfile.objects.create(user=self.user, role='customer', is_verified=True)
        self.customer = Customer.objects.create(first_name='Del', last_name='Cust', email='delcust@example.com', phone='1', address='x')
        self.vehicle = Vehicle.objects.create(customer=self.customer, make='Toyota', model='Corolla', year=2020)
        self.other_user = User.objects.create_user('other', 'other@example.com', 'pw-12345-xyz')
        UserProfile.objects.create(user=self.other_user, role='customer', is_verified=True)
        self.other_customer = Customer.objects.create(first_name='Oth', last_name='Er', email='other@example.com', phone='2', address='y')

    def _request(self, customer=None, vehicle=None):
        vehicle = vehicle or self.vehicle
        order = RepairOrder.objects.create(vehicle=vehicle, description='Duplicate', status='pending')
        appt = Appointment.objects.create(
            customer=customer or self.customer, vehicle=vehicle, repair_order=order,
            date_time=timezone.now() + timedelta(days=1), service_desc='Duplicate',
        )
        return appt, order

    def test_customer_can_delete_duplicate_request(self):
        appt, order = self._request()
        self.client.force_login(self.user)
        page = self.client.get(reverse('appointment_list'))
        self.assertContains(page, reverse('appointment_delete', args=[appt.pk]))
        response = self.client.post(reverse('appointment_delete', args=[appt.pk]))
        self.assertRedirects(response, reverse('appointment_list'))
        self.assertFalse(Appointment.objects.filter(pk=appt.pk).exists())
        order.refresh_from_db()
        self.assertEqual(order.status, 'cancelled')
        self.assertTrue(AuditLog.objects.filter(action='appointment_deleted', object_id=appt.pk).exists())

    def test_cannot_delete_once_work_has_started(self):
        appt, order = self._request()
        add_estimate_line(order)
        self.client.force_login(self.user)
        page = self.client.get(reverse('appointment_list'))
        self.assertNotContains(page, reverse('appointment_delete', args=[appt.pk]))
        self.client.post(reverse('appointment_delete', args=[appt.pk]))
        self.assertTrue(Appointment.objects.filter(pk=appt.pk).exists())
        order.refresh_from_db()
        self.assertEqual(order.status, 'pending')

    def test_customer_cannot_delete_someone_elses_request(self):
        other_vehicle = Vehicle.objects.create(customer=self.other_customer, make='Ford', model='Fiesta', year=2018)
        appt, _ = self._request(customer=self.other_customer, vehicle=other_vehicle)
        self.client.force_login(self.user)
        response = self.client.post(reverse('appointment_delete', args=[appt.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Appointment.objects.filter(pk=appt.pk).exists())

    def test_delete_requires_post(self):
        appt, _ = self._request()
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('appointment_delete', args=[appt.pk])).status_code, 405)


class RegistrationTests(TestCase):
    @patch('workshop.views.send_verification_email', side_effect=RuntimeError('smtp down'))
    def test_registration_survives_email_failure_and_unverified_user_can_resend(self, mocked_send):
        self.client.post(reverse('register'), {
            'email': 'mailfail@example.com',
            'first_name': 'Mail',
            'last_name': 'Fail',
            'password1': 'A-strong-pass-123',
            'password2': 'A-strong-pass-123',
        })
        self.assertTrue(User.objects.filter(email='mailfail@example.com').exists())

        mocked_send.side_effect = None
        response = self.client.post(reverse('login'), {'username': 'mailfail@example.com', 'password': 'A-strong-pass-123'})
        self.assertContains(response, 'Resend verification email')

        mocked_send.reset_mock()
        response = self.client.post(reverse('login'), {'resend_verification': '1'})
        self.assertRedirects(response, reverse('login'))
        mocked_send.assert_called_once()

    @patch('workshop.views.send_verification_email')
    def test_resend_without_pending_login_sends_nothing(self, mocked_send):
        response = self.client.post(reverse('login'), {'resend_verification': '1'})
        self.assertRedirects(response, reverse('login'))
        mocked_send.assert_not_called()

    @patch('workshop.views.send_verification_email')
    def test_invalid_registration_saves_nothing(self, send_verification_email):
        base = {
            'email': 'bad@example.com',
            'first_name': 'Bad',
            'last_name': 'Customer',
            'password1': 'A-strong-pass-123',
            'password2': 'A-strong-pass-123',
        }
        for override in ({'password2': 'different-pass-456'}, {'email': 'not-an-email'}, {'password1': '123', 'password2': '123'}):
            response = self.client.post(reverse('register'), {**base, **override})
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.context['form'].is_valid())

        self.assertFalse(User.objects.filter(email='bad@example.com').exists())
        self.assertFalse(Customer.objects.filter(email__in=['bad@example.com', 'not-an-email']).exists())
        send_verification_email.assert_not_called()

    def test_register_form_has_no_username_or_role_and_email_follows_last_name(self):
        page = self.client.get(reverse('register'))
        self.assertNotContains(page, 'id_username')
        self.assertNotContains(page, 'id_role')
        self.assertNotContains(page, 'Choose a role')
        html = page.content.decode()
        self.assertLess(html.index('id_last_name'), html.index('id_email'))
        self.assertLess(html.index('id_email'), html.index('id_password1'))

    @patch('workshop.views.send_verification_email')
    def test_usernames_are_unique_and_customer_can_login_with_email(self, _send):
        for first in ('A', 'B'):
            self.client.post(reverse('register'), {
                'email': f'same{first}@example.com' if False else 'same@example.com' if first == 'A' else 'same@other.com',
                'first_name': first, 'last_name': 'X',
                'password1': 'A-strong-pass-123', 'password2': 'A-strong-pass-123',
            })
        self.assertEqual(sorted(User.objects.filter(email__in=['same@example.com', 'same@other.com']).values_list('username', flat=True)), ['same', 'same2'])
        user = User.objects.get(email='same@example.com')
        user.userprofile.is_verified = True
        user.userprofile.save()
        Customer.objects.filter(email=user.email).update(phone='0712345678', address='1 Main St')
        response = self.client.post(reverse('login'), {'username': 'SAME@example.com', 'password': 'A-strong-pass-123'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

    def test_register_page_has_show_password_toggle(self):
        page = self.client.get(reverse('register'))
        self.assertContains(page, 'pw-toggle')

    @patch('workshop.views.send_verification_email')
    def test_customer_can_register_without_contact_details(self, send_verification_email):
        page = self.client.get(reverse('register'))
        self.assertNotContains(page, 'Phone')
        self.assertNotContains(page, 'Address')

        response = self.client.post(reverse('register'), {
            'email': 'newcustomer@example.com',
            'first_name': 'New',
            'last_name': 'Customer',
            'password1': 'A-strong-pass-123',
            'password2': 'A-strong-pass-123',
        })

        self.assertRedirects(response, reverse('login'))
        user = User.objects.get(email='newcustomer@example.com')
        self.assertEqual(user.username, 'newcustomer')
        self.assertEqual(user.email, 'newcustomer@example.com')
        self.assertEqual(user.userprofile.role, 'customer')
        customer = Customer.objects.get(email=user.email)
        self.assertEqual(customer.phone, '')
        self.assertEqual(customer.address, '')
        registration_audit = AuditLog.objects.get(action='account_registered', object_id=user.pk)
        self.assertEqual(registration_audit.actor, user)
        self.assertEqual(registration_audit.details, {
            'role': 'customer',
            'is_active': True,
            'is_verified': False,
        })
        send_verification_email.assert_called_once()

    def test_public_api_registration_cannot_create_staff_accounts(self):
        response = self.client.post(
            reverse('api_register'),
            data=json.dumps({
                'username': 'apiadmin',
                'email': 'apiadmin@example.com',
                'password': 'Api-Strong-Password-812!',
                'role': 'admin',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username='apiadmin').exists())

    def test_public_api_registration_enforces_password_policy(self):
        response = self.client.post(
            reverse('api_register'),
            data=json.dumps({
                'username': 'apiweak',
                'email': 'apiweak@example.com',
                'password': 'short',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())
        self.assertFalse(User.objects.filter(username='apiweak').exists())

    @patch('workshop.views.send_verification_email')
    def test_public_api_registration_creates_only_customer_accounts(self, send_verification_email):
        response = self.client.post(
            reverse('api_register'),
            data=json.dumps({
                'username': 'apicustomer',
                'email': 'apicustomer@example.com',
                'password': 'Api-Customer-Password-812!',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201)
        user = User.objects.get(username='apicustomer')
        self.assertFalse(user.is_staff)
        self.assertEqual(user.userprofile.role, 'customer')
        registration_audit = AuditLog.objects.get(action='account_registered', object_id=user.pk)
        self.assertEqual(registration_audit.details['role'], 'customer')
        send_verification_email.assert_called_once()

    def test_email_verification_is_audited(self):
        user = User.objects.create_user(
            username='verification-audit',
            email='verification-audit@example.com',
            password='Verified-Password-815!',
        )
        profile = UserProfile.objects.create(user=user, role='customer', is_verified=False)
        raw_token, _ = EmailVerificationToken.generate_for_user(user)

        response = self.client.get(reverse('verify_email'), {'token': raw_token})

        self.assertEqual(response.status_code, 200)
        profile.refresh_from_db()
        self.assertTrue(profile.is_verified)
        entry = AuditLog.objects.get(action='account_email_verified', object_id=user.pk)
        self.assertEqual(entry.actor, user)
        self.assertEqual(entry.details, {'is_verified': True})

    def test_resend_verification_response_does_not_reveal_account_state(self):
        unverified_user = User.objects.create_user(
            username='unverified-api',
            email='unverified-api@example.com',
            password='Verified-Password-815!',
        )
        UserProfile.objects.create(user=unverified_user, role='customer', is_verified=False)
        verified_user = User.objects.create_user(
            username='verified-api',
            email='verified-api@example.com',
            password='Verified-Password-815!',
        )
        UserProfile.objects.create(user=verified_user, role='customer', is_verified=True)

        with (
            patch('workshop.views.can_resend_verification', return_value=True),
            patch('workshop.views.send_verification_email', side_effect=RuntimeError('mail failure')),
            patch('workshop.views.logger.exception') as log_failure,
        ):
            responses = [
                self.client.post(
                    reverse('resend_verification'),
                    data=json.dumps({'email': email}),
                    content_type='application/json',
                )
                for email in [
                    'unknown-verification@example.com',
                    verified_user.email,
                    unverified_user.email,
                ]
            ]

        with patch('workshop.views.can_resend_verification', return_value=False):
            throttled_response = self.client.post(
                reverse('resend_verification'),
                data=json.dumps({'email': unverified_user.email}),
                content_type='application/json',
            )

        expected = {
            'status': 'ok',
            'message': 'If the account can be verified, instructions will be sent.',
        }
        for response in [*responses, throttled_response]:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), expected)
        log_failure.assert_called_once_with('Verification email delivery failed.')


class LegalAndErrorPageTests(TestCase):
    def test_privacy_policy_page_loads(self):
        response = self.client.get(reverse('privacy_policy'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Privacy Policy')

    def test_terms_and_conditions_page_loads(self):
        response = self.client.get(reverse('terms_and_conditions'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Terms and Conditions')

    def test_missing_page_uses_custom_404_template(self):
        response = self.client.get('/definitely-missing-page/')
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'Page not found', status_code=404)


class ReportExportTests(TestCase):
    def test_admin_can_download_report_spreadsheet(self):
        user = User.objects.create_user(username='reportexport', email='export@example.com', password='Password123!')
        user.is_staff = True
        user.save()
        UserProfile.objects.create(user=user, role='admin', is_verified=True)

        self.client.force_login(user)
        response = self.client.get(reverse('report_export'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('Month', response.content.decode('utf-8'))

    def test_export_rejects_invalid_date_ranges(self):
        user = User.objects.create_user(username='invalidreportexport', password='Password123!', is_staff=True)
        UserProfile.objects.create(user=user, role='admin', is_verified=True)
        self.client.force_login(user)

        response = self.client.get(reverse('report_export'), {'start_date': 'not-a-date'})

        self.assertEqual(response.status_code, 400)


class CustomerRepairOrderSummaryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='customer',
            email='customer@example.com',
            password='test-password',
        )
        UserProfile.objects.create(user=self.user, role='customer')
        self.customer = Customer.objects.create(
            first_name='Casey',
            last_name='Customer',
            email=self.user.email,
            phone='0712345678',
            address='1 Workshop Road',
        )
        vehicle = Vehicle.objects.create(
            customer=self.customer,
            make='Toyota',
            model='Corolla',
            year=2020,
        )
        self.order = RepairOrder.objects.create(
            vehicle=vehicle,
            description='Brake service',
        )
        self.invoice = Invoice.objects.create(
            repair_order=self.order,
            due_date=timezone.localdate() + timedelta(days=1),
            service_amount=Decimal('100.00'),
        )
        self.client.force_login(self.user)

    def test_customer_order_summary_shows_invoice_with_two_decimal_total(self):
        response = self.client.get(reverse('repair_order_detail', args=[self.order.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Payment status')
        self.assertContains(response, 'R 115.00')
        self.assertContains(response, 'View invoice')

    def test_invoice_list_uses_annotated_payments_for_amount_and_balance(self):
        InvoicePayment.objects.create(
            invoice=self.invoice,
            amount=Decimal('35.00'),
            payment_method='cash',
        )

        response = self.client.get(reverse('invoice_list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['invoices'][0].report_paid_amount, Decimal('35.00'))
        self.assertContains(response, 'R 35.00')
        self.assertContains(response, 'R 80.00')

    def test_invoice_detail_displays_amounts_as_two_decimal_rand_values(self):
        response = self.client.get(reverse('invoice_detail', args=[self.invoice.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'R 115.00')
        self.assertContains(response, 'R 0.00')
        self.assertContains(response, 'R 15.00')

    @patch('workshop.auth_utils.send_mail')
    def test_invoice_ready_email_formats_balance_as_rand(self, send_mail_mock):
        request = RequestFactory().get('/')

        send_invoice_ready_email(request, self.invoice)

        message = send_mail_mock.call_args.args[1]
        self.assertIn('Balance Due: R 115.00', message)

    def test_customer_cannot_view_another_customers_order(self):
        other_customer = Customer.objects.create(
            first_name='Other',
            last_name='Customer',
            email='other@example.com',
        )
        other_vehicle = Vehicle.objects.create(
            customer=other_customer,
            make='Honda',
            model='Civic',
            year=2021,
        )
        other_order = RepairOrder.objects.create(
            vehicle=other_vehicle,
            description='Inspection',
        )

        response = self.client.get(reverse('repair_order_detail', args=[other_order.pk]))

        self.assertEqual(response.status_code, 404)

    def test_customer_cannot_view_internal_repair_notes(self):
        self.order.internal_notes = 'INTERNAL: supplier dispute and staff-only details'
        self.order.save(update_fields=['internal_notes'])

        response = self.client.get(reverse('repair_order_detail', args=[self.order.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'supplier dispute')
        self.assertNotContains(response, 'staff-only details')

    def test_customer_can_submit_payment_method_for_own_invoice(self):
        payment_url = reverse('invoice_pay', args=[self.invoice.pk])
        invoice_page = self.client.get(reverse('invoice_detail', args=[self.invoice.pk]))
        page = self.client.get(payment_url)

        self.assertContains(invoice_page, 'Pay invoice')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Choose method')
        self.assertContains(page, 'does not process a transaction')

        response = self.client.post(payment_url, {'payment_method': 'card'})

        self.assertRedirects(response, reverse('invoice_detail', args=[self.invoice.pk]))
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.payment_status, 'paid')
        self.assertEqual(self.invoice.payment_method, 'card')
        self.assertEqual(self.invoice.paid_amount, Decimal('115.00'))
        self.assertEqual(self.invoice.balance_due, Decimal('0.00'))
        payment = InvoicePayment.objects.get(invoice=self.invoice)
        self.assertEqual(payment.amount, Decimal('115.00'))
        self.assertEqual(payment.recorded_by, self.user)

    def test_customer_cannot_submit_payment_for_another_customers_invoice(self):
        other_customer = Customer.objects.create(
            first_name='Other',
            last_name='Customer',
            email='other-payment@example.com',
        )
        other_vehicle = Vehicle.objects.create(
            customer=other_customer,
            make='Honda',
            model='Civic',
            year=2021,
        )
        other_order = RepairOrder.objects.create(vehicle=other_vehicle, description='Inspection')
        other_invoice = Invoice.objects.create(
            repair_order=other_order,
            due_date=timezone.localdate() + timedelta(days=1),
            service_amount=Decimal('100.00'),
        )

        response = self.client.post(
            reverse('invoice_pay', args=[other_invoice.pk]),
            {'payment_method': 'eft'},
        )

        self.assertRedirects(response, reverse('dashboard'))
        self.assertFalse(InvoicePayment.objects.filter(invoice=other_invoice).exists())

    def test_paid_invoice_is_visible_to_admin_and_mechanic(self):
        admin = User.objects.create_user(username='billingadmin', password='test-password')
        UserProfile.objects.create(user=admin, role='admin')
        self.client.force_login(admin)
        partial_payment = self.client.post(reverse('invoice_pay', args=[self.invoice.pk]), {
            'amount': '40.00',
            'payment_method': 'cash',
            'reference': 'cash-001',
            'notes': '',
        })
        self.assertRedirects(partial_payment, reverse('invoice_detail', args=[self.invoice.pk]))
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.payment_status, 'partial')
        self.assertEqual(self.invoice.paid_amount, Decimal('40.00'))
        self.assertEqual(self.invoice.balance_due, Decimal('75.00'))
        first_payment = InvoicePayment.objects.get(reference='cash-001')
        payment_audit = AuditLog.objects.get(action='invoice_payment_recorded', object_id=first_payment.pk)
        self.assertEqual(payment_audit.actor, admin)
        self.assertEqual(payment_audit.repair_order, self.order)
        self.assertEqual(payment_audit.details['invoice_id'], self.invoice.pk)
        self.assertEqual(payment_audit.details['balance_due'], '75.00')
        self.assertEqual(payment_audit.details['payment_status'], 'partial')

        overpayment = self.client.post(reverse('invoice_pay', args=[self.invoice.pk]), {
            'amount': '76.00',
            'payment_method': 'eft',
            'reference': 'eft-001',
            'notes': '',
        })
        self.assertEqual(overpayment.status_code, 200)
        self.assertContains(overpayment, 'cannot exceed the outstanding balance')
        self.assertEqual(InvoicePayment.objects.filter(invoice=self.invoice).count(), 1)

        final_payment = self.client.post(reverse('invoice_pay', args=[self.invoice.pk]), {
            'amount': '75.00',
            'payment_method': 'eft',
            'reference': 'eft-002',
            'notes': '',
        })
        self.assertRedirects(final_payment, reverse('invoice_detail', args=[self.invoice.pk]))
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.payment_status, 'paid')
        self.assertEqual(self.invoice.paid_amount, Decimal('115.00'))
        self.assertEqual(self.invoice.balance_due, Decimal('0.00'))
        self.assertEqual(InvoicePayment.objects.filter(invoice=self.invoice).count(), 2)

        duplicate_payment = self.client.post(reverse('invoice_pay', args=[self.invoice.pk]), {
            'amount': '1.00', 'payment_method': 'cash', 'reference': 'extra',
        })
        self.assertRedirects(duplicate_payment, reverse('invoice_detail', args=[self.invoice.pk]))
        self.assertEqual(InvoicePayment.objects.filter(invoice=self.invoice).count(), 2)

        self.client.force_login(self.user)
        customer_order_response = self.client.get(reverse('repair_order_detail', args=[self.order.pk]))
        self.assertContains(customer_order_response, 'Paid')
        customer_invoice_response = self.client.get(reverse('invoice_detail', args=[self.invoice.pk]))
        self.assertContains(customer_invoice_response, 'Invoice Paid')
        self.assertContains(customer_invoice_response, 'eft-002')

        for role in ('admin', 'mechanic'):
            staff_user = User.objects.create_user(
                username=role,
                email=f'{role}@example.com',
                password='test-password',
            )
            UserProfile.objects.create(user=staff_user, role=role)
            if role == 'mechanic':
                self.order.assigned_tech = staff_user
                self.order.save(update_fields=['assigned_tech'])
            self.client.force_login(staff_user)

            dashboard_response = self.client.get(reverse('dashboard'))
            self.assertEqual(dashboard_response.status_code, 200)
            self.assertEqual(dashboard_response.context['paid_invoices'], 1)
            self.assertContains(dashboard_response, 'Paid invoices')

            invoice_list_response = self.client.get(reverse('invoice_list'))
            self.assertContains(invoice_list_response, 'Paid')
            self.assertContains(invoice_list_response, f'#{self.invoice.pk}')

    def test_invoice_create_redirects_to_existing_invoice(self):
        admin = User.objects.create_user(username='invoiceadmin', password='test-password')
        UserProfile.objects.create(user=admin, role='admin')
        self.client.force_login(admin)

        response = self.client.get(reverse('invoice_create'), {'ro': self.order.pk})

        self.assertRedirects(response, reverse('invoice_detail', args=[self.invoice.pk]))

    def test_invoice_edits_record_financial_before_and_after_values(self):
        admin = User.objects.create_user(username='invoiceeditadmin', password='test-password', is_staff=True)
        self.client.force_login(admin)
        old_due_date = self.invoice.due_date
        new_due_date = old_due_date + timedelta(days=14)

        response = self.client.post(reverse('invoice_edit', args=[self.invoice.pk]), {
            'repair_order': self.order.pk,
            'service_amount': '100.00',
            'issue_date': self.invoice.issue_date.strftime('%Y-%m-%d'),
            'due_date': new_due_date.isoformat(),
            'discount': '0.00',
            'tax_rate': '10.00',
            'notes': '',
        })

        self.assertRedirects(response, reverse('invoice_detail', args=[self.invoice.pk]))
        entry = AuditLog.objects.get(action='invoice_updated', object_id=self.invoice.pk)
        self.assertEqual(entry.actor, admin)
        self.assertEqual(entry.details['changes']['tax_rate'], {'from': '15.00', 'to': '10.00'})
        self.assertEqual(
            entry.details['changes']['due_date'],
            {'from': old_due_date.isoformat(), 'to': new_due_date.isoformat()},
        )


class CustomerProfileCompletionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='incomplete-customer',
            email='incomplete@example.com',
            password='test-password',
            first_name='Taylor',
            last_name='Customer',
        )
        UserProfile.objects.create(user=self.user, role='customer', is_verified=True)
        self.customer = Customer.objects.create(
            first_name='Taylor',
            last_name='Customer',
            email=self.user.email,
        )

    def test_customer_login_requires_phone_and_address(self):
        response = self.client.post(
            reverse('login'),
            {'username': self.user.username, 'password': 'test-password'},
        )

        self.assertRedirects(response, reverse('customer_profile'))

    def test_customer_cannot_bypass_profile_completion(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('dashboard'))

        self.assertRedirects(response, reverse('customer_profile'))

    def test_updated_contact_details_are_visible_to_staff(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('customer_profile'), {
            'first_name': 'Taylor',
            'last_name': 'Customer',
            'email': self.user.email,
            'phone': '0712345678',
            'address': '42 Main Street',
            'notes': '',
        })

        self.assertRedirects(response, reverse('dashboard'))
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.phone, '0712345678')
        self.assertEqual(self.customer.address, '42 Main Street')
        entry = AuditLog.objects.get(action='customer_profile_updated', object_id=self.customer.pk)
        self.assertEqual(entry.actor, self.user)
        self.assertEqual(set(entry.details['changed_fields']), {'phone', 'address'})
        self.assertNotIn('0712345678', json.dumps(entry.details))
        self.assertNotIn('42 Main Street', json.dumps(entry.details))

        staff = User.objects.create_user(username='staff', password='test-password')
        UserProfile.objects.create(user=staff, role='admin')
        self.client.force_login(staff)
        customer_list = self.client.get(reverse('customer_list'))
        self.assertContains(customer_list, '0712345678')
        self.assertContains(customer_list, '42 Main Street')

    def test_customer_profile_requires_phone_and_address(self):
        form = CustomerForm(data={
            'first_name': 'Taylor',
            'last_name': 'Customer',
            'email': self.user.email,
            'phone': '',
            'address': '',
            'notes': '',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('phone', form.errors)
        self.assertIn('address', form.errors)


class RoleBoundaryTests(TestCase):
    def setUp(self):
        self.customer_user = User.objects.create_user(
            username='boundary-customer',
            email='boundary-customer@example.com',
            password='test-password',
        )
        UserProfile.objects.create(user=self.customer_user, role='customer', is_verified=True)
        self.customer = Customer.objects.create(
            first_name='Boundary',
            last_name='Customer',
            email=self.customer_user.email,
            phone='0712345678',
            address='1 Test Street',
        )
        self.other_customer = Customer.objects.create(
            first_name='Other',
            last_name='Customer',
            email='other-boundary@example.com',
            phone='0712345679',
            address='2 Test Street',
        )
        self.mechanic = User.objects.create_user(
            username='boundary-mechanic',
            password='test-password',
        )
        UserProfile.objects.create(user=self.mechanic, role='mechanic')

    def test_customers_cannot_reach_admin_crud_endpoints(self):
        self.client.force_login(self.customer_user)

        for route_name in ('customer_create', 'part_create', 'service_create'):
            with self.subTest(route=route_name):
                response = self.client.get(reverse(route_name))
                self.assertRedirects(response, reverse('dashboard'))

    def test_audit_log_is_admin_only_searchable_and_read_only(self):
        entry = AuditLog.objects.create(
            actor=self.mechanic,
            action='vehicle_updated',
            object_type='Vehicle',
            object_id=42,
            details={'field': 'mileage'},
        )
        admin = User.objects.create_user(username='audit-admin', password='test-password', is_staff=True)
        UserProfile.objects.create(user=admin, role='admin')

        self.client.force_login(admin)
        response = self.client.get(reverse('audit_log'), {'q': 'vehicle_updated'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, entry.action)
        self.assertContains(response, 'mileage')
        self.assertEqual(self.client.post(reverse('audit_log')).status_code, 405)

        self.client.force_login(self.customer_user)
        self.assertRedirects(self.client.get(reverse('audit_log')), reverse('dashboard'))
        self.client.force_login(self.mechanic)
        self.assertRedirects(self.client.get(reverse('audit_log')), reverse('dashboard'))

    def test_customer_and_vehicle_lists_are_paginated(self):
        admin = User.objects.create_user(username='pagination-admin', password='test-password', is_staff=True)
        UserProfile.objects.create(user=admin, role='admin')
        for index in range(26):
            customer = Customer.objects.create(
                first_name=f'Page{index}',
                last_name='Customer',
                email=f'page-{index}@example.com',
                phone=f'0712345{index:03d}',
                address='Pagination Street',
            )
            Vehicle.objects.create(customer=customer, make='Toyota', model='Yaris', year=2020)
        self.client.force_login(admin)

        customers_page = self.client.get(reverse('customer_list'))
        vehicles_page = self.client.get(reverse('vehicle_list'))

        self.assertEqual(customers_page.context['customers'].paginator.num_pages, 2)
        self.assertEqual(vehicles_page.context['vehicles'].paginator.num_pages, 2)
        self.assertContains(customers_page, 'Page 1 of 2')
        self.assertContains(vehicles_page, 'Page 1 of 2')
        self.assertContains(self.client.get(reverse('customer_list'), {'page': 2}), 'Page 2 of 2')

    def test_admin_search_filters_vehicles_repairs_invoices_and_appointments(self):
        admin = User.objects.create_user(username='listsearchadmin', password='test-password', is_staff=True)
        UserProfile.objects.create(user=admin, role='admin')
        vehicle = Vehicle.objects.create(
            customer=self.customer,
            make='Honda',
            model='Civic',
            year=2022,
            license_plate='ABC123',
        )
        order = RepairOrder.objects.create(vehicle=vehicle, assigned_tech=self.mechanic, description='Searchable repair')
        Invoice.objects.create(repair_order=order, due_date=timezone.localdate() + timedelta(days=1))
        Appointment.objects.create(
            customer=self.customer,
            vehicle=vehicle,
            date_time=timezone.now(),
            service_desc='Searchable appointment',
        )
        self.client.force_login(admin)

        vehicle_response = self.client.get(reverse('vehicle_list'), {'q': 'Boundary'})
        repair_response = self.client.get(reverse('repair_order_list'), {'q': 'Honda'})
        invoice_response = self.client.get(reverse('invoice_list'), {'q': str(order.invoice.pk)})
        appointment_response = self.client.get(reverse('appointment_list'), {'q': 'ABC123'})

        self.assertContains(vehicle_response, 'ABC123')
        self.assertContains(repair_response, f'#{order.pk}')
        self.assertContains(invoice_response, f'#{order.invoice.pk}')
        self.assertContains(appointment_response, 'ABC123')

    def test_mechanics_cannot_reach_customer_or_vehicle_lists(self):
        self.client.force_login(self.mechanic)

        for route_name in ('customer_list', 'vehicle_list'):
            with self.subTest(route=route_name):
                response = self.client.get(reverse(route_name))
                self.assertRedirects(response, reverse('dashboard'))

    def test_mechanics_can_view_parts_and_services_for_assigned_work(self):
        self.client.force_login(self.mechanic)

        self.assertEqual(self.client.get(reverse('parts_list')).status_code, 200)
        self.assertEqual(self.client.get(reverse('service_list')).status_code, 200)

    def test_customer_lists_are_limited_to_the_authenticated_customer(self):
        vehicle = Vehicle.objects.create(
            customer=self.customer,
            make='Toyota',
            model='Corolla',
            year=2020,
        )
        Vehicle.objects.create(
            customer=self.other_customer,
            make='Ford',
            model='Ranger',
            year=2021,
        )
        self.client.force_login(self.customer_user)

        customers_response = self.client.get(reverse('customer_list'))
        vehicles_response = self.client.get(reverse('vehicle_list'))

        self.assertContains(customers_response, self.customer.email)
        self.assertNotContains(customers_response, self.other_customer.email)
        self.assertContains(vehicles_response, vehicle.make)
        self.assertNotContains(vehicles_response, 'Ranger')

    def test_vehicle_edits_audit_changed_field_names_not_sensitive_values(self):
        vehicle = Vehicle.objects.create(
            customer=self.customer,
            make='Toyota',
            model='Corolla',
            year=2020,
            vin='1HGCM82633A004352',
            mileage=100,
        )
        admin = User.objects.create_user(username='vehicleauditadmin', password='test-password', is_staff=True)
        self.client.force_login(admin)

        response = self.client.post(reverse('vehicle_edit', args=[vehicle.pk]), {
            'customer': self.customer.pk,
            'make': 'Toyota',
            'model': 'Corolla',
            'year': '2020',
            'vin': '1HGCM82633A004352',
            'license_plate': '',
            'color': '',
            'mileage': '150',
            'service_plan': '',
            'recent_service_history': '',
            'notes': '',
        })

        self.assertRedirects(response, reverse('vehicle_detail', args=[vehicle.pk]))
        entry = AuditLog.objects.get(action='vehicle_updated', object_id=vehicle.pk)
        self.assertEqual(entry.actor, admin)
        self.assertEqual(entry.details, {'changed_fields': ['mileage']})
        self.assertNotIn(vehicle.vin, json.dumps(entry.details))

    def test_customer_approval_writes_attributed_visible_timeline_event(self):
        vehicle = Vehicle.objects.create(
            customer=self.customer,
            make='Toyota',
            model='Corolla',
            year=2020,
        )
        order = RepairOrder.objects.create(
            vehicle=vehicle,
            description='Timeline test repair',
        )
        add_estimate_line(order, self.mechanic)
        self.client.force_login(self.customer_user)

        response = self.client.post(
            reverse('repair_order_customer_decision', args=[order.pk, 'approve']),
        )

        self.assertRedirects(response, reverse('repair_order_detail', args=[order.pk]))
        event = RepairOrderEvent.objects.get(repair_order=order, event_type='approval')
        self.assertEqual(event.actor, self.customer_user)
        self.assertTrue(event.customer_visible)
        self.assertEqual(event.metadata, {
            'approved': True,
            'estimate_version': 1,
            'estimate_total': '250.00',
        })
        estimate = RepairEstimate.objects.get(repair_order=order, version=1)
        self.assertEqual(estimate.status, 'approved')
        self.assertEqual(estimate.decided_by, self.customer_user)
        self.assertEqual(estimate.total_amount, 250)

        detail = self.client.get(reverse('repair_order_detail', args=[order.pk]))
        self.assertContains(detail, 'Customer approval recorded')

    def test_customer_can_approve_active_order_before_work_is_logged(self):
        vehicle = Vehicle.objects.create(
            customer=self.customer,
            make='Toyota',
            model='Corolla',
            year=2020,
        )
        order = RepairOrder.objects.create(
            vehicle=vehicle,
            description='Estimate awaiting approval',
            status='in_progress',
        )
        service = ServiceItem.objects.create(name='Inspection', labor_hours=1, labor_rate=250)
        RepairEstimateLine.objects.create(
            repair_order=order,
            line_type='labor',
            service_item=service,
            quantity=1,
            unit_price=250,
            created_by=self.mechanic,
        )
        self.client.force_login(self.customer_user)

        response = self.client.post(
            reverse('repair_order_customer_decision', args=[order.pk, 'approve']),
        )

        self.assertRedirects(response, reverse('repair_order_detail', args=[order.pk]))
        order.refresh_from_db()
        self.assertTrue(order.approved)
        estimate = RepairEstimate.objects.get(repair_order=order, status='approved')
        self.assertEqual(estimate.total_amount, 250)

    def test_customer_cannot_approve_or_decline_without_an_estimate(self):
        vehicle = Vehicle.objects.create(customer=self.customer, make='Toyota', model='Corolla', year=2020)
        order = RepairOrder.objects.create(vehicle=vehicle, description='No estimate yet')
        self.client.force_login(self.customer_user)

        detail = self.client.get(reverse('repair_order_detail', args=[order.pk]))
        self.assertContains(detail, 'No estimate has been prepared')
        self.assertNotContains(detail, 'Approve</button>')
        self.assertNotContains(detail, 'Decline</button>')
        dashboard = self.client.get(reverse('dashboard'))
        self.assertNotIn(order, list(dashboard.context['pending_approval']))

        for action in ('approve', 'decline'):
            response = self.client.post(reverse('repair_order_customer_decision', args=[order.pk, action]))
            self.assertRedirects(response, reverse('repair_order_detail', args=[order.pk]))
            order.refresh_from_db()
            self.assertFalse(order.approved)
            self.assertFalse(RepairEstimate.objects.filter(repair_order=order).exclude(status='pending').exists())

        add_estimate_line(order, self.mechanic)
        detail = self.client.get(reverse('repair_order_detail', args=[order.pk]))
        self.assertContains(detail, 'Approve</button>')
        self.assertContains(detail, 'Decline</button>')

    def test_customer_cannot_approve_after_work_is_logged(self):
        vehicle = Vehicle.objects.create(
            customer=self.customer,
            make='Toyota',
            model='Corolla',
            year=2020,
        )
        order = RepairOrder.objects.create(
            vehicle=vehicle,
            description='Work already logged',
            status='in_progress',
        )
        service = ServiceItem.objects.create(name='Repair', labor_hours=1, labor_rate=250)
        LaborLine.objects.create(repair_order=order, service_item=service, hours=1, rate=250)
        self.client.force_login(self.customer_user)

        self.client.post(reverse('repair_order_customer_decision', args=[order.pk, 'approve']))

        order.refresh_from_db()
        self.assertFalse(order.approved)
        self.assertFalse(RepairEstimate.objects.filter(repair_order=order, status='approved').exists())

    def test_customer_collection_creates_a_protected_collection_record(self):
        vehicle = Vehicle.objects.create(
            customer=self.customer,
            make='Toyota',
            model='Corolla',
            year=2020,
        )
        order = RepairOrder.objects.create(
            vehicle=vehicle,
            description='Collection test repair',
            status='ready',
            approved=True,
        )
        Invoice.objects.create(
            repair_order=order,
            due_date=date.today(),
            payment_status='paid',
        )
        self.client.force_login(self.customer_user)

        response = self.client.post(
            reverse('repair_order_customer_decision', args=[order.pk, 'collect']),
        )

        self.assertRedirects(response, reverse('repair_order_detail', args=[order.pk]))
        collection = CollectionRecord.objects.get(repair_order=order)
        self.assertEqual(collection.collected_by, self.customer_user)
        self.assertIsNotNone(collection.collected_at)

    def test_customer_visible_status_change_creates_unread_notification(self):
        admin = User.objects.create_user(username='notification-admin', password='test-password', is_staff=True)
        UserProfile.objects.create(user=admin, role='admin')
        vehicle = Vehicle.objects.create(
            customer=self.customer,
            make='Toyota',
            model='Corolla',
            year=2020,
        )
        order = RepairOrder.objects.create(
            vehicle=vehicle,
            description='Notification test repair',
            status='in_progress',
            approved=True,
        )
        self.client.force_login(admin)

        response = self.client.post(reverse('repair_order_finalize', args=[order.pk, 'ready']))

        self.assertRedirects(response, reverse('repair_order_detail', args=[order.pk]))
        notification = Notification.objects.get(recipient=self.customer_user, repair_order=order)
        self.assertFalse(notification.is_read)
        self.assertEqual(notification.link, f'/repairs/{order.pk}/')
        audit_entry = AuditLog.objects.get(action='status_changed', repair_order=order)
        self.assertEqual(audit_entry.actor, admin)
        self.assertEqual(audit_entry.details['current_status'], 'ready')

    def test_customer_can_mark_only_their_notification_as_read(self):
        notification = Notification.objects.create(
            recipient=self.customer_user,
            message='Please review your repair update.',
            link='/repairs/1/',
        )
        self.client.force_login(self.customer_user)

        dashboard = self.client.get(reverse('dashboard'))
        self.assertContains(dashboard, notification.message)

        response = self.client.post(reverse('notification_mark_read', args=[notification.pk]))

        self.assertRedirects(response, reverse('dashboard'))
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

        self.client.force_login(self.mechanic)
        forbidden = self.client.post(reverse('notification_mark_read', args=[notification.pk]))
        self.assertEqual(forbidden.status_code, 404)
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

    def test_customer_can_download_only_their_invoice(self):
        vehicle = Vehicle.objects.create(
            customer=self.customer,
            make='Toyota',
            model='Corolla',
            year=2020,
        )
        order = RepairOrder.objects.create(
            vehicle=vehicle,
            description='Invoice download test',
            approved=True,
        )
        invoice = Invoice.objects.create(
            repair_order=order,
            due_date=date.today(),
            service_amount='500.00',
        )
        self.client.force_login(self.customer_user)

        response = self.client.get(reverse('invoice_download', args=[invoice.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn(f'invoice-{invoice.pk}.csv', response['Content-Disposition'])
        self.assertIn('Balance due,R 575.00', response.content.decode())

    def test_repair_documents_are_validated_and_customer_scoped(self):
        admin = User.objects.create_user(username='document-admin', password='test-password', is_staff=True)
        UserProfile.objects.create(user=admin, role='admin')
        vehicle = Vehicle.objects.create(
            customer=self.customer,
            make='Toyota',
            model='Corolla',
            year=2020,
        )
        order = RepairOrder.objects.create(vehicle=vehicle, description='Document test repair')
        upload = SimpleUploadedFile('inspection.pdf', b'%PDF-test', content_type='application/pdf')
        self.client.force_login(admin)

        response = self.client.post(
            reverse('repair_document_upload', args=[order.pk]),
            {'title': 'Inspection report', 'customer_visible': 'on', 'file': upload},
        )

        self.assertRedirects(response, reverse('repair_order_detail', args=[order.pk]))
        document = RepairDocument.objects.get(repair_order=order)
        self.assertTrue(document.customer_visible)
        self.client.force_login(self.customer_user)
        repair_order_page = self.client.get(reverse('repair_order_detail', args=[order.pk]))
        self.assertContains(repair_order_page, 'Inspection report')
        download = self.client.get(reverse('repair_document_download', args=[document.pk]))
        self.assertEqual(download.status_code, 200)
        self.assertEqual(b''.join(download.streaming_content), b'%PDF-test')
        document.file.delete(save=False)

        other_customer = Customer.objects.create(
            first_name='Other',
            last_name='Document Owner',
            email='other-document-owner@example.com',
        )
        other_vehicle = Vehicle.objects.create(
            customer=other_customer,
            make='Honda',
            model='Civic',
            year=2022,
        )
        other_order = RepairOrder.objects.create(vehicle=other_vehicle, description='Private repair')
        other_document = RepairDocument.objects.create(
            repair_order=other_order,
            title='Other customer inspection',
            file=SimpleUploadedFile('other-inspection.pdf', b'%PDF-other', content_type='application/pdf'),
            uploaded_by=admin,
            customer_visible=True,
        )
        forbidden_download = self.client.get(reverse('repair_document_download', args=[other_document.pk]))
        self.assertRedirects(forbidden_download, reverse('dashboard'))
        other_document.file.delete(save=False)

        spoofed_pdf = SimpleUploadedFile('spoofed.pdf', b'not a PDF', content_type='application/pdf')
        self.client.force_login(admin)
        self.client.post(
            reverse('repair_document_upload', args=[order.pk]),
            {'title': 'Spoofed PDF', 'file': spoofed_pdf},
        )
        self.assertFalse(RepairDocument.objects.filter(title='Spoofed PDF').exists())

        invalid_upload = SimpleUploadedFile('script.exe', b'not allowed', content_type='application/octet-stream')
        self.client.force_login(admin)
        self.client.post(
            reverse('repair_document_upload', args=[order.pk]),
            {'title': 'Invalid file', 'file': invalid_upload},
        )
        self.assertFalse(RepairDocument.objects.filter(title='Invalid file').exists())

    def test_assigned_mechanic_can_upload_customer_visible_document(self):
        vehicle = Vehicle.objects.create(
            customer=self.customer,
            make='Toyota',
            model='Corolla',
            year=2020,
        )
        order = RepairOrder.objects.create(
            vehicle=vehicle,
            assigned_tech=self.mechanic,
            description='Customer-visible document test',
        )
        upload = SimpleUploadedFile('inspection.pdf', b'%PDF-mechanic', content_type='application/pdf')
        self.client.force_login(self.mechanic)

        response = self.client.post(
            reverse('repair_document_upload', args=[order.pk]),
            {'title': 'Mechanic inspection report', 'customer_visible': 'on', 'file': upload},
        )

        self.assertRedirects(response, reverse('repair_order_detail', args=[order.pk]))
        document = RepairDocument.objects.get(repair_order=order, title='Mechanic inspection report')
        self.assertTrue(document.customer_visible)

        self.client.force_login(self.customer_user)
        repair_order_page = self.client.get(reverse('repair_order_detail', args=[order.pk]))
        self.assertContains(repair_order_page, 'Mechanic inspection report')
        download = self.client.get(reverse('repair_document_download', args=[document.pk]))
        self.assertEqual(download.status_code, 200)
        self.assertEqual(b''.join(download.streaming_content), b'%PDF-mechanic')
        document.file.delete(save=False)

    def test_assigned_mechanic_can_prepare_quote_before_customer_approval(self):
        vehicle = Vehicle.objects.create(
            customer=self.customer,
            make='Toyota',
            model='Corolla',
            year=2020,
        )
        order = RepairOrder.objects.create(
            vehicle=vehicle,
            assigned_tech=self.mechanic,
            description='Quote preparation test',
        )
        service = ServiceItem.objects.create(name='Diagnostic', labor_hours=1, labor_rate=200)
        self.client.force_login(self.mechanic)

        response = self.client.post(
            reverse('repair_estimate_line_add', args=[order.pk]),
            {'line_type': 'labor', 'service_item': service.pk, 'quantity': '1', 'notes': 'Initial diagnosis'},
        )

        self.assertRedirects(response, reverse('repair_order_detail', args=[order.pk]))
        estimate = RepairEstimate.objects.get(repair_order=order, status='pending')
        quote_line = RepairEstimateLine.objects.get(repair_order=order)
        self.assertEqual(quote_line.unit_price, 200)
        self.assertEqual(estimate.total_amount, 200)
        self.assertEqual(RepairEstimateLine.objects.filter(repair_order=order).count(), 1)
        self.client.force_login(self.customer_user)
        estimate_page = self.client.get(reverse('repair_order_detail', args=[order.pk]))
        self.assertContains(estimate_page, 'Diagnostic')
        self.assertContains(estimate_page, 'R 200.00')
        self.assertContains(estimate_page, '>Approve</button>')
        RepairEstimate.objects.filter(repair_order=order, status='pending').delete()
        self.client.post(reverse('repair_order_customer_decision', args=[order.pk, 'approve']))
        estimate = RepairEstimate.objects.get(repair_order=order, version=1)
        self.assertEqual(estimate.status, 'approved')
        self.assertEqual(estimate.total_amount, 200)
        approval_event = RepairOrderEvent.objects.get(repair_order=order, event_type='approval')
        self.assertEqual(approval_event.metadata['estimate_total'], '200.00')


class MechanicJobAssignmentTests(TestCase):
    def setUp(self):
        self.mechanic = User.objects.create_user(username='mechanic', password='test-password')
        UserProfile.objects.create(user=self.mechanic, role='mechanic')
        self.non_mechanic = User.objects.create_user(username='notmechanic', password='test-password')
        UserProfile.objects.create(user=self.non_mechanic, role='admin')
        self.customer = Customer.objects.create(
            first_name='Jamie',
            last_name='Driver',
            email='driver@example.com',
        )
        self.vehicle = Vehicle.objects.create(
            customer=self.customer,
            make='Toyota',
            model='Corolla',
            year=2022,
        )
        self.order = RepairOrder.objects.create(
            vehicle=self.vehicle,
            assigned_tech=self.mechanic,
            description='Brake inspection',
        )

    def test_technician_dropdown_only_lists_mechanics(self):
        form = RepairOrderForm()

        self.assertEqual(list(form.fields['assigned_tech'].queryset), [self.mechanic])

    def test_create_job_action_is_only_on_admin_dashboard(self):
        self.client.force_login(self.mechanic)
        mechanic_dashboard = self.client.get(reverse('dashboard'))
        self.assertNotContains(mechanic_dashboard, 'Create new job')

        self.client.force_login(self.non_mechanic)
        admin_dashboard = self.client.get(reverse('dashboard'))
        self.assertContains(admin_dashboard, 'Create new job')

    def test_mechanic_cannot_open_create_job_page(self):
        self.client.force_login(self.mechanic)

        response = self.client.get(reverse('repair_order_create'))

        self.assertRedirects(response, reverse('dashboard'))

    def test_mechanic_acceptance_waits_for_admin_status_approval(self):
        self.client.force_login(self.mechanic)

        response = self.client.post(reverse('repair_order_decision', args=[self.order.pk, 'accept']))

        self.assertRedirects(response, reverse('dashboard'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'pending')
        self.assertEqual(self.order.pending_status, 'in_progress')

    def test_appointment_acceptance_proposes_status_for_admin_approval(self):
        appointment_order = RepairOrder.objects.create(
            vehicle=self.vehicle,
            description='Tire rotation',
        )
        appointment = Appointment.objects.create(
            customer=self.customer,
            vehicle=self.vehicle,
            repair_order=appointment_order,
            date_time='2026-10-01T09:00:00Z',
            service_desc='Brake inspection',
            assigned_mechanic=self.mechanic,
        )
        self.client.force_login(self.mechanic)

        response = self.client.post(
            reverse('appointment_decision', args=[appointment.pk, 'accept']),
        )

        self.assertRedirects(response, reverse('dashboard'))
        self.order.refresh_from_db()
        appointment_order.refresh_from_db()
        self.assertEqual(self.order.status, 'pending')
        self.assertEqual(self.order.pending_status, '')
        self.assertEqual(appointment_order.pending_status, 'in_progress')

    def test_mechanic_appointment_list_only_shows_their_assignments(self):
        assigned_appointment = Appointment.objects.create(
            customer=self.customer,
            vehicle=self.vehicle,
            date_time='2030-05-20T10:30:00Z',
            service_desc='Assigned service',
            assigned_mechanic=self.mechanic,
        )
        other_mechanic = User.objects.create_user(username='other-mechanic', password='test-password')
        UserProfile.objects.create(user=other_mechanic, role='mechanic')
        Appointment.objects.create(
            customer=self.customer,
            vehicle=self.vehicle,
            date_time='2030-05-21T10:30:00Z',
            service_desc='Other mechanic service',
            assigned_mechanic=other_mechanic,
        )
        Appointment.objects.create(
            customer=self.customer,
            vehicle=self.vehicle,
            date_time='2030-05-22T10:30:00Z',
            service_desc='Unassigned service',
        )
        self.client.force_login(self.mechanic)

        response = self.client.get(reverse('appointment_list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['appointments']), [assigned_appointment])

    def test_mechanic_cannot_accept_appointment_via_get(self):
        appointment = Appointment.objects.create(
            customer=self.customer,
            vehicle=self.vehicle,
            date_time='2026-10-01T09:00:00Z',
            service_desc='Brake inspection',
            assigned_mechanic=self.mechanic,
        )
        self.client.force_login(self.mechanic)

        response = self.client.get(
            reverse('appointment_decision', args=[appointment.pk, 'accept']),
        )

        self.assertEqual(response.status_code, 405)
        appointment.refresh_from_db()
        self.assertEqual(appointment.assignment_status, 'pending')
        self.assertEqual(self.order.pending_status, '')

    @patch('workshop.views.Appointment.has_schedule_conflict')
    def test_appointment_acceptance_checks_schedule_inside_transaction(self, conflict_check):
        appointment = Appointment.objects.create(
            customer=self.customer,
            vehicle=self.vehicle,
            date_time='2026-10-01T09:00:00Z',
            service_desc='Brake inspection',
            assigned_mechanic=self.mechanic,
        )

        def check_while_locked(**kwargs):
            self.assertTrue(connection.in_atomic_block)
            return False

        conflict_check.side_effect = check_while_locked
        self.client.force_login(self.mechanic)

        response = self.client.post(reverse('appointment_decision', args=[appointment.pk, 'accept']))

        self.assertRedirects(response, reverse('dashboard'))
        conflict_check.assert_called_once()
        appointment.refresh_from_db()
        self.assertEqual(appointment.assignment_status, 'accepted')

    def test_mechanic_cannot_accept_overlapping_appointment(self):
        Appointment.objects.create(
            customer=self.customer,
            vehicle=self.vehicle,
            date_time='2026-10-01T09:00:00Z',
            duration=60,
            service_desc='Existing service',
            assigned_mechanic=self.mechanic,
            assignment_status='accepted',
        )
        appointment = Appointment.objects.create(
            customer=self.customer,
            vehicle=self.vehicle,
            date_time='2026-10-01T09:30:00Z',
            duration=60,
            service_desc='Another service',
            assigned_mechanic=self.mechanic,
        )
        self.client.force_login(self.mechanic)

        response = self.client.post(
            reverse('appointment_decision', args=[appointment.pk, 'accept']),
        )

        self.assertRedirects(response, reverse('appointment_list'))
        appointment.refresh_from_db()
        self.assertEqual(appointment.assignment_status, 'pending')

    def test_mechanic_appointment_edit_queues_status_for_admin_approval(self):
        appointment = Appointment.objects.create(
            customer=self.customer,
            vehicle=self.vehicle,
            date_time='2026-10-01T09:00:00Z',
            service_desc='Brake inspection',
            assigned_mechanic=self.mechanic,
        )
        self.client.force_login(self.mechanic)

        response = self.client.post(
            reverse('appointment_edit', args=[appointment.pk]),
            {
                'customer': self.customer.pk,
                'vehicle': self.vehicle.pk,
                'date_time': '2026-10-01T09:00',
                'service_desc': 'Brake inspection',
                'assigned_mechanic': self.mechanic.pk,
                'assignment_status': 'accepted',
                'notes': '',
            },
        )

        self.assertRedirects(response, reverse('appointment_list'))
        self.order.refresh_from_db()
        appointment.refresh_from_db()
        self.assertEqual(self.order.status, 'pending')
        self.assertEqual(self.order.pending_status, '')
        self.assertIsNotNone(appointment.repair_order_id)
        self.assertEqual(appointment.repair_order.pending_status, 'in_progress')
        appointment_audit = AuditLog.objects.get(action='appointment_updated', object_id=appointment.pk)
        self.assertEqual(appointment_audit.actor, self.mechanic)
        self.assertEqual(
            appointment_audit.details['changes']['assignment_status'],
            {'from': 'pending', 'to': 'accepted'},
        )

    def test_mechanic_cannot_change_appointment_customer_vehicle_or_assignment(self):
        appointment = Appointment.objects.create(
            customer=self.customer,
            vehicle=self.vehicle,
            date_time='2030-05-20T10:30:00Z',
            service_desc='Brake inspection',
            assigned_mechanic=self.mechanic,
        )
        other_customer = Customer.objects.create(
            first_name='Other',
            last_name='Owner',
            email='other-owner@example.com',
        )
        other_vehicle = Vehicle.objects.create(
            customer=other_customer,
            make='Honda',
            model='Civic',
            year=2021,
        )
        other_mechanic = User.objects.create_user(username='other-mechanic', password='test-password')
        UserProfile.objects.create(user=other_mechanic, role='mechanic')
        self.client.force_login(self.mechanic)

        response = self.client.post(reverse('appointment_edit', args=[appointment.pk]), {
            'customer': other_customer.pk,
            'vehicle': other_vehicle.pk,
            'date_time': '2031-05-20T10:30',
            'service_desc': 'Tampered request',
            'assigned_mechanic': other_mechanic.pk,
            'assignment_status': 'accepted',
            'notes': '',
        })

        self.assertRedirects(response, reverse('appointment_list'))
        appointment.refresh_from_db()
        self.assertEqual(appointment.customer_id, self.customer.pk)
        self.assertEqual(appointment.vehicle_id, self.vehicle.pk)
        self.assertEqual(appointment.date_time.year, 2030)
        self.assertEqual(appointment.service_desc, 'Brake inspection')
        self.assertEqual(appointment.assigned_mechanic_id, self.mechanic.pk)

    def test_staff_cannot_book_vehicle_under_another_customer(self):
        other_customer = Customer.objects.create(
            first_name='Other',
            last_name='Owner',
            email='other-owner@example.com',
        )
        other_vehicle = Vehicle.objects.create(
            customer=other_customer,
            make='Honda',
            model='Civic',
            year=2021,
        )
        self.client.force_login(self.non_mechanic)

        response = self.client.post(reverse('appointment_create'), {
            'customer': self.customer.pk,
            'vehicle': other_vehicle.pk,
            'date_time': '2030-05-20T10:30',
            'service_desc': 'Annual service',
        })

        self.assertEqual(response.status_code, 200)
        self.assertIn('vehicle', response.context['form'].errors)
        self.assertFalse(Appointment.objects.filter(vehicle=other_vehicle).exists())

    @patch('workshop.views.send_service_request_confirmation')
    def test_new_appointment_creates_its_own_repair_order(self, send_confirmation):
        customer_user = User.objects.create_user(
            username='vehicle-customer',
            email=self.customer.email,
            password='test-password',
        )
        UserProfile.objects.create(user=customer_user, role='customer', is_verified=True)
        self.customer.phone = '0712345678'
        self.customer.address = '42 Main Street'
        self.customer.save(update_fields=['phone', 'address'])
        self.order.status = 'in_progress'
        self.order.approved = True
        self.order.save(update_fields=['status', 'approved'])
        self.client.force_login(customer_user)

        response = self.client.post(reverse('appointment_create'), {
            'vehicle': self.vehicle.pk,
            'date_time': '2030-05-20T10:30',
            'service_desc': 'Annual service',
        })

        self.assertRedirects(response, reverse('dashboard'))
        appointment = Appointment.objects.get(service_desc='Annual service')
        self.order.refresh_from_db()
        self.assertNotEqual(appointment.repair_order_id, self.order.pk)
        self.assertEqual(appointment.repair_order.description, 'Annual service')
        self.assertEqual(self.order.description, 'Brake inspection')
        self.assertEqual(self.order.status, 'in_progress')
        self.assertTrue(self.order.approved)
        send_confirmation.assert_called_once()
        appointment_audit = AuditLog.objects.get(action='appointment_created', object_id=appointment.pk)
        self.assertEqual(appointment_audit.actor, customer_user)
        self.assertEqual(appointment_audit.repair_order, appointment.repair_order)
        order_audit = AuditLog.objects.get(action='created', object_id=appointment.repair_order_id)
        self.assertEqual(order_audit.actor, customer_user)
        self.assertEqual(order_audit.details['appointment_id'], appointment.pk)

    @patch('workshop.views.send_service_request_confirmation')
    def test_similar_pending_request_for_same_vehicle_is_blocked(self, send_confirmation):
        customer_user = User.objects.create_user(username='dup-customer', email=self.customer.email, password='test-password')
        UserProfile.objects.create(user=customer_user, role='customer', is_verified=True)
        self.customer.phone = '0712345678'
        self.customer.address = '42 Main Street'
        self.customer.save(update_fields=['phone', 'address'])
        RepairOrder.objects.filter(pk=self.order.pk).update(status='in_progress')
        self.client.force_login(customer_user)
        payload = {'vehicle': self.vehicle.pk, 'date_time': '2030-05-20T10:30', 'service_desc': 'Oil change'}

        self.assertRedirects(self.client.post(reverse('appointment_create'), payload), reverse('dashboard'))
        response = self.client.post(reverse('appointment_create'), {**payload, 'service_desc': 'Tyre rotation'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already submitted recently')
        self.assertEqual(Appointment.objects.filter(vehicle=self.vehicle, service_desc__in=['Oil change', 'Tyre rotation']).count(), 1)

    @patch('workshop.views.send_service_request_confirmation')
    def test_manual_vehicle_entry_reuses_existing_vehicle_and_blocks_duplicate(self, send_confirmation):
        customer_user = User.objects.create_user(username='dup2', email=self.customer.email, password='test-password')
        UserProfile.objects.create(user=customer_user, role='customer', is_verified=True)
        self.customer.phone = '0712345678'
        self.customer.address = '42 Main Street'
        self.customer.save(update_fields=['phone', 'address'])
        RepairOrder.objects.filter(pk=self.order.pk).update(status='in_progress')
        self.client.force_login(customer_user)
        before = Vehicle.objects.filter(customer=self.customer).count()
        payload = {
            'vehicle_make': self.vehicle.make.upper(), 'vehicle_model': self.vehicle.model,
            'vehicle_year': self.vehicle.year, 'date_time': '2030-05-20T10:30', 'service_desc': 'Oil change',
        }
        first = self.client.post(reverse('appointment_create'), payload)
        second = self.client.post(reverse('appointment_create'), payload)
        self.assertEqual(Vehicle.objects.filter(customer=self.customer).count(), before)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 200)

    def test_mechanic_status_menu_only_offers_admin_reviewable_proposals(self):
        self.client.force_login(self.mechanic)

        response = self.client.get(reverse('repair_order_detail', args=[self.order.pk]))

        self.assertContains(response, '<option value="in_progress">In Progress</option>', html=True)
        for status in ('waiting', 'ready', 'completed', 'cancelled'):
            self.assertNotContains(response, f'<option value="{status}">', html=True)

    def test_in_progress_mechanic_can_propose_ready_but_not_waiting_for_parts(self):
        self.order.status = 'in_progress'
        self.order.approved = True
        self.order.save(update_fields=['status', 'approved'])
        self.client.force_login(self.mechanic)

        response = self.client.get(reverse('repair_order_detail', args=[self.order.pk]))

        self.assertContains(response, '<option value="ready">Ready for Pickup</option>', html=True)
        self.assertNotContains(response, '<option value="waiting">', html=True)
        self.assertNotContains(response, '<option value="in_progress">', html=True)

        invalid_response = self.client.post(
            reverse('repair_order_status_proposal', args=[self.order.pk]),
            {'status': 'waiting'},
        )
        self.assertRedirects(invalid_response, reverse('repair_order_detail', args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.pending_status, '')

    def test_mechanic_can_propose_ready_for_admin_approval(self):
        self.order.status = 'in_progress'
        self.order.approved = True
        self.order.save(update_fields=['status', 'approved'])
        self.client.force_login(self.mechanic)

        proposal = self.client.post(
            reverse('repair_order_status_proposal', args=[self.order.pk]),
            {'status': 'ready'},
        )

        self.assertRedirects(proposal, reverse('repair_order_detail', args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'in_progress')
        self.assertEqual(self.order.pending_status, 'ready')

        self.client.force_login(self.non_mechanic)
        approval = self.client.post(
            reverse('repair_order_status_review', args=[self.order.pk, 'approve']),
        )

        self.assertRedirects(approval, reverse('dashboard'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'ready')
        self.assertEqual(self.order.pending_status, '')

    def test_mechanic_action_filters_link_to_relevant_repair_detail_sections(self):
        self.order.status = 'in_progress'
        self.order.approved = True
        self.order.save(update_fields=['status', 'approved'])
        self.client.force_login(self.mechanic)
        detail_url = reverse('repair_order_detail', args=[self.order.pk])

        status_list = self.client.get(reverse('repair_order_list'), {'status': 'in_progress', 'action': 'status'})
        self.assertContains(status_list, f'href="{detail_url}#status-update"')
        work_list = self.client.get(reverse('repair_order_list'), {'status': 'in_progress', 'action': 'work'})
        self.assertContains(work_list, f'href="{detail_url}#work-lines"')

        self.order.status = 'waiting'
        self.order.save(update_fields=['status'])
        waiting_list = self.client.get(reverse('repair_order_list'), {'status': 'waiting', 'action': 'waiting'})
        self.assertContains(waiting_list, f'href="{detail_url}#status-update"')

    def test_mechanic_sees_why_actual_work_lines_are_locked_before_approval(self):
        self.client.force_login(self.mechanic)

        response = self.client.get(reverse('repair_order_detail', args=[self.order.pk]))

        self.assertContains(response, 'Available after customer approval')
        self.assertNotContains(response, '+ Add Labor')
        self.assertNotContains(response, '+ Add Part')

    def test_status_proposal_is_hidden_from_customer_until_admin_approves(self):
        self.customer.phone = '0712345678'
        self.customer.address = '42 Main Street'
        self.customer.save(update_fields=['phone', 'address'])
        customer_user = User.objects.create_user(
            username='repaircustomer',
            email=self.customer.email,
            password='test-password',
        )
        UserProfile.objects.create(user=customer_user, role='customer', is_verified=True)
        self.client.force_login(self.mechanic)

        proposal_response = self.client.post(
            reverse('repair_order_status_proposal', args=[self.order.pk]),
            {'status': 'in_progress'},
        )

        self.assertRedirects(proposal_response, reverse('repair_order_detail', args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'pending')
        self.assertEqual(self.order.pending_status, 'in_progress')

        unauthorized_review = self.client.post(
            reverse('repair_order_status_review', args=[self.order.pk, 'approve']),
        )
        self.assertRedirects(unauthorized_review, reverse('dashboard'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'pending')
        self.assertEqual(self.order.pending_status, 'in_progress')

        self.client.force_login(customer_user)
        customer_response = self.client.get(reverse('repair_order_detail', args=[self.order.pk]))
        self.assertContains(customer_response, 'Pending')
        self.assertNotContains(customer_response, 'In Progress')

        self.client.force_login(self.non_mechanic)
        admin_dashboard = self.client.get(reverse('dashboard'))
        self.assertContains(admin_dashboard, 'Status updates awaiting approval')
        self.assertContains(admin_dashboard, 'In Progress')
        approval_response = self.client.post(
            reverse('repair_order_status_review', args=[self.order.pk, 'approve']),
        )
        self.assertRedirects(approval_response, reverse('dashboard'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'pending')
        self.assertEqual(self.order.pending_status, 'in_progress')

        add_estimate_line(self.order, self.mechanic)
        self.client.force_login(customer_user)
        customer_approval = self.client.post(
            reverse('repair_order_customer_decision', args=[self.order.pk, 'approve']),
        )
        self.assertRedirects(customer_approval, reverse('repair_order_detail', args=[self.order.pk]))
        self.client.force_login(self.non_mechanic)
        approval_response = self.client.post(
            reverse('repair_order_status_review', args=[self.order.pk, 'approve']),
        )
        self.assertRedirects(approval_response, reverse('dashboard'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'in_progress')
        self.assertEqual(self.order.pending_status, '')

        self.client.force_login(customer_user)
        customer_response = self.client.get(reverse('repair_order_detail', args=[self.order.pk]))
        self.assertContains(customer_response, 'In Progress')

    def test_mechanic_edit_form_cannot_change_status_or_approval(self):
        self.client.force_login(self.mechanic)

        page = self.client.get(reverse('repair_order_edit', args=[self.order.pk]))
        self.assertNotIn('status', page.context['form'].fields)
        self.assertNotIn('approved', page.context['form'].fields)
        self.assertTrue(page.context['form'].fields['vehicle'].disabled)
        self.assertTrue(page.context['form'].fields['assigned_tech'].disabled)
        self.assertTrue(page.context['form'].fields['description'].disabled)

        response = self.client.post(reverse('repair_order_edit', args=[self.order.pk]), {
            'vehicle': self.vehicle.pk,
            'assigned_tech': self.mechanic.pk,
            'status': 'completed',
            'description': self.order.description,
            'internal_notes': '',
            'mileage_in': self.order.mileage_in,
            'approved': 'on',
        })

        self.assertRedirects(response, reverse('repair_order_detail', args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'pending')
        self.assertFalse(self.order.approved)

    def test_admin_repair_order_edit_cannot_change_status_or_customer_approval(self):
        self.client.force_login(self.non_mechanic)

        page = self.client.get(reverse('repair_order_edit', args=[self.order.pk]))
        self.assertNotIn('status', page.context['form'].fields)
        self.assertNotIn('approved', page.context['form'].fields)
        self.assertTrue(page.context['form'].fields['vehicle'].disabled)

        response = self.client.post(reverse('repair_order_edit', args=[self.order.pk]), {
            'vehicle': self.vehicle.pk,
            'assigned_tech': self.mechanic.pk,
            'status': 'completed',
            'description': self.order.description,
            'internal_notes': '',
            'mileage_in': self.order.mileage_in,
            'approved': 'on',
        })

        self.assertRedirects(response, reverse('repair_order_detail', args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'pending')
        self.assertFalse(self.order.approved)

    def test_admin_repair_order_creation_starts_pending_and_unapproved(self):
        self.client.force_login(self.non_mechanic)

        page = self.client.get(reverse('repair_order_create'))
        self.assertNotIn('status', page.context['form'].fields)
        self.assertNotIn('approved', page.context['form'].fields)
        response = self.client.post(reverse('repair_order_create'), {
            'vehicle': self.vehicle.pk,
            'assigned_tech': self.mechanic.pk,
            'status': 'completed',
            'description': 'Fresh repair request',
            'internal_notes': '',
            'mileage_in': '50000',
            'approved': 'on',
        })

        created_order = RepairOrder.objects.get(description='Fresh repair request')
        self.assertRedirects(response, reverse('repair_order_detail', args=[created_order.pk]))
        self.assertEqual(created_order.status, 'pending')
        self.assertFalse(created_order.approved)

    def test_admin_can_reject_status_proposal_without_changing_current_status(self):
        self.client.force_login(self.mechanic)
        self.client.post(
            reverse('repair_order_status_proposal', args=[self.order.pk]),
            {'status': 'in_progress'},
        )
        self.client.force_login(self.non_mechanic)

        response = self.client.post(
            reverse('repair_order_status_review', args=[self.order.pk, 'reject']),
        )

        self.assertRedirects(response, reverse('dashboard'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'pending')
        self.assertEqual(self.order.pending_status, '')

    def test_admin_status_review_rejects_stale_ready_proposal(self):
        self.order.pending_status = 'ready'
        self.order.save(update_fields=['pending_status'])
        self.client.force_login(self.non_mechanic)

        response = self.client.post(
            reverse('repair_order_status_review', args=[self.order.pk, 'approve']),
        )

        self.assertRedirects(response, reverse('dashboard'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'pending')
        self.assertEqual(self.order.pending_status, '')

    def test_mechanic_can_decline_assigned_job_for_reassignment(self):
        self.client.force_login(self.mechanic)

        response = self.client.post(reverse('repair_order_decision', args=[self.order.pk, 'decline']))

        self.assertRedirects(response, reverse('dashboard'))
        self.order.refresh_from_db()
        self.assertIsNone(self.order.assigned_tech)
        self.assertEqual(self.order.status, 'pending')

    def test_mechanic_waiting_for_parts_filter_includes_pending_proposals(self):
        self.order.status = 'pending'
        self.order.pending_status = 'waiting'
        self.order.save(update_fields=['status', 'pending_status'])
        self.client.force_login(self.mechanic)

        response = self.client.get(reverse('repair_order_list'), {'status': 'waiting'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'#{self.order.pk}')
        self.assertContains(response, 'Waiting for Parts')
        self.assertContains(response, 'awaiting approval')

    def test_admin_cannot_create_invoice_until_customer_approves(self):
        self.client.force_login(self.non_mechanic)
        response = self.client.get(reverse('invoice_create'), {'ro': self.order.pk})

        self.assertRedirects(response, reverse('repair_order_detail', args=[self.order.pk]))
        self.assertFalse(Invoice.objects.filter(repair_order=self.order).exists())
        self.assertFalse(InvoiceForm().fields['repair_order'].queryset.filter(pk=self.order.pk).exists())

        post_response = self.client.post(reverse('invoice_create'), {
            'repair_order': self.order.pk,
            'due_date': (date.today() + timedelta(days=7)).isoformat(),
            'discount': '0.00',
            'tax_rate': '15.00',
            'notes': '',
        })
        self.assertEqual(post_response.status_code, 200)
        self.assertFalse(Invoice.objects.filter(repair_order=self.order).exists())

        self.order.approved = True
        self.order.save(update_fields=['approved'])
        approved_response = self.client.get(reverse('invoice_create'), {'ro': self.order.pk})

        self.assertEqual(approved_response.status_code, 200)

    def test_admin_cannot_invoice_a_cancelled_repair(self):
        self.order.approved = True
        self.order.status = 'cancelled'
        self.order.save(update_fields=['approved', 'status'])
        self.client.force_login(self.non_mechanic)

        explicit_order_response = self.client.get(reverse('invoice_create'), {'ro': self.order.pk})
        form_response = self.client.post(reverse('invoice_create'), {
            'repair_order': self.order.pk,
            'due_date': (date.today() + timedelta(days=7)).isoformat(),
            'discount': '0.00',
            'tax_rate': '15.00',
            'notes': '',
        })

        self.assertRedirects(explicit_order_response, reverse('repair_order_detail', args=[self.order.pk]))
        self.assertEqual(form_response.status_code, 200)
        self.assertFalse(Invoice.objects.filter(repair_order=self.order).exists())

    @patch('workshop.views.send_invoice_ready_email')
    def test_invoice_issuance_is_audited(self, send_invoice_email):
        self.order.approved = True
        self.order.save(update_fields=['approved'])
        self.client.force_login(self.non_mechanic)

        response = self.client.post(
            f"{reverse('invoice_create')}?ro={self.order.pk}",
            {
                'repair_order': self.order.pk,
                'issue_date': date.today().isoformat(),
                'due_date': (date.today() + timedelta(days=7)).isoformat(),
                'discount': '0.00',
                'tax_rate': '15.00',
                'notes': '',
            },
        )

        invoice = Invoice.objects.get(repair_order=self.order)
        self.assertRedirects(response, reverse('invoice_detail', args=[invoice.pk]))
        entry = AuditLog.objects.get(action='invoice_created', object_id=invoice.pk)
        self.assertEqual(entry.actor, self.non_mechanic)
        self.assertEqual(entry.repair_order, self.order)
        self.assertEqual(entry.details['total_due'], str(invoice.total_due))
        send_invoice_email.assert_called_once()

    def test_admin_can_finalize_a_paid_repair_as_completed(self):
        self.order.approved = True
        self.order.status = 'ready'
        self.order.save(update_fields=['approved', 'status'])
        Invoice.objects.create(
            repair_order=self.order,
            service_amount='500.00',
            due_date=date.today() + timedelta(days=7),
            payment_status='paid',
        )
        self.client.force_login(self.non_mechanic)

        response = self.client.post(reverse('repair_order_finalize', args=[self.order.pk, 'complete']))

        self.assertRedirects(response, reverse('repair_order_detail', args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'completed')

    def test_admin_cannot_reopen_terminal_repair_as_ready(self):
        self.order.approved = True
        self.client.force_login(self.non_mechanic)

        for terminal_status in ('cancelled', 'completed'):
            with self.subTest(status=terminal_status):
                self.order.status = terminal_status
                self.order.save(update_fields=['approved', 'status'])

                response = self.client.post(reverse('repair_order_finalize', args=[self.order.pk, 'ready']))

                self.assertRedirects(response, reverse('repair_order_detail', args=[self.order.pk]))
                self.order.refresh_from_db()
                self.assertEqual(self.order.status, terminal_status)

    def test_admin_can_cancel_open_repair_and_restore_parts_stock(self):
        self.order.approved = True
        self.order.status = 'in_progress'
        self.order.save(update_fields=['approved', 'status'])
        part = Part.objects.create(
            name='Air filter',
            cost_price=20,
            sell_price=35,
            stock_qty=5,
        )
        part.stock_qty -= 2
        part.save(update_fields=['stock_qty'])
        self.order.parts_lines.create(part=part, quantity=2, unit_price=35)
        part.refresh_from_db()
        self.assertEqual(part.stock_qty, 3)
        self.client.force_login(self.non_mechanic)

        response = self.client.post(reverse('repair_order_cancel', args=[self.order.pk]))

        self.assertRedirects(response, reverse('repair_order_detail', args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'cancelled')
        part.refresh_from_db()
        self.assertEqual(part.stock_qty, 5)
        restoration = AuditLog.objects.get(action='inventory_stock_restored', repair_order=self.order)
        self.assertEqual(restoration.actor, self.non_mechanic)
        self.assertEqual(restoration.details['quantity'], 2)
        self.assertEqual(restoration.details['stock_before'], 3)
        self.assertEqual(restoration.details['stock_after'], 5)

        repeat_response = self.client.post(reverse('repair_order_cancel', args=[self.order.pk]))

        self.assertRedirects(repeat_response, reverse('repair_order_detail', args=[self.order.pk]))
        part.refresh_from_db()
        self.assertEqual(part.stock_qty, 5)

    def test_work_is_locked_until_customer_approves_estimate(self):
        self.order.assigned_tech = self.mechanic
        self.order.status = 'in_progress'
        self.order.approved = False
        self.order.save(update_fields=['assigned_tech', 'status', 'approved'])
        service_item = ServiceItem.objects.create(name='Diagnostic', labor_hours=1, labor_rate=200)
        part = Part.objects.create(name='Oil filter', cost_price=15, sell_price=25, stock_qty=10)
        self.client.force_login(self.mechanic)

        labor_response = self.client.post(reverse('add_labor_line', args=[self.order.pk]), {
            'service_item': service_item.pk,
            'hours': '1',
            'notes': 'Test',
        })
        parts_response = self.client.post(reverse('add_parts_line', args=[self.order.pk]), {
            'part': part.pk,
            'quantity': '1',
        })

        self.assertRedirects(labor_response, reverse('repair_order_detail', args=[self.order.pk]))
        self.assertEqual(self.order.labor_lines.count(), 0)
        self.assertRedirects(parts_response, reverse('repair_order_detail', args=[self.order.pk]))
        self.assertEqual(self.order.parts_lines.count(), 0)

        self.client.force_login(self.non_mechanic)
        admin_labor_response = self.client.post(reverse('add_labor_line', args=[self.order.pk]), {
            'service_item': service_item.pk,
            'hours': '1',
            'notes': 'Admin bypass attempt',
        })
        admin_parts_response = self.client.post(reverse('add_parts_line', args=[self.order.pk]), {
            'part': part.pk,
            'quantity': '1',
        })

        self.assertRedirects(admin_labor_response, reverse('repair_order_detail', args=[self.order.pk]))
        self.assertRedirects(admin_parts_response, reverse('repair_order_detail', args=[self.order.pk]))
        self.assertEqual(self.order.labor_lines.count(), 0)
        self.assertEqual(self.order.parts_lines.count(), 0)
        part.refresh_from_db()
        self.assertEqual(part.stock_qty, 10)


class NavigationGuidanceTests(TestCase):
    def setUp(self):
        self.customer_user = User.objects.create_user(
            username='guidance-customer',
            email='guidance-customer@example.com',
            password='test-password',
        )
        UserProfile.objects.create(user=self.customer_user, role='customer', is_verified=True)
        self.customer = Customer.objects.create(
            first_name='Guide',
            last_name='Customer',
            email=self.customer_user.email,
            phone='0712345678',
            address='42 Main Street',
        )
        self.mechanic = User.objects.create_user(username='guidance-mechanic', password='test-password')
        UserProfile.objects.create(user=self.mechanic, role='mechanic')
        self.admin = User.objects.create_user(username='guidance-admin', password='test-password', is_staff=True)
        UserProfile.objects.create(user=self.admin, role='admin')

    def test_each_role_sees_its_own_first_task_guide_and_shared_menu(self):
        role_guides = [
            (self.customer_user, 'customer', 'Submit a service request'),
            (self.mechanic, 'mechanic', 'View assigned jobs'),
            (self.admin, 'admin', 'Add a customer'),
        ]

        for user, role, first_action in role_guides:
            with self.subTest(role=role):
                self.client.force_login(user)
                response = self.client.get(reverse('dashboard'))

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'data-role="{role}"')
                self.assertContains(response, first_action)
                self.assertContains(response, 'Dismiss welcome guide')
                self.assertContains(response, 'Open navigation menu')

    def test_mechanic_sidebar_links_route_to_distinct_job_views(self):
        self.client.force_login(self.mechanic)
        response = self.client.get(reverse('dashboard'))

        self.assertContains(response, 'View assigned jobs')
        self.assertContains(response, 'Update job status')
        self.assertContains(response, 'Log parts & labour')
        self.assertContains(response, 'Waiting for parts')
        self.assertContains(response, 'href="/repairs/?status=in_progress&amp;action=status"')
        self.assertContains(response, 'href="/repairs/?status=in_progress&amp;action=work"')
        self.assertContains(response, 'href="/repairs/?status=waiting&amp;action=waiting"')

    def test_mechanic_dashboard_tracks_waiting_for_parts_jobs(self):
        self.client.force_login(self.mechanic)
        waiting_order = RepairOrder.objects.create(
            vehicle=Vehicle.objects.create(
                customer=self.customer,
                make='Ford',
                model='Focus',
                year=2020,
                license_plate='WAIT123',
            ),
            assigned_tech=self.mechanic,
            status='waiting',
            description='Waiting for a replacement timing belt',
        )

        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertIn('waiting_orders', response.context)
        self.assertIn(waiting_order, response.context['waiting_orders'])

    def test_customer_sees_clear_pickup_notice_when_repair_is_ready(self):
        self.customer_user = User.objects.create_user(
            username='pickup-customer',
            email='pickup-customer@example.com',
            password='test-password',
        )
        UserProfile.objects.create(user=self.customer_user, role='customer', is_verified=True)
        customer = Customer.objects.create(
            first_name='Pickup',
            last_name='Customer',
            email=self.customer_user.email,
            phone='0712345678',
            address='42 Main Street',
        )
        vehicle = Vehicle.objects.create(
            customer=customer,
            make='Toyota',
            model='Corolla',
            year=2021,
            license_plate='READY1',
        )
        repair = RepairOrder.objects.create(
            vehicle=vehicle,
            assigned_tech=self.mechanic,
            status='ready',
            description='Ready for pickup',
            approved=True,
        )
        self.client.force_login(self.customer_user)

        response = self.client.get(reverse('repair_order_detail', args=[repair.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Your vehicle is ready for pickup')
        self.assertContains(response, 'Ready for Pickup')

    def test_customer_can_confirm_pickup_after_invoice_is_paid(self):
        customer_user = User.objects.create_user(
            username='pickup-confirmation-user',
            email='pickup-confirmation@example.com',
            password='test-password',
        )
        UserProfile.objects.create(user=customer_user, role='customer', is_verified=True)
        customer = Customer.objects.create(
            first_name='Pickup',
            last_name='Confirmation',
            email=customer_user.email,
            phone='0712345678',
            address='42 Main Street',
        )
        vehicle = Vehicle.objects.create(
            customer=customer,
            make='Honda',
            model='Civic',
            year=2022,
            license_plate='COLLECT1',
        )
        order = RepairOrder.objects.create(
            vehicle=vehicle,
            assigned_tech=self.mechanic,
            status='ready',
            description='Ready for collection',
            approved=True,
        )
        Invoice.objects.create(
            repair_order=order,
            service_amount='500.00',
            due_date=date.today() + timedelta(days=7),
            payment_status='paid',
        )
        self.client.force_login(customer_user)

        response = self.client.post(reverse('repair_order_customer_decision', args=[order.pk, 'collect']))

        self.assertRedirects(response, reverse('repair_order_detail', args=[order.pk]))
        order.refresh_from_db()
        self.assertEqual(order.status, 'completed')
        self.assertIsNotNone(order.date_completed)

    def test_mechanic_cannot_propose_terminal_statuses_directly(self):
        vehicle = Vehicle.objects.create(
            customer=self.customer,
            make='Audi',
            model='A4',
            year=2021,
            license_plate='TERM123',
        )
        order = RepairOrder.objects.create(
            vehicle=vehicle,
            assigned_tech=self.mechanic,
            status='pending',
            description='Test terminal status guard',
            approved=True,
        )
        self.client.force_login(self.mechanic)

        response = self.client.post(
            reverse('repair_order_status_proposal', args=[order.pk]),
            {'status': 'completed'},
        )

        self.assertRedirects(response, reverse('repair_order_detail', args=[order.pk]))
        order.refresh_from_db()
        self.assertEqual(order.status, 'pending')
        self.assertEqual(order.pending_status, '')

        response = self.client.post(
            reverse('repair_order_status_proposal', args=[order.pk]),
            {'status': 'cancelled'},
        )

        self.assertRedirects(response, reverse('repair_order_detail', args=[order.pk]))
        order.refresh_from_db()
        self.assertEqual(order.status, 'pending')
        self.assertEqual(order.pending_status, '')

    def test_admin_cannot_mark_a_non_ready_repair_complete(self):
        vehicle = Vehicle.objects.create(
            customer=self.customer,
            make='BMW',
            model='3 Series',
            year=2023,
            license_plate='READYNO',
        )
        order = RepairOrder.objects.create(
            vehicle=vehicle,
            assigned_tech=self.mechanic,
            status='in_progress',
            description='Test direct-complete guard',
            approved=True,
        )
        Invoice.objects.create(
            repair_order=order,
            service_amount='500.00',
            due_date=date.today() + timedelta(days=7),
            payment_status='paid',
        )
        self.client.force_login(self.admin)

        response = self.client.post(reverse('repair_order_finalize', args=[order.pk, 'complete']))

        self.assertRedirects(response, reverse('repair_order_detail', args=[order.pk]))
        order.refresh_from_db()
        self.assertEqual(order.status, 'in_progress')
        self.assertIsNone(order.date_completed)

    def test_admin_cannot_finalize_ready_or_complete_without_customer_approval(self):
        vehicle = Vehicle.objects.create(
            customer=self.customer,
            make='Mercedes',
            model='C-Class',
            year=2024,
            license_plate='APPROVAL',
        )
        order = RepairOrder.objects.create(
            vehicle=vehicle,
            assigned_tech=self.mechanic,
            status='in_progress',
            description='Test approval requirement for finalization',
            approved=False,
        )
        Invoice.objects.create(
            repair_order=order,
            service_amount='500.00',
            due_date=date.today() + timedelta(days=7),
            payment_status='paid',
        )
        self.client.force_login(self.admin)

        ready_response = self.client.post(reverse('repair_order_finalize', args=[order.pk, 'ready']))
        self.assertRedirects(ready_response, reverse('repair_order_detail', args=[order.pk]))
        order.refresh_from_db()
        self.assertEqual(order.status, 'in_progress')

        complete_response = self.client.post(reverse('repair_order_finalize', args=[order.pk, 'complete']))
        self.assertRedirects(complete_response, reverse('repair_order_detail', args=[order.pk]))
        order.refresh_from_db()
        self.assertEqual(order.status, 'in_progress')
        self.assertIsNone(order.date_completed)

    def test_admin_empty_collections_explain_the_next_action(self):
        self.customer.delete()
        self.mechanic.delete()
        self.client.force_login(self.admin)
        empty_pages = [
            ('customer_list', 'No customers yet'),
            ('vehicle_list', 'No vehicles on file'),
            ('repair_order_list', 'No repair orders yet'),
            ('appointment_list', 'No appointments scheduled'),
            ('invoice_list', 'No invoices yet'),
            ('parts_list', 'No parts in inventory'),
            ('service_list', 'No services in the catalogue'),
        ]

        for route_name, message in empty_pages:
            with self.subTest(page=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, message)
                self.assertContains(response, 'class="empty-state"')

            employee_response = self.client.get(reverse('employee_list'))
            self.assertContains(employee_response, self.admin.username)

        filtered_repairs = self.client.get(reverse('repair_order_list'), {'status': 'waiting'})
        filtered_invoices = self.client.get(reverse('invoice_list'), {'status': 'paid'})
        filtered_parts = self.client.get(reverse('parts_list'), {'low_stock': '1'})
        self.assertContains(filtered_repairs, 'Show all repair orders')
        self.assertContains(filtered_invoices, 'Show all invoices')
        self.assertContains(filtered_parts, 'No low-stock parts')
        self.assertContains(filtered_parts, 'Show all parts')

    def test_customer_and_mechanic_empty_states_are_role_appropriate(self):
        self.client.force_login(self.customer_user)
        customer_repairs = self.client.get(reverse('repair_order_list'))
        customer_appointments = self.client.get(reverse('appointment_list'))
        self.assertContains(customer_repairs, 'Request service')
        self.assertContains(customer_appointments, 'Book an appointment')

        self.client.force_login(self.mechanic)
        mechanic_dashboard = self.client.get(reverse('dashboard'))
        mechanic_repairs = self.client.get(reverse('repair_order_list'))
        self.assertContains(mechanic_dashboard, 'No jobs assigned yet')
        self.assertContains(mechanic_repairs, 'No jobs assigned yet')

    @patch('workshop.views.send_service_request_confirmation')
    def test_customer_service_request_shows_validation_and_success(self, send_confirmation):
        self.client.force_login(self.customer_user)
        invalid_response = self.client.post(reverse('appointment_create'), {
            'date_time': '',
            'service_desc': '',
        })
        self.assertIn('Please provide vehicle details for the appointment.', invalid_response.context['form'].non_field_errors())
        self.assertContains(invalid_response, 'role="alert"')
        self.assertFalse(Appointment.objects.exists())

        response = self.client.post(reverse('appointment_create'), {
            'date_time': '2030-05-20T10:30',
            'service_desc': 'Annual service',
            'vehicle_make': 'Toyota',
            'vehicle_model': 'Corolla',
            'vehicle_year': '2020',
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Service request submitted.')
        self.assertTrue(Appointment.objects.filter(customer=self.customer, service_desc='Annual service').exists())
        self.assertTrue(Vehicle.objects.filter(customer=self.customer, make='Toyota', model='Corolla').exists())
        send_confirmation.assert_called_once()

    def test_customer_cannot_book_another_customers_vehicle(self):
        other_customer = Customer.objects.create(
            first_name='Other',
            last_name='Owner',
            email='other-owner@example.com',
        )
        other_vehicle = Vehicle.objects.create(
            customer=other_customer,
            make='Honda',
            model='Civic',
            year=2021,
        )
        self.client.force_login(self.customer_user)

        response = self.client.post(reverse('appointment_create'), {
            'vehicle': other_vehicle.pk,
            'date_time': '2030-05-20T10:30',
            'service_desc': 'Annual service',
        })

        self.assertEqual(response.status_code, 200)
        self.assertIn('vehicle', response.context['form'].errors)
        self.assertFalse(Appointment.objects.filter(vehicle=other_vehicle).exists())

    def test_customers_cannot_open_admin_creation_or_staff_pages(self):
        self.client.force_login(self.customer_user)

        repair_order_page = self.client.get(reverse('repair_order_create'))
        staff_page = self.client.get(reverse('employee_list'))

        self.assertRedirects(repair_order_page, reverse('dashboard'))
        self.assertRedirects(staff_page, reverse('dashboard'))

    def test_form_return_links_work_without_browser_history(self):
        self.client.force_login(self.admin)
        form_pages = [
            ('customer_create', 'href="/customers/"'),
            ('vehicle_create', 'href="/vehicles/"'),
            ('repair_order_create', 'href="/repairs/"'),
            ('appointment_create', 'href="/appointments/"'),
            ('invoice_create', 'href="/invoices/"'),
            ('part_create', 'href="/parts/"'),
            ('service_create', 'href="/services/"'),
        ]

        for route_name, parent_link in form_pages:
            with self.subTest(page=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'javascript:history.back()')
                self.assertContains(response, parent_link)

    def test_customer_cannot_view_another_customers_profile_or_vehicle(self):
        other_customer = Customer.objects.create(
            first_name='Other',
            last_name='Customer',
            email='other@example.com',
            phone='0712345678',
            address='9 Other Road',
        )
        other_vehicle = Vehicle.objects.create(
            customer=other_customer,
            make='Ford',
            model='Focus',
            year=2022,
        )
        self.client.force_login(self.customer_user)

        customer_response = self.client.get(reverse('customer_detail', args=[other_customer.pk]))
        vehicle_response = self.client.get(reverse('vehicle_detail', args=[other_vehicle.pk]))

        self.assertRedirects(customer_response, reverse('dashboard'))
        self.assertRedirects(vehicle_response, reverse('dashboard'))

    def test_customer_can_approve_or_decline_their_own_repair(self):
        order = RepairOrder.objects.create(
            vehicle=Vehicle.objects.create(
                customer=self.customer,
                make='Honda',
                model='Civic',
                year=2021,
            ),
            description='Engine service',
            approved=False,
        )
        add_estimate_line(order)
        self.client.force_login(self.customer_user)

        approve_response = self.client.post(reverse('repair_order_customer_decision', args=[order.pk, 'approve']))
        self.assertRedirects(approve_response, reverse('repair_order_detail', args=[order.pk]))
        order.refresh_from_db()
        self.assertTrue(order.approved)

        decline_response = self.client.post(reverse('repair_order_customer_decision', args=[order.pk, 'decline']))
        self.assertRedirects(decline_response, reverse('repair_order_detail', args=[order.pk]))
        order.refresh_from_db()
        self.assertTrue(order.approved)

        decline_order = RepairOrder.objects.create(
            vehicle=order.vehicle,
            description='Transmission service',
            approved=False,
        )
        add_estimate_line(decline_order)
        decline_before_approval = self.client.post(
            reverse('repair_order_customer_decision', args=[decline_order.pk, 'decline']),
        )
        self.assertRedirects(decline_before_approval, reverse('repair_order_detail', args=[decline_order.pk]))
        decline_order.refresh_from_db()
        self.assertFalse(decline_order.approved)

    def test_customer_vehicle_page_offers_request_service_not_staff_creation(self):
        vehicle = Vehicle.objects.create(
            customer=self.customer,
            make='Honda',
            model='Civic',
            year=2021,
        )
        self.client.force_login(self.customer_user)

        response = self.client.get(reverse('vehicle_detail', args=[vehicle.pk]))

        self.assertContains(response, 'Request service')
        self.assertNotContains(response, 'Create repair order')
