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

<<<<<<< HEAD
<<<<<<< HEAD
    def test_line_item_forms_use_descriptive_empty_labels(self):
        labor_form = LaborLineForm()
        parts_form = PartsLineForm()

        self.assertEqual(labor_form.fields['service_item'].empty_label, 'Choose item')
        self.assertIn('total_amount', labor_form.fields)
        self.assertEqual(parts_form.fields['part'].empty_label, 'Choose Part')


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
=======
=======
>>>>>>> 1d39633f91473004feaf8eca50b62c2897103b05

class AuthUrlTests(TestCase):
    def test_password_reset_routes_exist(self):
        self.assertEqual(reverse('forgot_password'), '/forgot-password/')
        self.assertEqual(reverse('reset_password'), '/reset-password/')
<<<<<<< HEAD
>>>>>>> a669431cca29cb08f0c0d7198d8c80163a6f03f0
=======
>>>>>>> 1d39633f91473004feaf8eca50b62c2897103b05
