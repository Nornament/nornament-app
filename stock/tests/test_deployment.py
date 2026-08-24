"""The settings a container depends on, tested as the container exercises them.

These are the ones that only bite in production, where nothing is watching:
the healthcheck reaches gunicorn over plain HTTP on 127.0.0.1, so a
DisallowedHost or an https redirect there leaves the container permanently
unhealthy and Traefik never routes it.
"""
import pytest
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def production(settings):
    """Settings as the deployed container has them, not as the suite runs."""
    settings.DEBUG = False
    settings.ALLOWED_HOSTS = ["nornament.example.com", "localhost", "127.0.0.1"]
    settings.SECURE_SSL_REDIRECT = True
    settings.SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
    return settings


def test_the_container_healthcheck_reaches_healthz(production):
    """Exactly what deploy/docker-compose.yml runs: http to 127.0.0.1:8000."""
    response = Client().get("/healthz", HTTP_HOST="127.0.0.1:8000")
    assert response.status_code == 200, "the healthcheck would fail and the container would never be routed"
    assert response.content == b"ok"


def test_loopback_is_allowed_even_when_only_a_domain_is_configured(settings):
    """The env gives one hostname; loopback is added so the check can work."""
    assert "127.0.0.1" in settings.ALLOWED_HOSTS
    assert "localhost" in settings.ALLOWED_HOSTS


def test_real_traffic_is_still_redirected_to_https(production):
    response = Client().get("/", HTTP_HOST="nornament.example.com")
    assert response.status_code == 301
    assert response["Location"].startswith("https://")


def test_an_unknown_host_is_still_refused(production):
    assert Client().get("/healthz", HTTP_HOST="evil.example.com").status_code == 400


def test_healthz_needs_no_login(production):
    """An uptime monitor has no session."""
    assert Client().get("/healthz", HTTP_HOST="127.0.0.1:8000").status_code == 200
