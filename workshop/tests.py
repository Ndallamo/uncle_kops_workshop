from decimal import Decimal

from django.test import TestCase

from workshop.forms import InvoiceForm


class InvoiceFormTests(TestCase):
    def test_invoice_form_includes_service_amount_field(self):
        form = InvoiceForm()
        self.assertIn('service_amount', form.fields)
        self.assertEqual(form.fields['service_amount'].label, 'Service amount')
        self.assertEqual(form.fields['repair_order'].empty_label, 'Choose repair/vehicle')
        self.assertEqual(form.fields['payment_method'].choices[0][1], 'Choose method')
