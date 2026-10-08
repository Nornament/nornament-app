from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm
from django.contrib.auth.models import Group

from .models import User


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label="Username or email",
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username"}),
    )

    def clean_username(self):
        return (self.cleaned_data.get("username") or "").strip()


class ChangePasswordForm(SetPasswordForm):
    """Used for the forced first change; validators include the 72-byte guard."""


class UserForm(forms.ModelForm):
    """Add or change a login from Users & Settings, not the Django admin.

    A user gets exactly one role and nothing else: no per-user permissions, no
    staff or superuser switch. Those are how a login quietly gains a capability
    nobody gave its role, so they stay with superusers in the Django admin.
    """

    role = forms.ChoiceField(label="Role")
    password = forms.CharField(
        label="Temporary password",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="They choose their own on first login.",
    )

    class Meta:
        model = User
        fields = ["username", "full_name", "email", "phone", "role", "home_location", "locations", "is_active"]
        labels = {
            "full_name": "Name",
            "home_location": "Home location",
            "locations": "Also sees",
            "is_active": "Can log in",
        }

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        from stock.models import Location

        from .capabilities import ROLE_GROUPS
        from .context_processors import _role_code

        self.actor = actor
        self.fields["role"].choices = [(code, spec["name"]) for code, spec in ROLE_GROUPS.items()]
        if self.instance.pk:
            self.fields["role"].initial = _role_code(self.instance)
        else:
            # a new login is active; an unticked box would otherwise create it disabled
            del self.fields["is_active"]
            # chosen on purpose, never defaulted: the first role is Admin / Owner
            self.fields["role"].choices = [("", "— choose a role —"), *self.fields["role"].choices]
            self.fields["password"].required = True
        active = Location.objects.filter(is_active=True).order_by("code")
        self.fields["home_location"].queryset = active
        self.fields["home_location"].empty_label = "All locations"
        self.fields["locations"].queryset = active
        self.fields["locations"].required = False

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip()
        # login takes a username or an email, so two logins sharing an email
        # would make one of them impossible to sign in as
        if email and User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Another login already uses this email.")
        return email

    def clean(self):
        cleaned = super().clean()
        user = self.instance
        if user.pk and user.is_superuser and not self.actor.is_superuser:
            raise forms.ValidationError("Only a superuser can change a superuser.")
        if user.pk and user.pk == self.actor.pk:
            from .context_processors import _role_code

            # the way to lock everyone out is an admin disabling or demoting themselves
            if not cleaned.get("is_active"):
                self.add_error("is_active", "You cannot disable your own login.")
            if cleaned.get("role") and cleaned["role"] != _role_code(user):
                self.add_error("role", "You cannot change your own role.")
        password = cleaned.get("password")
        if password:
            try:
                password_validation.validate_password(password, user)
            except forms.ValidationError as error:
                self.add_error("password", error)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("password"):
            user.set_password(self.cleaned_data["password"])
            user.must_change_password = True
        user.save()
        self.save_m2m()
        user.groups.set([Group.objects.get(name=self.cleaned_data["role"])])
        return user
