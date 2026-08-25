from django.shortcuts import redirect
from django.urls import reverse


class MustChangePasswordMiddleware:
    """A user flagged ``must_change_password`` can reach nothing else.

    The old app carried the same flag but enforced it in the front end, which
    means it did not enforce it at all.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.must_change_password:
            allowed = {
                reverse("accounts:password_change"),
                reverse("accounts:logout"),
                reverse("healthz"),
            }
            if request.path not in allowed and not request.path.startswith("/static/"):
                return redirect("accounts:password_change")
        return self.get_response(request)
