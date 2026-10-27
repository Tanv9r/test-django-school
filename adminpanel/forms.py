from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import SetPasswordForm

from accounts.models import Role, User
from core.forms import BootstrapForm, BootstrapFormMixin, BootstrapModelForm, DateInput
from core.models import AuditLog, HospitalSettings


class UserCreateForm(BootstrapModelForm):
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput, strip=False,
                                help_text=password_validation.password_validators_help_text_html())
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput, strip=False)

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "phone", "role", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("A user with that username already exists.")
        return username

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "The two passwords do not match.")
        elif p1:
            user = User(username=cleaned.get("username"), first_name=cleaned.get("first_name", ""),
                        last_name=cleaned.get("last_name", ""), email=cleaned.get("email", ""))
            try:
                password_validation.validate_password(p1, user)
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class UserUpdateForm(BootstrapModelForm):
    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "phone", "role", "is_active"]

    def __init__(self, *args, acting_user=None, **kwargs):
        self.acting_user = acting_user
        super().__init__(*args, **kwargs)
        if self.instance.is_superuser:
            self.fields["role"].disabled = True
            self.fields["role"].help_text = "Superusers are always administrators."

    def clean(self):
        cleaned = super().clean()
        if self.acting_user is not None and self.instance.pk == self.acting_user.pk:
            if cleaned.get("is_active") is False:
                self.add_error("is_active", "You cannot deactivate your own account.")
            if cleaned.get("role") and cleaned["role"] != Role.ADMIN and not self.instance.is_superuser:
                self.add_error("role", "You cannot remove your own administrator role.")
        return cleaned


class StyledSetPasswordForm(BootstrapFormMixin, SetPasswordForm):
    pass


class HospitalSettingsForm(BootstrapModelForm):
    class Meta:
        model = HospitalSettings
        fields = ["name", "tagline", "address", "phone", "email", "currency_symbol", "expiry_warning_days", "invoice_footer"]
        widgets = {"address": forms.Textarea(attrs={"rows": 2})}


class UserFilterForm(BootstrapForm):
    q = forms.CharField(required=False, label="Search", widget=forms.TextInput(attrs={"placeholder": "Username, name or email"}))
    role = forms.ChoiceField(required=False, choices=[("", "All roles"), *Role.choices])
    status = forms.ChoiceField(required=False, choices=[("", "Any status"), ("active", "Active"), ("inactive", "Inactive")])


class AuditFilterForm(BootstrapForm):
    q = forms.CharField(required=False, label="Search", widget=forms.TextInput(attrs={"placeholder": "Object, message or username"}))
    action = forms.ChoiceField(required=False, choices=[("", "All actions"), *AuditLog.Action.choices])
    date_from = forms.DateField(required=False, widget=DateInput(), label="From")
    date_to = forms.DateField(required=False, widget=DateInput(), label="To")
