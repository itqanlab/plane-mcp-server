"""A signed-in Plane web session, for the few operations the API key cannot reach.

Some Plane routes live only in the web app (`/api/workspaces/...`) behind
`BaseSessionAuthentication`, which ignores API keys. Relation removal is one: Plane
Community 1.4.2's public API lists and creates relations but cannot remove them.

This module signs in as a dedicated user through Plane's own web sign-in flow:

1. GET  /auth/get-csrf-token/  -> sets the `csrftoken` cookie and returns the token
2. POST /auth/sign-in/         -> form body with `csrfmiddlewaretoken`, `email`, `password`;
                                  success sets the `session-id` cookie, failure is a redirect
                                  carrying `error_code` in the query string

The cookie jar is kept for the life of the process and the sign-in is repeated once when
Plane says the session is gone. The password and cookie values are never logged and never
put in an error message.

Credentials come from the environment, next to PLANE_API_KEY:
PLANE_SESSION_EMAIL and PLANE_SESSION_PASSWORD.
"""

from __future__ import annotations

import os
import threading
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

EMAIL_ENV = "PLANE_SESSION_EMAIL"
PASSWORD_ENV = "PLANE_SESSION_PASSWORD"
SESSION_COOKIE = "session-id"
CSRF_COOKIE = "csrftoken"
TIMEOUT = 30

HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403

# DRF answers a request with no valid session with 403 and this detail (SessionAuthentication
# has no WWW-Authenticate header, so it cannot use 401). A 403 for missing membership says
# something else, and must not trigger a sign-in loop.
_SIGNED_OUT_MARKERS = ("authentication credentials were not provided", "not authenticated")


class SessionSignInError(Exception):
    """Plane refused the sign-in. The message never contains the password."""


def session_configured() -> bool:
    return bool(os.getenv(EMAIL_ENV) and os.getenv(PASSWORD_ENV))


def _base_url() -> str:
    return (os.getenv("PLANE_INTERNAL_BASE_URL") or os.getenv("PLANE_BASE_URL", "https://api.plane.so")).rstrip("/")


def _signed_out(response: Any) -> bool:
    if response.status_code == HTTP_UNAUTHORIZED:
        return True
    if response.status_code != HTTP_FORBIDDEN:
        return False
    return any(marker in (response.text or "").lower() for marker in _SIGNED_OUT_MARKERS)


class PlaneSession:
    """One signed-in browser session. `http` is injectable so tests need no network."""

    def __init__(self, base_url: str, email: str, password: str, http: Any = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.email = email
        self._password = password
        self.http = http if http is not None else requests.Session()
        self._signed_in = False
        self._lock = threading.Lock()

    def __repr__(self) -> str:  # never show the password
        return f"PlaneSession(base_url={self.base_url!r}, email={self.email!r})"

    def _headers(self) -> dict[str, str]:
        # Django checks the Referer on HTTPS form posts; the web app sends both.
        headers = {"Referer": f"{self.base_url}/", "Origin": self.base_url}
        token = self.http.cookies.get(CSRF_COOKIE)
        if token:
            headers["X-CSRFToken"] = token
        return headers

    def sign_in(self) -> None:
        response = self.http.get(f"{self.base_url}/auth/get-csrf-token/", timeout=TIMEOUT)
        response.raise_for_status()
        token = (response.json() or {}).get("csrf_token") or self.http.cookies.get(CSRF_COOKIE)
        if not token:
            raise SessionSignInError("Plane returned no CSRF token for the session sign-in.")

        response = self.http.post(
            f"{self.base_url}/auth/sign-in/",
            data={"csrfmiddlewaretoken": token, "email": self.email, "password": self._password, "next_path": "/"},
            headers=self._headers(),
            allow_redirects=False,
            timeout=TIMEOUT,
        )
        if not self.http.cookies.get(SESSION_COOKIE):
            location = response.headers.get("Location", "") if hasattr(response, "headers") else ""
            code = parse_qs(urlparse(location).query).get("error_code", [""])[0]
            reason = f"error_code {code}" if code else f"HTTP {response.status_code}"
            raise SessionSignInError(f"Plane refused the session sign-in for {self.email} ({reason}).")
        self._signed_in = True

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        """POST JSON to a web-app route, signing in first and once more if the session expired."""
        with self._lock:
            if not self._signed_in:
                self.sign_in()
            response = self._post(path, payload)
            if _signed_out(response):
                self.sign_in()
                response = self._post(path, payload)
            return response

    def _post(self, path: str, payload: dict[str, Any]) -> Any:
        return self.http.post(
            f"{self.base_url}/{path.lstrip('/')}",
            json=payload,
            headers=self._headers(),
            allow_redirects=False,
            timeout=TIMEOUT,
        )


_cache: dict[tuple[str, str], PlaneSession] = {}
_cache_lock = threading.Lock()


def get_session() -> PlaneSession:
    """The process-wide session for the configured user and base URL."""
    email, password, base = os.getenv(EMAIL_ENV, ""), os.getenv(PASSWORD_ENV, ""), _base_url()
    with _cache_lock:
        session = _cache.get((base, email))
        if session is None:
            session = _cache[(base, email)] = PlaneSession(base, email, password)
        return session
