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



class CrmScreenMiddleware:
    """The CRM is a screen like any other: a role without it opens none of it.

    Every CRM view sits in the ``crm`` URL namespace, so one check here covers
    all of them — including any added later — where a decorator on each view
    would be one forgotten line from a customer list anyone can read.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        from django.core.exceptions import PermissionDenied

        user = getattr(request, "user", None)
        match = request.resolver_match
        if match and match.namespace == "crm" and user is not None and user.is_authenticated:
            if "crm" not in user.screens:
                raise PermissionDenied(f"{user.role_name} cannot open the CRM.")
        return None
