from django import forms
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label="Username or email",
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username"}),
    )

    def clean_username(self):
        return (self.cleaned_data.get("username") or "").strip()


class ChangePasswordForm(SetPasswordForm):
    """Used for the forced first change; validators include the 72-byte guard."""
