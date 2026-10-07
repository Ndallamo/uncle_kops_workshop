from django import forms
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from PIL import Image, UnidentifiedImageError
from .currency import format_rand
from .models import Customer, Vehicle, RepairOrder, RepairDocument, RepairEstimateLine, LaborLine, PartsLine, Invoice, Appointment, Part, ServiceItem


class CustomerForm(forms.ModelForm):
    class Meta:
        model  = Customer
        fields = ['first_name', 'last_name', 'email', 'phone', 'address', 'notes']
        widgets = {
            'first_name': forms.TextInput(attrs={'placeholder': 'e.g. Alex'}),
            'last_name': forms.TextInput(attrs={'placeholder': 'e.g. Smith'}),
            'email': forms.EmailInput(attrs={'placeholder': 'e.g. alex@example.com'}),
            'phone': forms.TextInput(attrs={'placeholder': 'e.g. 071 234 5678'}),
            'address': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Street address, suburb, city and postal code'}),
            'notes': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Optional customer preferences or contact notes'}),
        }
        help_texts = {
            'first_name': 'Enter the customer\'s first name.',
            'last_name': 'Enter the customer\'s surname.',
            'email': 'Use a valid email address for receipts and communication.',
            'phone': 'Enter a phone number where the customer can be reached.',
            'address': 'Enter the full address, including suburb and postal code.',
            'notes': 'Optional: add useful customer or communication notes.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['phone'].required = True
        self.fields['address'].required = True


class VehicleForm(forms.ModelForm):
    class Meta:
        model  = Vehicle
        fields = ['customer', 'make', 'model', 'year', 'vin', 'license_plate', 'color', 'mileage', 'service_plan', 'recent_service_history', 'notes']
        widgets = {
            'make': forms.TextInput(attrs={'placeholder': 'e.g. Toyota'}),
            'model': forms.TextInput(attrs={'placeholder': 'e.g. Corolla'}),
            'year': forms.NumberInput(attrs={'placeholder': 'e.g. 2018'}),
            'vin': forms.TextInput(attrs={'placeholder': '17-character vehicle identification number'}),
            'license_plate': forms.TextInput(attrs={'placeholder': 'e.g. ABC 123 GP'}),
            'color': forms.TextInput(attrs={'placeholder': 'e.g. Silver'}),
            'mileage': forms.NumberInput(attrs={'placeholder': 'Current odometer reading'}),
            'notes': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Optional notes about this vehicle'}),
            'recent_service_history': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Recent work, dates and approximate mileage'}),
            'service_plan': forms.TextInput(attrs={'placeholder': 'e.g. Basic maintenance plan - oil + brakes'})
        }
        help_texts = {
            'customer': 'Select the owner of this vehicle.',
            'make': 'Enter the manufacturer.',
            'model': 'Enter the vehicle model.',
            'year': 'Enter the model year using four digits.',
            'vin': 'Optional; enter the 17-character VIN if available.',
            'license_plate': 'Optional; enter the vehicle registration number.',
            'color': 'Optional; enter the vehicle color.',
            'mileage': 'Enter the current odometer reading in kilometers.',
            'service_plan': 'Optional; enter the customer\'s maintenance plan.',
            'recent_service_history': 'Optional; summarize recent services, dates and mileage.',
            'notes': 'Optional notes relevant to this vehicle.',
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['customer'].empty_label = 'Choose customer'
        if user is not None:
            profile = getattr(user, 'userprofile', None)
            if profile and profile.role == 'customer':
                customer = Customer.objects.filter(email=user.email).first()
                if customer:
                    self.fields['customer'].widget = forms.HiddenInput()
                    self.fields['customer'].initial = customer.pk
                    self.fields['customer'].help_text = 'This vehicle will be saved to your customer account.'


class RepairOrderForm(forms.ModelForm):
    class Meta:
        model  = RepairOrder
        fields = ['vehicle', 'assigned_tech', 'status', 'description', 'internal_notes', 'mileage_in', 'approved']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Describe the customer complaint and work requested'}),
            'internal_notes': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Optional notes for workshop staff; not customer-facing'}),
            'mileage_in': forms.NumberInput(attrs={'placeholder': 'Odometer reading when vehicle arrived'}),
        }
        help_texts = {
            'vehicle': 'Choose the vehicle being brought in for repair.',
            'assigned_tech': 'Optional; choose the mechanic responsible for this repair.',
            'status': 'Choose the repair stage that best matches the current work.',
            'description': 'Record the customer complaint and the work requested.',
            'internal_notes': 'Optional workshop-only notes. Do not include these in customer-facing details.',
            'mileage_in': 'Enter the odometer reading at vehicle drop-off, in kilometers.',
            'approved': 'Tick only when the customer has approved the quoted work.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['vehicle'].empty_label = 'Choose vehicle'
        self.fields['assigned_tech'].empty_label = 'Choose technician'
        self.fields['assigned_tech'].queryset = User.objects.filter(
            userprofile__role='mechanic'
        ).order_by('first_name', 'last_name', 'username')


class LaborLineForm(forms.ModelForm):
    total_amount = forms.DecimalField(
        required=False,
        disabled=True,
        label='Total amount',
        decimal_places=2,
        max_digits=10,
        initial=None,
        widget=forms.NumberInput(attrs={'readonly': 'readonly'})
    )

    class Meta:
        model  = LaborLine
        fields = ['service_item', 'hours', 'rate', 'notes', 'total_amount']
        widgets = {
            'hours': forms.NumberInput(attrs={'placeholder': 'e.g. 1.5', 'min': '0.01', 'step': '0.01'}),
            'rate': forms.NumberInput(attrs={'readonly': 'readonly'}),
            'notes': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Optional details about this labor'}),
        }
        help_texts = {
            'service_item': 'Choose the labor or service performed.',
            'hours': 'Enter labor time in hours; decimals are allowed (for example, 1.5).',
            'rate': 'Uses the selected service item\'s admin-set labor rate.',
            'notes': 'Optional details about the work performed.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['service_item'].empty_label = 'Choose service item'
        self.fields['service_item'].label = 'Service item'
        self.fields['service_item'].label_from_instance = lambda item: f'{item.name} ({format_rand(item.labor_rate)}/hour)'
        self.fields['rate'].required = False
        self.fields['rate'].label = 'Rate (R/hour)'
        self.fields['total_amount'].label = 'Total amount (R)'
        self.fields['hours'].min_value = Decimal('0.01')
        self.fields['rate'].min_value = Decimal('0.00')
        self.fields['hours'].validators.append(MinValueValidator(Decimal('0.01')))
        self.fields['rate'].validators.append(MinValueValidator(Decimal('0.00')))
        self.fields['total_amount'].initial = None
        if self.data:
            try:
                hours = Decimal(self.data.get('hours', '0') or '0')
                rate = Decimal(self.data.get('rate', '0') or '0')
                self.fields['total_amount'].initial = (hours * rate).quantize(
                    Decimal('0.01'),
                    rounding=ROUND_HALF_UP,
                )
            except (InvalidOperation, TypeError, ValueError):
                self.fields['total_amount'].initial = None

    def clean(self):
        cleaned_data = super().clean()
        service_item = cleaned_data.get('service_item')
        if service_item:
            cleaned_data['rate'] = service_item.labor_rate
        return cleaned_data


class PartsLineForm(forms.ModelForm):
    class Meta:
        model  = PartsLine
        fields = ['part', 'quantity', 'unit_price']
        widgets = {
            'quantity': forms.NumberInput(attrs={'placeholder': 'Number of units used', 'min': '1', 'step': '1'}),
            'unit_price': forms.NumberInput(attrs={'readonly': 'readonly'}),
        }
        help_texts = {
            'part': 'Choose the inventory part used for this repair.',
            'quantity': 'Enter the number of units used.',
            'unit_price': 'Uses the selected part\'s admin-set selling price.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['part'].empty_label = 'Choose part'
        self.fields['part'].label = 'Part'
        self.fields['part'].label_from_instance = lambda part: f'{part.name} ({format_rand(part.sell_price)})'
        self.fields['unit_price'].required = False
        self.fields['unit_price'].label = 'Unit price (R)'
        self.fields['quantity'].min_value = 1
        self.fields['unit_price'].min_value = Decimal('0.00')
        self.fields['quantity'].validators.append(MinValueValidator(1))
        self.fields['unit_price'].validators.append(MinValueValidator(Decimal('0.00')))

    def clean(self):
        cleaned_data = super().clean()
        part = cleaned_data.get('part')
        if part:
            cleaned_data['unit_price'] = part.sell_price
        return cleaned_data


class InvoiceForm(forms.ModelForm):
    repair_order = forms.ModelChoiceField(
        queryset=RepairOrder.objects.all(),
        empty_label='Choose repair/vehicle',
        label='Repair order',
    )
    service_amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        disabled=True,
        label='Service amount (R)',
    )
    class Meta:
        model  = Invoice
        fields = ['repair_order', 'service_amount', 'issue_date', 'due_date', 'discount', 'tax_rate', 'notes']
        widgets = {
            'issue_date': forms.DateInput(attrs={'type': 'date'}),
            'due_date':   forms.DateInput(attrs={'type': 'date'}),
            'notes':      forms.Textarea(attrs={'rows': 3, 'placeholder': 'Optional payment or invoice notes'}),
        }
        help_texts = {
            'discount': 'Enter a discount amount in currency; use 0 if there is no discount.',
            'tax_rate': 'Enter the tax percentage (for example, 15 for 15%); use 0 if not applicable.',
            'notes': 'Optional information to include with this invoice.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        available_orders = RepairOrder.objects.filter(
            invoice__isnull=True,
            approved=True,
        ).exclude(status='cancelled')
        if self.instance.pk:
            available_orders |= RepairOrder.objects.filter(pk=self.instance.repair_order_id)
        self.fields['repair_order'].queryset = available_orders
        self.fields['service_amount'].label = 'Service amount (R)'
        self.fields['discount'].label = 'Discount (R)'
        if self.instance.pk:
            self.fields['repair_order'].disabled = True
        if not self.instance.pk and self.initial.get('repair_order'):
            repair_order = self.initial['repair_order']
            if hasattr(repair_order, 'grand_total'):
                self.fields['service_amount'].initial = repair_order.grand_total
        self.fields['discount'].min_value = 0
        self.fields['tax_rate'].min_value = 0
        self.fields['discount'].validators.append(MinValueValidator(Decimal('0.00')))
        self.fields['tax_rate'].validators.append(MinValueValidator(Decimal('0.00')))
        self.fields['repair_order'].help_text = 'Select the repair order this invoice is for.'
        self.fields['service_amount'].help_text = 'Calculated from the labor and parts on this repair order.'
        self.fields['issue_date'].help_text = 'Choose the date the invoice is issued.'
        self.fields['due_date'].help_text = 'Choose the date payment is due.'

    def clean_service_amount(self):
        value = self.cleaned_data.get('service_amount')
        if value is None:
            return value
        return max(value, 0)

    def clean(self):
        cleaned_data = super().clean()
        repair_order = cleaned_data.get('repair_order')
        if repair_order:
            cleaned_data['service_amount'] = repair_order.grand_total
        discount = cleaned_data.get('discount')
        service_amount = cleaned_data.get('service_amount')
        if discount is not None and service_amount is not None and discount > service_amount:
            self.add_error('discount', 'Discount cannot exceed the repair order amount.')
        issue_date = cleaned_data.get('issue_date')
        due_date = cleaned_data.get('due_date')
        if issue_date and due_date and due_date < issue_date:
            self.add_error('due_date', 'Due date cannot be before the invoice issue date.')
        return cleaned_data

    def clean_discount(self):
        value = self.cleaned_data.get('discount')
        if value is not None and value < 0:
            raise forms.ValidationError('Discount cannot be negative.')
        return value

    def clean_tax_rate(self):
        value = self.cleaned_data.get('tax_rate')
        if value is not None and value < 0:
            raise forms.ValidationError('Tax rate cannot be negative.')
        return value


class InvoicePaymentForm(forms.Form):
    amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('0.01'),
        label='Amount received (R)',
    )
    payment_method = forms.ChoiceField(choices=Invoice.METHOD_CHOICES, label='Payment method')
    reference = forms.CharField(max_length=100, required=False, label='Receipt or transaction reference')
    notes = forms.CharField(
        required=False,
        label='Notes',
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Optional reconciliation details'}),
    )

    def __init__(self, *args, invoice, **kwargs):
        self.invoice = invoice
        super().__init__(*args, **kwargs)

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount > self.invoice.balance_due:
            raise forms.ValidationError('The amount received cannot exceed the outstanding balance.')
        return amount


class AppointmentForm(forms.ModelForm):
    vehicle_text = forms.CharField(
        label='Vehicle details',
        required=False,
        help_text='Type your vehicle make/model if you are not selecting an existing vehicle.',
        widget=forms.TextInput(attrs={'placeholder': 'e.g. Toyota Corolla 2018'})
    )
    vehicle_make = forms.CharField(max_length=50, required=False, label='Make', help_text='Enter the vehicle manufacturer, for example Toyota.')
    vehicle_model = forms.CharField(max_length=50, required=False, label='Model', help_text='Enter the model, for example Corolla.')
    vehicle_year = forms.IntegerField(required=False, label='Year', min_value=1900, max_value=2100, help_text='Enter the four-digit model year.')
    vehicle_vin = forms.CharField(max_length=17, required=False, label='VIN', help_text='Optional; enter the 17-character vehicle identification number.')
    vehicle_license_plate = forms.CharField(max_length=20, required=False, label='License plate', help_text='Optional; enter the vehicle registration number.')
    vehicle_color = forms.CharField(max_length=30, required=False, label='Color', help_text='Optional; enter the vehicle color.')
    vehicle_mileage = forms.IntegerField(required=False, label='Mileage', min_value=0, help_text='Enter the current odometer reading in kilometers.')
    vehicle_service_plan = forms.CharField(max_length=200, required=False, label='Service plan', help_text='Optional; enter the customer\'s maintenance plan.')
    vehicle_recent_service_history = forms.CharField(
        required=False,
        label='Recent service history',
        help_text='Optional; list recent work, dates and approximate mileage.',
        widget=forms.Textarea(attrs={'rows': 3})
    )
    vehicle_notes = forms.CharField(
        required=False,
        label='Vehicle notes',
        help_text='Optional notes relevant to this vehicle.',
        widget=forms.Textarea(attrs={'rows': 3})
    )
    assigned_mechanic = forms.ModelChoiceField(
        queryset=User.objects.filter(userprofile__role='mechanic'),
        required=False,
        label='Assigned mechanic',
        empty_label='--- No mechanic assigned ---',
        help_text='Staff only; select a mechanic if one has already been assigned.'
    )
    assignment_status = forms.ChoiceField(
        choices=Appointment.ASSIGNMENT_CHOICES,
        required=False,
        label='Assignment status',
        initial='pending',
        help_text='Staff only; choose the current assignment state.'
    )

    class Meta:
        model  = Appointment
        # remove `confirmed` checkbox from the form as requested
        fields = [
            'customer', 'vehicle', 'vehicle_text',
            'vehicle_make', 'vehicle_model', 'vehicle_year', 'vehicle_vin', 'vehicle_license_plate',
            'vehicle_color', 'vehicle_mileage', 'vehicle_service_plan', 'vehicle_recent_service_history',
            'vehicle_notes', 'date_time', 'service_desc', 'assigned_mechanic', 'assignment_status', 'notes'
        ]
        widgets = {
            'date_time':                    forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'service_desc': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Describe the problem or service requested'}),
            'notes': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Optional additional information for the workshop'}),
            'vehicle_recent_service_history': forms.Textarea(attrs={'rows': 3}),
            'vehicle_notes':                forms.Textarea(attrs={'rows': 3}),
        }
        help_texts = {
            'customer': 'Choose the customer requesting the appointment.',
            'vehicle': 'Choose a saved vehicle, or enter vehicle details below if it is not listed.',
            'date_time': 'Choose the requested appointment date and time.',
            'service_desc': 'Describe the issue or service the customer wants done.',
            'notes': 'Optional details that may help the workshop prepare.',
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['customer'].empty_label = 'Choose customer'
        self.fields['vehicle'].empty_label = 'Choose vehicle'
        self.fields['assigned_mechanic'].empty_label = 'Choose mechanic'
        self.fields['vehicle_text'].widget.attrs['placeholder'] = 'e.g. Toyota Corolla 2018'
        self.fields['vehicle_make'].widget.attrs['placeholder'] = 'e.g. Toyota'
        self.fields['vehicle_model'].widget.attrs['placeholder'] = 'e.g. Corolla'
        self.fields['vehicle_year'].widget.attrs['placeholder'] = 'e.g. 2018'
        self.fields['vehicle_vin'].widget.attrs['placeholder'] = '17-character VIN, if available'
        self.fields['vehicle_license_plate'].widget.attrs['placeholder'] = 'e.g. ABC 123 GP'
        self.fields['vehicle_color'].widget.attrs['placeholder'] = 'e.g. Silver'
        self.fields['vehicle_mileage'].widget.attrs['placeholder'] = 'Current odometer reading'
        self.fields['vehicle_service_plan'].widget.attrs['placeholder'] = 'e.g. Basic maintenance plan'
        self.fields['vehicle_recent_service_history'].widget.attrs['placeholder'] = 'Recent work, dates and mileage'
        self.fields['vehicle_notes'].widget.attrs['placeholder'] = 'Optional vehicle notes'
        if user is not None:
            profile = getattr(user, 'userprofile', None)
            if profile and profile.role == 'customer':
                customer = Customer.objects.filter(email=user.email).first()
                if customer:
                    self.fields['customer'].widget = forms.HiddenInput()
                    self.fields['customer'].initial = customer.pk
                    self.fields['customer'].required = False
                    self.fields['vehicle'].queryset = Vehicle.objects.filter(customer=customer)
                else:
                    self.fields['vehicle'].queryset = Vehicle.objects.none()
                self.fields['vehicle'].widget = forms.HiddenInput()
                self.fields['vehicle'].required = False
                self.fields['vehicle'].help_text = 'Customers can type vehicle details instead of selecting a saved vehicle.'
                self.fields['vehicle_text'].widget = forms.HiddenInput()
                self.fields['vehicle_text'].required = False
                self.fields['assigned_mechanic'].widget = forms.HiddenInput()
                self.fields['assigned_mechanic'].required = False
                self.fields['assignment_status'].widget = forms.HiddenInput()
                self.fields['assignment_status'].required = False
            else:
                for field_name in [
                    'vehicle_text', 'vehicle_make', 'vehicle_model', 'vehicle_year', 'vehicle_vin',
                    'vehicle_license_plate', 'vehicle_color', 'vehicle_mileage', 'vehicle_service_plan',
                    'vehicle_recent_service_history', 'vehicle_notes'
                ]:
                    self.fields[field_name].widget = forms.HiddenInput()
                    self.fields[field_name].required = False
                if profile and profile.role == 'mechanic' and self.instance.pk:
                    for field_name in ['customer', 'vehicle', 'date_time', 'service_desc', 'assigned_mechanic']:
                        self.fields[field_name].disabled = True

    def manual_vehicle_data(self):
        return {
            'make': (self.cleaned_data.get('vehicle_make') or '').strip(),
            'model': (self.cleaned_data.get('vehicle_model') or '').strip(),
            'year': self.cleaned_data.get('vehicle_year') or 0,
            'vin': (self.cleaned_data.get('vehicle_vin') or '').strip(),
            'license_plate': (self.cleaned_data.get('vehicle_license_plate') or '').strip(),
            'color': (self.cleaned_data.get('vehicle_color') or '').strip(),
            'mileage': self.cleaned_data.get('vehicle_mileage') or 0,
            'service_plan': (self.cleaned_data.get('vehicle_service_plan') or '').strip(),
            'recent_service_history': (self.cleaned_data.get('vehicle_recent_service_history') or '').strip(),
            'notes': (self.cleaned_data.get('vehicle_notes') or '').strip(),
        }

    def clean(self):
        cleaned_data = super().clean()
        vehicle = cleaned_data.get('vehicle')
        assigned_mechanic = cleaned_data.get('assigned_mechanic')
        assignment_status = cleaned_data.get('assignment_status') or 'pending'
        date_time = cleaned_data.get('date_time')
        manual_vehicle = self.manual_vehicle_data()
        has_manual_vehicle = any(value not in (None, '', 0) for value in manual_vehicle.values())
        customer = cleaned_data.get('customer')
        if vehicle and customer and vehicle.customer_id != customer.pk:
            self.add_error('vehicle', 'The selected vehicle does not belong to the selected customer.')
        if not vehicle and not has_manual_vehicle:
            raise forms.ValidationError('Please provide vehicle details for the appointment.')
        if assignment_status == 'accepted' and Appointment.has_schedule_conflict(
            mechanic=assigned_mechanic,
            date_time=date_time,
            duration=self.instance.duration,
            exclude_pk=self.instance.pk,
        ):
            self.add_error('assigned_mechanic', 'This mechanic already has an accepted appointment during that time.')
        return cleaned_data


class PartForm(forms.ModelForm):
    class Meta:
        model  = Part
        fields = ['name', 'part_number', 'description', 'cost_price', 'sell_price', 'stock_qty', 'reorder_level', 'supplier']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'e.g. Oil filter'}),
            'part_number': forms.TextInput(attrs={'placeholder': 'Manufacturer or workshop part number'}),
            'description': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Part details, fitment or specifications'}),
            'cost_price': forms.NumberInput(attrs={'placeholder': 'Purchase cost per unit'}),
            'sell_price': forms.NumberInput(attrs={'placeholder': 'Customer price per unit'}),
            'stock_qty': forms.NumberInput(attrs={'placeholder': 'Units currently in stock'}),
            'reorder_level': forms.NumberInput(attrs={'placeholder': 'Stock level that triggers reorder'}),
            'supplier': forms.TextInput(attrs={'placeholder': 'Supplier name'}),
        }
        help_texts = {
            'name': 'Enter the part name used to find it in inventory.',
            'part_number': 'Optional; enter the manufacturer or internal part number.',
            'description': 'Optional; include specifications or compatible vehicles.',
            'cost_price': 'Enter your purchase cost for one unit.',
            'sell_price': 'Enter the price charged to customers for one unit.',
            'stock_qty': 'Enter the number of units currently available.',
            'reorder_level': 'A low-stock alert appears when quantity reaches this number.',
            'supplier': 'Optional; enter the supplier business name.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['cost_price'].label = 'Cost price (R)'
        self.fields['sell_price'].label = 'Sell price (R)'
        self.fields['cost_price'].validators.append(MinValueValidator(Decimal('0.00')))
        self.fields['sell_price'].validators.append(MinValueValidator(Decimal('0.00')))


class ServiceItemForm(forms.ModelForm):
    class Meta:
        model  = ServiceItem
        fields = ['name', 'description', 'labor_hours', 'labor_rate']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'e.g. Standard oil change'}),
            'description': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Describe what this service includes'}),
            'labor_hours': forms.NumberInput(attrs={'placeholder': 'Estimated hours'}),
            'labor_rate': forms.NumberInput(attrs={'placeholder': 'Charge per labor hour'}),
        }
        help_texts = {
            'name': 'Enter the service name shown in the labor list.',
            'description': 'Optional; explain what work is included in this service.',
            'labor_hours': 'Enter the standard labor time in hours; decimals are allowed.',
            'labor_rate': 'Enter the charge per labor hour.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['labor_rate'].label = 'Labor rate (R/hour)'
        self.fields['labor_hours'].validators.append(MinValueValidator(Decimal('0.00')))
        self.fields['labor_rate'].validators.append(MinValueValidator(Decimal('0.00')))


class RepairDocumentForm(forms.ModelForm):
    class Meta:
        model = RepairDocument
        fields = ['title', 'file', 'customer_visible']
        widgets = {
            'title': forms.TextInput(attrs={'placeholder': 'e.g. Brake inspection photo'}),
        }

    def clean_file(self):
        uploaded_file = self.cleaned_data['file']
        allowed_extensions = {'.jpg', '.jpeg', '.png', '.pdf'}
        extension = uploaded_file.name.lower().rsplit('.', 1)[-1] if '.' in uploaded_file.name else ''
        extension = f'.{extension}'
        if extension not in allowed_extensions:
            raise forms.ValidationError('Upload a JPG, PNG or PDF file.')
        if uploaded_file.size > 10 * 1024 * 1024:
            raise forms.ValidationError('Files must be 10 MB or smaller.')

        uploaded_file.seek(0)
        if extension == '.pdf':
            if not uploaded_file.read(5).startswith(b'%PDF-'):
                uploaded_file.seek(0)
                raise forms.ValidationError('The uploaded PDF file is not a valid PDF document.')
        else:
            try:
                image = Image.open(uploaded_file)
                if image.format not in {'JPEG', 'PNG'}:
                    raise forms.ValidationError('The image content must be JPEG or PNG.')
                image.verify()
            except (UnidentifiedImageError, OSError, ValueError) as exc:
                raise forms.ValidationError('The uploaded image file is invalid.') from exc
            finally:
                uploaded_file.seek(0)
        return uploaded_file


class RepairEstimateLineForm(forms.ModelForm):
    class Meta:
        model = RepairEstimateLine
        fields = ['line_type', 'service_item', 'part', 'quantity', 'unit_price', 'notes']
        widgets = {
            'quantity': forms.NumberInput(attrs={'step': '0.01', 'min': '0.01'}),
            'unit_price': forms.NumberInput(attrs={'readonly': 'readonly'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['unit_price'].required = False
        self.fields['unit_price'].label = 'Unit price (R)'

    def clean(self):
        cleaned_data = super().clean()
        line_type = cleaned_data.get('line_type')
        service_item = cleaned_data.get('service_item')
        part = cleaned_data.get('part')
        if line_type == 'labor':
            if not service_item:
                self.add_error('service_item', 'Choose a service for labor estimates.')
            if part:
                self.add_error('part', 'Labor estimates cannot include a part.')
            cleaned_data['unit_price'] = service_item.labor_rate if service_item else cleaned_data.get('unit_price')
        elif line_type == 'part':
            if not part:
                self.add_error('part', 'Choose a part for parts estimates.')
            if service_item:
                self.add_error('service_item', 'Parts estimates cannot include a labor service.')
            cleaned_data['unit_price'] = part.sell_price if part else cleaned_data.get('unit_price')
        return cleaned_data


class EmployeeForm(UserCreationForm):
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=30, required=True)
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'password1', 'password2']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].help_text = 'Use the username this employee will enter to sign in.'
        self.fields['email'].help_text = 'Enter a valid, unique work email address.'
        self.fields['first_name'].help_text = 'Enter the employee\'s first name.'
        self.fields['last_name'].help_text = 'Enter the employee\'s surname.'

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('A user with that email already exists.')
        return email


class EmployeeEditForm(forms.ModelForm):
    role = forms.ChoiceField(
        choices=[('mechanic', 'Mechanic'), ('admin', 'Admin')],
        help_text='Choose the employee access role.',
    )

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'username', 'is_active']
        help_texts = {
            'first_name': 'Enter the employee\'s first name.',
            'last_name': 'Enter the employee\'s surname.',
            'email': 'Enter a valid, unique work email address.',
            'username': 'This is the username the employee enters to sign in.',
        }

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('A user with that email already exists.')
        return email


class UserRegistrationForm(UserCreationForm):
    ROLE_CHOICES = [
        ('customer', 'Customer'),
    ]

    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=30, required=True)
    phone = forms.CharField(max_length=20, required=False)
    address = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}), required=False)
    role = forms.ChoiceField(choices=ROLE_CHOICES, required=True, help_text='Choose Customer to create a customer account.')

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'phone', 'address', 'role', 'password1', 'password2']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].help_text = 'Choose a username to use when signing in.'
        self.fields['email'].help_text = 'Enter a valid email address for account verification and communication.'
        self.fields['first_name'].help_text = 'Enter your first name.'
        self.fields['last_name'].help_text = 'Enter your surname.'
        self.fields['phone'].help_text = 'Optional; provide a phone number the workshop can use to contact you.'
        self.fields['phone'].widget.attrs['placeholder'] = 'e.g. 071 234 5678'
        self.fields['address'].help_text = 'Optional; include street, suburb, city and postal code.'
        self.fields['address'].widget.attrs['placeholder'] = 'Street address, suburb, city and postal code'
        self.fields['username'].widget.attrs['placeholder'] = 'Choose a unique username'
        self.fields['email'].widget.attrs['placeholder'] = 'Enter your email address'
        self.fields['first_name'].widget.attrs['placeholder'] = 'Enter your First name'
        self.fields['last_name'].widget.attrs['placeholder'] = 'Enter your Surname'
        self.fields['password1'].widget.attrs['placeholder'] = 'At least 8 characters'
        self.fields['password2'].widget.attrs['placeholder'] = 'Re-enter your password'

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('A user with that email already exists.')
        return email
