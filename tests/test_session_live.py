"""Live contract test: Plane's web sign-in still works the way plane_mcp.session expects.

If Plane changes its sign-in flow (CSRF endpoint, form fields, cookie name), relation
removal breaks silently on the next upgrade. This catches it. It signs in and does nothing
else, so it is safe to run against a production workspace.
"""

import os

import pytest

from plane_mcp import session

pytestmark = pytest.mark.skipif(
    not (os.getenv("PLANE_SESSION_LIVE") and session.session_configured() and os.getenv("PLANE_BASE_URL")),
    reason="live test: set PLANE_SESSION_LIVE=1, PLANE_BASE_URL, PLANE_SESSION_EMAIL and PLANE_SESSION_PASSWORD",
)


def test_signs_in_and_gets_a_session_cookie():
    s = session.PlaneSession(session._base_url(), os.environ[session.EMAIL_ENV], os.environ[session.PASSWORD_ENV])
    s.sign_in()
    assert s.http.cookies.get(session.SESSION_COOKIE)
    assert s.http.cookies.get(session.CSRF_COOKIE)
