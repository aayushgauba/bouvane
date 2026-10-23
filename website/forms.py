from django import forms

from .models import Enquiry


class ContactForm(forms.ModelForm):
    SERVICE_CHOICES = [
        ('', 'Choose a topic'),
        ('Cloud beta access', 'Bouvane Cloud beta access'),
        ('AIWAF', 'AIWAF & open source'),
        ('Partnership', 'Partnership enquiry'),
        ('General enquiry', 'General enquiry'),
    ]
    service = forms.ChoiceField(choices=SERVICE_CHOICES, label='What can we help with?')
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = Enquiry
        fields = ['name', 'email', 'company', 'service', 'message']
        labels = {'name': 'Your name', 'email': 'Email address', 'company': 'Company (optional)', 'message': 'Your message'}
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Alex Morgan', 'autocomplete': 'name'}),
            'email': forms.EmailInput(attrs={'placeholder': 'alex@company.com', 'autocomplete': 'email'}),
            'company': forms.TextInput(attrs={'placeholder': 'Your company', 'autocomplete': 'organization'}),
            'message': forms.Textarea(attrs={'rows': 5, 'placeholder': 'Tell us about your application, your security needs, or what you would like to know.'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if self.is_bound and self.errors.get(name):
                field.widget.attrs.update({'aria-invalid': 'true', 'aria-describedby': f'{name}-errors'})

    def clean_name(self):
        value = self.cleaned_data['name'].strip()
        if len(value) < 2:
            raise forms.ValidationError('Please enter your full name.')
        return value

    def clean_message(self):
        value = self.cleaned_data['message'].strip()
        if len(value) < 20:
            raise forms.ValidationError('Please share a little more detail (at least 20 characters).')
        return value


class BetaSignupForm(forms.Form):
    email = forms.EmailField(max_length=254, label='Your email address', widget=forms.EmailInput(attrs={
        'placeholder': 'you@company.com', 'autocomplete': 'email', 'id': 'beta-email',
    }))
    consent = forms.BooleanField(label='Email me Bouvane Cloud beta updates and an invitation when access is available.')
    website = forms.CharField(required=False, widget=forms.HiddenInput(attrs={'id': 'beta-website'}))
