from django import forms
from .models import Physician, Clinic, TimeOffRequest, CoverageAssignment, PhysicianAvailability


class PhysicianForm(forms.ModelForm):
    class Meta:
        model = Physician
        fields = ['first_name', 'last_name', 'email',  'physician_type',
                  'total_vacation_days', 'daily_rate', 'agency', 'is_active']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            
            'physician_type': forms.Select(attrs={'class': 'form-control'}),
            'total_vacation_days': forms.NumberInput(attrs={'class': 'form-control'}),
            'daily_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': 'e.g. 1200.00'}),
            'agency': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. CompHealth, Weatherby'}),
        }


class ClinicForm(forms.ModelForm):
    class Meta:
        model = Clinic
        fields = ['name', 'location',  'regular_physicians', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'location': forms.TextInput(attrs={'class': 'form-control'}),
            
            'regular_physicians': forms.CheckboxSelectMultiple(),
        }


class TimeOffRequestForm(forms.ModelForm):
    class Meta:
        model = TimeOffRequest
        fields = ['physician', 'start_date', 'end_date', 'request_type', 'status', 'notes']
        widgets = {
            'physician': forms.Select(attrs={'class': 'form-control'}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'request_type': forms.Select(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['physician'].queryset = Physician.objects.filter(
            is_active=True, physician_type='regular'
        )

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('start_date')
        end = cleaned_data.get('end_date')
        if start and end and end < start:
            raise forms.ValidationError('End date must be on or after start date.')
        return cleaned_data


class CoverageAssignmentForm(forms.ModelForm):
    class Meta:
        model = CoverageAssignment
        fields = ['clinic', 'covering_physician', 'covered_physician', 'date', 'daily_rate_override', 'notes']
        widgets = {
            'clinic': forms.Select(attrs={'class': 'form-control'}),
            'covering_physician': forms.Select(attrs={'class': 'form-control'}),
            'covered_physician': forms.Select(attrs={'class': 'form-control'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'daily_rate_override': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': 'Leave blank to use standard rate'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['covering_physician'].queryset = Physician.objects.filter(
            is_active=True, physician_type='locum'
        )
        self.fields['covered_physician'].queryset = Physician.objects.filter(
            is_active=True, physician_type='regular'
        )
        self.fields['covered_physician'].required = False


class PhysicianAvailabilityForm(forms.ModelForm):
    class Meta:
        model = PhysicianAvailability
        fields = ['physician', 'date', 'is_available', 'notes']
        widgets = {
            'physician': forms.Select(attrs={'class': 'form-control'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['physician'].queryset = Physician.objects.filter(
            is_active=True, physician_type='locum'
        )
