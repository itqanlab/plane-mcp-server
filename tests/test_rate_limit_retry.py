"""429 from a self-hosted Plane is retried instead of failing the tool call."""

from plane import PlaneClient

from plane_mcp.client import RATE_LIMIT_RETRY, retry_on_rate_limit


def test_every_resource_session_gets_the_rate_limit_retry():
    client = retry_on_rate_limit(PlaneClient(base_url="https://plane.example", api_key="k"))
    sessions = [r.session for r in vars(client).values() if hasattr(r, "session")]
    assert sessions, "PlaneClient exposes no resource sessions; the walk found nothing"
    for session in sessions:
        assert session.get_adapter("https://plane.example/api").max_retries is RATE_LIMIT_RETRY


def test_only_429_is_retried_and_post_is_included():
    assert tuple(RATE_LIMIT_RETRY.status_forcelist) == (429,)
    assert RATE_LIMIT_RETRY.allowed_methods is None  # POST too: a 429 never ran
    assert RATE_LIMIT_RETRY.respect_retry_after_header
