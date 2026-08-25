from django.db import connection
from django.http import HttpResponse


def healthz(request):
    """What the uptime monitor hits. A database round trip, nothing else."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return HttpResponse("ok", content_type="text/plain")
