from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse

from .context_processors import _role_code


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


class KarigarDeskMiddleware:
    """The Karigar desk posts job-card movements; it has no business in the CRM.

    Every CRM view is a plain ``login_required``, so the refusal lives here,
    keyed on the URL namespace, rather than on each of them.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if (request.resolver_match.namespace == "crm" and request.user.is_authenticated
                and _role_code(request.user) == "KARIGAR"):
            raise PermissionDenied("The Karigar desk cannot open the CRM.")
