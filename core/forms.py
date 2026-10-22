import re
from decimal import Decimal

from django import forms
from django.db.models import Q
from django.utils import timezone

from .models import Farmer, Delivery, Payment, Stock
from .services import normalise_phone


class BootstrapMixin:
    """Gives every field the Bootstrap look."""
    def _style(self):
        for field in self.fields.values():
            widget = field.widget
            css = 'form-select' if isinstance(widget, forms.Select) else 'form-control'
            widget.attrs['class'] = (widget.attrs.get('class', '') + ' ' + css).strip()


class FarmerForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Farmer
        fields = ['name', 'phone', 'produce_type', 'status']
        labels = {'produce_type': 'Main produce'}
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'e.g. Peter Mwangi'}),
            'phone': forms.TextInput(attrs={'placeholder': 'e.g. 0712 345 678'}),
            'produce_type': forms.TextInput(attrs={'list': 'produce-list', 'placeholder': 'e.g. Maize'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()

    def clean_name(self):
        return ' '.join(self.cleaned_data['name'].split())

    def clean_phone(self):
        phone = normalise_phone(self.cleaned_data['phone'])
        if not re.fullmatch(r'\+?\d{9,13}', phone):
            raise forms.ValidationError('Enter a phone number with 9 to 13 digits, e.g. 0712 345 678.')
        return phone

    def clean_produce_type(self):
        return self.cleaned_data['produce_type'].strip().title()


class DeliveryForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Delivery
        fields = ['farmer', 'produce', 'quantity', 'receipt_no', 'delivery_date']
        labels = {'produce': 'Produce', 'quantity': 'Quantity (kg)', 'receipt_no': 'Receipt number',
                  'delivery_date': 'Delivery date'}
        widgets = {
            'produce': forms.TextInput(attrs={'list': 'produce-list', 'placeholder': 'e.g. Maize'}),
            'quantity': forms.NumberInput(attrs={'step': '0.01', 'min': '0.01', 'placeholder': 'e.g. 250'}),
            'receipt_no': forms.TextInput(attrs={'placeholder': 'e.g. R-1042'}),
            'delivery_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['farmer'].queryset = Farmer.objects.exclude(status='Inactive').order_by('name')
        if self.instance.pk:  # keep the current farmer selectable even if now inactive
            self.fields['farmer'].queryset = Farmer.objects.filter(
                Q(pk=self.instance.farmer_id) | ~Q(status='Inactive')).order_by('name')
        self.fields['farmer'].label_from_instance = lambda f: f"{f.code} - {f.name}"
        if not self.instance.pk:
            self.fields['delivery_date'].initial = timezone.localdate()
        self._style()

    def clean_produce(self):
        return self.cleaned_data['produce'].strip().title()

    def clean_receipt_no(self):
        return self.cleaned_data['receipt_no'].strip().upper()

    def clean_quantity(self):
        qty = self.cleaned_data['quantity']
        if qty <= 0:
            raise forms.ValidationError('Quantity must be more than 0.')
        return qty


class PaymentForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Payment
        fields = ['delivery', 'amount', 'receipt_no', 'payment_date']
        labels = {'delivery': 'Verified delivery', 'amount': 'Amount (KES)', 'receipt_no': 'Receipt number',
                  'payment_date': 'Payment date'}
        widgets = {
            'amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0.01', 'placeholder': 'e.g. 18500'}),
            'receipt_no': forms.TextInput(attrs={'placeholder': 'Same as the delivery receipt'}),
            'payment_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        free = Q(status='Verified', payment__isnull=True)
        if self.instance.pk:
            free |= Q(pk=self.instance.delivery_id)
        self.fields['delivery'].queryset = Delivery.objects.filter(free).select_related('farmer').order_by('-delivery_date')
        self.fields['delivery'].label_from_instance = lambda d: (
            f"{d.code} - {d.farmer.name} - {d.produce} {d.quantity:g} kg - receipt {d.receipt_no}")
        self.fields['delivery'].empty_label = 'Choose a verified delivery...'
        if not self.instance.pk:
            self.fields['payment_date'].initial = timezone.localdate()
        self._style()

    def clean_receipt_no(self):
        return self.cleaned_data['receipt_no'].strip().upper()

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount <= 0:
            raise forms.ValidationError('Amount must be more than 0.')
        return amount

    def save(self, commit=True):
        payment = super().save(commit=False)
        payment.farmer = payment.delivery.farmer       # the farmer always comes from the delivery
        if commit:
            payment.save()
        return payment


class DispatchForm(BootstrapMixin, forms.Form):
    produce = forms.ChoiceField(label='Produce')
    quantity = forms.DecimalField(label='Quantity dispatched (kg)', min_value=Decimal('0.01'),
                                  max_digits=10, decimal_places=2)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['produce'].choices = [(s.produce, s.produce) for s in Stock.objects.order_by('produce')]
        self._style()
