from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class UsernameOrEmailBackend(ModelBackend):
    """Everyone knows their Supabase email; most also have a username.

    Both work. The email lookup is case-insensitive because ``logins.csv`` is
    exported with ``lower(email)``.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        User = get_user_model()
        candidate = username.strip()
        try:
            user = User.objects.get(username__iexact=candidate)
        except User.DoesNotExist:
            user = User.objects.filter(email__iexact=candidate).first()
        if user is None:
            User().set_password(password)  # equalise timing on an unknown user
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
