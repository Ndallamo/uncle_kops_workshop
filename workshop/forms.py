from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Customer, Vehicle, RepairOrder, LaborLine, PartsLine, Invoice, Appointment, Part, ServiceItem


class CustomerForm(forms.ModelForm):
    class Meta:
        model  = Customer
        fields = ['first_name', 'last_name', 'email', 'phone', 'address', 'notes']
        widgets = {
            'address': forms.Textarea(attrs={'rows': 3}),
            'notes':   forms.Textarea(attrs={'rows': 3}),
        }


class VehicleForm(forms.ModelForm):
    class Meta:
        model  = Vehicle
        fields = ['customer', 'make', 'model', 'year', 'vin', 'license_plate', 'color', 'mileage', 'service_plan', 'recent_service_history', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3}),
            'recent_service_history': forms.Textarea(attrs={'rows': 4}),
            'service_plan': forms.TextInput(attrs={'placeholder': 'e.g. Basic maintenance plan - oil + brakes'})
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
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
            'description':    forms.Textarea(attrs={'rows': 4}),
            'internal_notes': forms.Textarea(attrs={'rows': 3}),
        }


class LaborLineForm(forms.ModelForm):
    class Meta:
        model  = LaborLine
        fields = ['service_item', 'hours', 'rate', 'notes']


class PartsLineForm(forms.ModelForm):
    class Meta:
        model  = PartsLine
        fields = ['part', 'quantity', 'unit_price']


class InvoiceForm(forms.ModelForm):
    class Meta:
        model  = Invoice
        fields = ['repair_order', 'issue_date', 'due_date', 'payment_status', 'payment_method', 'discount', 'tax_rate', 'notes']
        widgets = {
            'issue_date': forms.DateInput(attrs={'type': 'date'}),
            'due_date':   forms.DateInput(attrs={'type': 'date'}),
            'notes':      forms.Textarea(attrs={'rows': 3}),
        }


class AppointmentForm(forms.ModelForm):
    vehicle_text = forms.CharField(
        label='Vehicle details',
        required=False,
        help_text='Type your vehicle make/model if you are not selecting an existing vehicle.',
        widget=forms.TextInput(attrs={'placeholder': 'e.g. Toyota Corolla 2018'})
    )
    vehicle_make = forms.CharField(max_length=50, required=False, label='Make')
    vehicle_model = forms.CharField(max_length=50, required=False, label='Model')
    vehicle_year = forms.IntegerField(required=False, label='Year', min_value=1900, max_value=2100)
    vehicle_vin = forms.CharField(max_length=17, required=False, label='VIN')
    vehicle_license_plate = forms.CharField(max_length=20, required=False, label='License plate')
    vehicle_color = forms.CharField(max_length=30, required=False, label='Color')
    vehicle_mileage = forms.IntegerField(required=False, label='Mileage', min_value=0)
    vehicle_service_plan = forms.CharField(max_length=200, required=False, label='Service plan')
    vehicle_recent_service_history = forms.CharField(
        required=False,
        label='Recent service history',
        widget=forms.Textarea(attrs={'rows': 3})
    )
    vehicle_notes = forms.CharField(
        required=False,
        label='Vehicle notes',
        widget=forms.Textarea(attrs={'rows': 3})
    )

    class Meta:
        model  = Appointment
        # remove `confirmed` checkbox from the form as requested
        fields = [
            'customer', 'vehicle', 'vehicle_text',
            'vehicle_make', 'vehicle_model', 'vehicle_year', 'vehicle_vin', 'vehicle_license_plate',
            'vehicle_color', 'vehicle_mileage', 'vehicle_service_plan', 'vehicle_recent_service_history',
            'vehicle_notes', 'date_time', 'service_desc', 'notes'
        ]
        widgets = {
            'date_time':                    forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'service_desc':                 forms.Textarea(attrs={'rows': 3}),
            'notes':                        forms.Textarea(attrs={'rows': 3}),
            'vehicle_recent_service_history': forms.Textarea(attrs={'rows': 3}),
            'vehicle_notes':                forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            profile = getattr(user, 'userprofile', None)
            if profile and profile.role == 'customer':
                customer = Customer.objects.filter(email=user.email).first()
                if customer:
                    self.fields['customer'].widget = forms.HiddenInput()
                    self.fields['customer'].initial = customer.pk
                    self.fields['customer'].required = False
                self.fields['vehicle'].widget = forms.HiddenInput()
                self.fields['vehicle'].required = False
                self.fields['vehicle'].help_text = 'Customers can type vehicle details instead of selecting a saved vehicle.'
                self.fields['vehicle_text'].widget = forms.HiddenInput()
                self.fields['vehicle_text'].required = False
            else:
                for field_name in [
                    'vehicle_text', 'vehicle_make', 'vehicle_model', 'vehicle_year', 'vehicle_vin',
                    'vehicle_license_plate', 'vehicle_color', 'vehicle_mileage', 'vehicle_service_plan',
                    'vehicle_recent_service_history', 'vehicle_notes'
                ]:
                    self.fields[field_name].widget = forms.HiddenInput()
                    self.fields[field_name].required = False

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
        manual_vehicle = self.manual_vehicle_data()
        has_manual_vehicle = any(value not in (None, '', 0) for value in manual_vehicle.values())
        if not vehicle and not has_manual_vehicle:
            raise forms.ValidationError('Please provide vehicle details for the appointment.')
        return cleaned_data


class PartForm(forms.ModelForm):
    class Meta:
        model  = Part
        fields = ['name', 'part_number', 'description', 'cost_price', 'sell_price', 'stock_qty', 'reorder_level', 'supplier']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }


class ServiceItemForm(forms.ModelForm):
    class Meta:
        model  = ServiceItem
        fields = ['name', 'description', 'labor_hours', 'labor_rate']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }


class EmployeeForm(UserCreationForm):
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=30, required=True)
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'password1', 'password2']

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('A user with that email already exists.')
        return email


class EmployeeEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'username']

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
    role = forms.ChoiceField(choices=ROLE_CHOICES, required=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'phone', 'address', 'role', 'password1', 'password2']

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('A user with that email already exists.')
        return email
