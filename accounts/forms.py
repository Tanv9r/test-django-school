from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm

from core.forms import BootstrapFormMixin, BootstrapModelForm

from .models import User


class LoginForm(BootstrapFormMixin, AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update({"placeholder": "Username", "autofocus": True})
        self.fields["password"].widget.attrs.update({"placeholder": "Password"})


class ProfileForm(BootstrapModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True


class StyledPasswordChangeForm(BootstrapFormMixin, PasswordChangeForm):
    pass


class EmptyForm(forms.Form):
    """Used for POST-only confirmation actions so CSRF is still validated."""
