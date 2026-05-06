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
        fields = ['customer', 'make', 'model', 'year', 'vin', 'license_plate', 'color', 'mileage', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3}),
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

    class Meta:
        model  = Appointment
        fields = ['customer', 'vehicle', 'vehicle_text', 'date_time', 'service_desc', 'confirmed', 'notes']
        widgets = {
            'date_time':    forms.DateInput(attrs={'type': 'date'}),
            'service_desc': forms.Textarea(attrs={'rows': 3}),
            'notes':        forms.Textarea(attrs={'rows': 3}),
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
            else:
                self.fields['vehicle_text'].widget = forms.HiddenInput()
                self.fields['vehicle_text'].required = False

    def clean(self):
        cleaned_data = super().clean()
        vehicle = cleaned_data.get('vehicle')
        vehicle_text = cleaned_data.get('vehicle_text')
        if not vehicle and not vehicle_text:
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
