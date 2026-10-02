"""Tests for the web-session sign-in and relation removal through it.

Everything runs against a fake HTTP layer that behaves like Plane 1.4.2: the CSRF endpoint
sets a cookie, sign-in sets `session-id` on success and redirects with an error_code on
failure, and the session-only `remove-relation/` route answers like DRF does.
"""

from types import SimpleNamespace

import pytest
from plane.errors.errors import HttpError

from plane_mcp import session
from plane_mcp.tools.workitem_relation import REMOVE_UNSUPPORTED, _remove_relation

BASE = "https://plane.example"
PASSWORD = "correct-horse-battery-staple"
SIGNED_OUT = "Authentication credentials were not provided."


class FakeResponse:
    def __init__(self, status_code=200, json=None, text="", headers=None):
        self.status_code = status_code
        self._json = json
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeHTTP:
    """Plane's web endpoints. `app_responses` is consumed one per app-route POST."""

    def __init__(self, app_responses=()):
        self.cookies = {}
        self.sign_ins = []
        self.app_calls = []
        self.app_responses = list(app_responses)

    def get(self, url, timeout=None):
        assert url == f"{BASE}/auth/get-csrf-token/"
        self.cookies["csrftoken"] = "tok"
        return FakeResponse(json={"csrf_token": "tok"})

    def post(self, url, data=None, json=None, headers=None, allow_redirects=True, timeout=None):
        assert allow_redirects is False
        if url == f"{BASE}/auth/sign-in/":
            self.sign_ins.append({"data": data, "headers": headers})
            if data["password"] == PASSWORD and data["csrfmiddlewaretoken"] == "tok":
                self.cookies["session-id"] = f"s{len(self.sign_ins)}"
                return FakeResponse(302, headers={"Location": f"{BASE}/"})
            return FakeResponse(302, headers={"Location": f"{BASE}/?error_code=5005&error_message=X"})
        self.app_calls.append({"url": url, "json": json, "headers": headers, "cookie": self.cookies.get("session-id")})
        return self.app_responses.pop(0) if self.app_responses else FakeResponse(204)


def make_session(http, password=PASSWORD):
    return session.PlaneSession(BASE, "bot@example.com", password, http=http)


class TestPlaneSession:
    def test_signs_in_with_the_csrf_token_email_and_password(self):
        http = FakeHTTP()
        make_session(http).sign_in()
        (call,) = http.sign_ins
        assert call["data"]["csrfmiddlewaretoken"] == "tok"
        assert call["data"]["email"] == "bot@example.com"
        assert call["data"]["password"] == PASSWORD
        assert call["headers"]["Referer"] == f"{BASE}/"
        assert http.cookies["session-id"] == "s1"

    def test_sends_the_csrf_header_and_session_cookie_on_app_calls(self):
        http = FakeHTTP()
        make_session(http).post("api/x/", {"a": 1})
        (call,) = http.app_calls
        assert call["url"] == f"{BASE}/api/x/"
        assert call["headers"]["X-CSRFToken"] == "tok"
        assert call["cookie"] == "s1"
        assert call["json"] == {"a": 1}

    def test_reuses_the_session_across_calls(self):
        http = FakeHTTP()
        s = make_session(http)
        s.post("api/x/", {})
        s.post("api/y/", {})
        assert len(http.sign_ins) == 1
        assert len(http.app_calls) == 2

    def test_signs_in_again_once_when_the_session_expired(self):
        http = FakeHTTP([FakeResponse(403, text=f'{{"detail": "{SIGNED_OUT}"}}'), FakeResponse(204)])
        response = make_session(http).post("api/x/", {})
        assert response.status_code == 204
        assert len(http.sign_ins) == 2
        assert [c["cookie"] for c in http.app_calls] == ["s1", "s2"]

    def test_does_not_loop_when_still_signed_out(self):
        http = FakeHTTP([FakeResponse(401), FakeResponse(401), FakeResponse(204)])
        response = make_session(http).post("api/x/", {})
        assert response.status_code == 401
        assert len(http.sign_ins) == 2

    def test_a_permission_403_does_not_trigger_a_sign_in(self):
        http = FakeHTTP([FakeResponse(403, text='{"error": "You don\'t have the required permissions."}')])
        assert make_session(http).post("api/x/", {}).status_code == 403
        assert len(http.sign_ins) == 1

    def test_refused_sign_in_names_the_error_code_and_never_the_password(self):
        with pytest.raises(session.SessionSignInError) as info:
            make_session(FakeHTTP(), password="wrong-password").sign_in()
        assert "5005" in str(info.value)
        assert "wrong-password" not in str(info.value)

    def test_repr_hides_the_password(self):
        assert PASSWORD not in repr(make_session(FakeHTTP()))


class FakePlane:
    """An API-key client on a deployment with no dependency endpoints.

    `legacy` is what the legacy relations endpoint returns for the work item; a successful
    session removal empties it, the way Plane's soft delete hides the row from the list.
    """

    def __init__(self, legacy):
        self.legacy = legacy

        def remove(**kwargs):
            raise HttpError(status_code=404, message="Not Found")

        def _get(path):
            return self.legacy

        self.work_items = SimpleNamespace(
            dependencies=SimpleNamespace(remove=remove),
            custom_relations=SimpleNamespace(remove=remove),
            relations=SimpleNamespace(_get=_get),
            retrieve=lambda **k: SimpleNamespace(sequence_id={"wi": 9, "other": 8}[k["work_item_id"]]),
        )
        self.projects = SimpleNamespace(
            retrieve=lambda **k: SimpleNamespace(identifier="PMCP", name="Plane MCP"),
        )


RELATED = {"blocked_by": [{"project_id": "p", "issue_id": "other"}]}


@pytest.fixture
def configured(monkeypatch):
    """Session env set, and get_session() bound to a fake HTTP layer."""
    monkeypatch.setenv(session.EMAIL_ENV, "bot@example.com")
    monkeypatch.setenv(session.PASSWORD_ENV, PASSWORD)

    def install(http, password=PASSWORD):
        s = make_session(http, password)
        monkeypatch.setattr(session, "get_session", lambda: s)
        return http

    return install


class TestRemoveThroughSession:
    def test_removes_the_relation_and_reads_it_back(self, configured):
        plane = FakePlane(dict(RELATED))

        class RemovingHTTP(FakeHTTP):
            def post(self, url, **kwargs):
                response = super().post(url, **kwargs)
                if url.endswith("/remove-relation/"):
                    plane.legacy = {"blocked_by": []}
                return response

        http = configured(RemovingHTTP())
        out = _remove_relation(plane, "ws", "p", "wi", "other", True)
        assert out == {
            "workitem": "PMCP-9",
            "related_workitem": "PMCP-8",
            "relation_type": "blocked_by",
            "removed": True,
            "source": "web_session_remove_relation",
        }
        (call,) = http.app_calls
        assert call["url"] == f"{BASE}/api/workspaces/ws/projects/p/issues/wi/remove-relation/"
        assert call["json"] == {"related_issue": "other"}

    def test_reports_removed_false_when_the_read_back_still_shows_it(self, configured):
        configured(FakeHTTP())
        out = _remove_relation(FakePlane(dict(RELATED)), "ws", "p", "wi", "other", True)
        assert out["removed"] is False

    def test_refuses_when_the_items_are_not_related(self, configured):
        """The server 500s on a missing relation; refuse before calling it."""
        http = configured(FakeHTTP())
        out = _remove_relation(FakePlane({"blocked_by": []}), "ws", "p", "wi", "other", True)
        assert out.startswith("Error:") and "no relation" in out
        assert http.app_calls == [] and http.sign_ins == []

    def test_env_unset_keeps_the_unsupported_message_naming_the_env_vars(self, monkeypatch):
        monkeypatch.delenv(session.EMAIL_ENV, raising=False)
        monkeypatch.delenv(session.PASSWORD_ENV, raising=False)
        out = _remove_relation(FakePlane(dict(RELATED)), "ws", "p", "wi", "other", True)
        assert out == REMOVE_UNSUPPORTED
        assert session.EMAIL_ENV in out and session.PASSWORD_ENV in out

    def test_403_names_the_project_and_the_membership_fix(self, configured):
        configured(FakeHTTP([FakeResponse(403, text='{"error": "You are not a member"}')]))
        out = _remove_relation(FakePlane(dict(RELATED)), "ws", "p", "wi", "other", True)
        assert out.startswith("Error:")
        assert "Plane MCP (PMCP)" in out
        assert "reference_plane_selfhosted_limits.md" in out

    def test_refused_sign_in_is_a_clear_error(self, configured):
        configured(FakeHTTP(), password="wrong-password")
        out = _remove_relation(FakePlane(dict(RELATED)), "ws", "p", "wi", "other", True)
        assert out.startswith("Error: Plane refused the session sign-in")
        assert "wrong-password" not in out

    def test_other_server_errors_are_raised(self, configured):
        configured(FakeHTTP([FakeResponse(500, text="boom")]))
        with pytest.raises(HttpError):
            _remove_relation(FakePlane(dict(RELATED)), "ws", "p", "wi", "other", True)


class TestSessionConfig:
    def test_get_session_prefers_the_internal_base_url_and_is_cached(self, monkeypatch):
        monkeypatch.setenv(session.EMAIL_ENV, "bot@example.com")
        monkeypatch.setenv(session.PASSWORD_ENV, PASSWORD)
        monkeypatch.setenv("PLANE_BASE_URL", "https://public.example/")
        monkeypatch.setenv("PLANE_INTERNAL_BASE_URL", "http://internal:8000/")
        monkeypatch.setattr(session, "_cache", {})
        first = session.get_session()
        assert first.base_url == "http://internal:8000"
        assert session.get_session() is first

    def test_configured_needs_both_vars(self, monkeypatch):
        monkeypatch.setenv(session.EMAIL_ENV, "bot@example.com")
        monkeypatch.delenv(session.PASSWORD_ENV, raising=False)
        assert session.session_configured() is False
