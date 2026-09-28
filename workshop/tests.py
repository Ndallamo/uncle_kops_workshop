from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from workshop.forms import InvoiceForm, LaborLineForm, PartsLineForm
from workshop.models import UserProfile


class InvoiceFormTests(TestCase):
    def test_invoice_form_includes_service_amount_field(self):
        form = InvoiceForm()
        self.assertIn('service_amount', form.fields)
        self.assertEqual(form.fields['service_amount'].label, 'Service amount')
        self.assertEqual(form.fields['repair_order'].empty_label, 'Choose repair/vehicle')
        self.assertEqual(form.fields['payment_method'].choices[0][1], 'Choose method')

    def test_line_item_forms_use_descriptive_empty_labels(self):
        labor_form = LaborLineForm()
        parts_form = PartsLineForm()

        self.assertEqual(labor_form.fields['service_item'].empty_label, 'Choose service item')
        self.assertIn('total_amount', labor_form.fields)
        self.assertEqual(parts_form.fields['part'].empty_label, 'Choose part')


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


class AuthUrlTests(TestCase):
    def test_password_reset_routes_exist(self):
        self.assertEqual(reverse('forgot_password'), '/forgot-password/')
        self.assertEqual(reverse('reset_password'), '/reset-password/')


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
        self.assertContains(response, 'Page not found')


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
