"""Project feature flags on an edition with no features endpoint (PMCP-22).

Plane Community answers 404 on `projects/{id}/features`. The same switches live on the
project record, so get_features and update_features fall back to them.
"""

from types import SimpleNamespace

import pytest
from plane.errors import HttpError

NOT_SERVED = HttpError("HTTP 404: Not Found", 404, {"error": "Page not found."})


def _project(**flags):
    base = {"module_view": False, "cycle_view": True, "issue_views_view": False, "page_view": True, "intake_view": True}
    return SimpleNamespace(**{**base, **flags})


def test_get_features_uses_the_endpoint_when_served(registered, spy):
    registered["project"].fn(action="get_features", project_id="p-1")
    assert spy.recorder.methods == ["projects.get_features"]


def test_get_features_falls_back_to_the_project_record(registered, spy):
    spy.returns["projects.get_features"] = NOT_SERVED
    spy.returns["projects.retrieve"] = _project()

    result = registered["project"].fn(action="get_features", project_id="p-1")

    assert spy.recorder.methods == ["projects.get_features", "projects.retrieve"]
    assert result.model_dump(exclude_none=True) == {
        "modules": False,
        "cycles": True,
        "views": False,
        "pages": True,
        "intakes": True,
    }


def test_update_features_writes_the_project_switch(registered, spy):
    spy.returns["projects.update_features"] = NOT_SERVED
    spy.returns["projects.update"] = _project(module_view=True)

    result = registered["project"].fn(action="update_features", project_id="p-1", modules=True)

    assert spy.recorder.methods == ["projects.update_features", "projects.update"]
    sent = spy.recorder.calls[-1].kwargs["data"].model_dump(exclude_none=True)
    assert sent == {"module_view": True}
    assert result.modules is True


def test_update_features_refuses_a_toggle_with_no_project_switch(registered, spy):
    spy.returns["projects.update_features"] = NOT_SERVED

    result = registered["project"].fn(action="update_features", project_id="p-1", modules=True, workitem_types=True)

    assert isinstance(result, str) and result.startswith("Error:")
    assert "workitem_types" in result and "nothing was changed" in result
    assert spy.recorder.methods == ["projects.update_features"]


def test_update_features_keeps_the_endpoint_when_served(registered, spy):
    registered["project"].fn(action="update_features", project_id="p-1", modules=True)
    assert spy.recorder.methods == ["projects.update_features"]


@pytest.mark.parametrize("action", ["get_features", "update_features"])
def test_other_errors_are_not_swallowed(registered, spy, action):
    spy.returns[f"projects.{action}"] = HttpError("HTTP 500: Server Error", 500, None)
    with pytest.raises(HttpError):
        registered["project"].fn(action=action, project_id="p-1", modules=True if action == "update_features" else None)
