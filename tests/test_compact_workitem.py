"""List rows are compact by default and writes confirm instead of echoing the item."""

from types import SimpleNamespace as NS

from plane_mcp.tools.workitem import COMPACT_ROW, _confirm


def test_write_confirmation_drops_the_body_but_says_how_big_it_is():
    item = NS(
        model_dump=lambda: {
            "id": "x",
            "sequence_id": 7,
            "name": "n",
            "state": "s",
            "priority": "high",
            "parent": None,
            "updated_at": "t",
            "description_html": "<p>" + "a" * 5000 + "</p>",
            "labels": ["l"],
        }
    )
    out = _confirm(item)
    assert "description_html" not in out and "labels" not in out
    assert out["sequence_id"] == 7 and out["priority"] == "high" and out["description_chars"] == 5007


def test_compact_row_carries_what_picking_work_needs_and_no_description():
    fields = set(COMPACT_ROW.split(","))
    assert {"id", "sequence_id", "name", "state", "priority", "parent", "updated_at"} <= fields
    assert not fields & {"description_html", "description_stripped"}
