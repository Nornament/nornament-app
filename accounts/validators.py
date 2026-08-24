from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


class BcryptLengthValidator:
    """bcrypt silently truncates at 72 bytes — refuse rather than truncate.

    An imported GoTrue hash is verified by bcrypt, so a 90-character password
    that "works" would in fact be a 72-byte one. Saying so at the form is the
    only honest option.
    """

    def validate(self, password, user=None):
        if len(password.encode("utf-8")) > 72:
            raise ValidationError(
                _("Passwords are limited to 72 bytes. Use a shorter one."),
                code="password_too_long",
            )

    def get_help_text(self):
        return _("Your password may be at most 72 bytes long.")
