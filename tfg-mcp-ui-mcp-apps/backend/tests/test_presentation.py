from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from mcp_app.presentation import build_presentation, parse_structured_value


def test_list_of_systems_builds_table_metrics_and_category_bar() -> None:
    systems = {
        "systems": [
            {"id": 1000010000, "name": "client1", "status": "online", "os": "Tumbleweed"},
            {"id": 1000010001, "name": "client2", "status": "offline", "os": "Tumbleweed"},
        ]
    }

    payload = build_presentation(
        tool_name="list_systems",
        tool_result=str(systems),
        structured_data=systems,
        requested_view="bar",
    )

    assert payload["totalRows"] == 2
    assert "table" in payload["views"]
    assert "bar" in payload["views"]
    assert payload["initialView"] == "bar"
    assert payload["chart"]["derived"] is True
    assert payload["chart"]["metricKey"] == "count"
    assert payload["chart"]["supportsLine"] is False
    # IDs are allowed in tables, but never used as chart magnitudes.
    assert payload["chart"]["metricKey"] != "id"


def test_real_numeric_metric_is_used_without_derivation() -> None:
    rows = [
        {"system": "client1", "pending_updates": 3},
        {"system": "client2", "pending_updates": 7},
    ]
    payload = build_presentation(
        tool_name="summarize_fleet_updates",
        tool_result="",
        structured_data={"systems": rows},
        requested_view="bar",
    )

    assert payload["chart"]["derived"] is False
    assert payload["chart"]["metricKey"] == "pending_updates"
    assert payload["chart"]["values"] == [3.0, 7.0]
    assert payload["initialView"] == "bar"


def test_line_view_requires_a_meaningful_axis() -> None:
    categorical = [
        {"system": "client1", "updates": 2},
        {"system": "client2", "updates": 4},
    ]
    payload = build_presentation(
        tool_name="updates",
        tool_result="",
        structured_data=categorical,
        requested_view="line",
    )
    assert "line" not in payload["views"]
    assert payload["initialView"] == "table"

    temporal = [
        {"date": "2026-08-20", "updates": 2},
        {"date": "2026-08-21", "updates": 4},
    ]
    payload = build_presentation(
        tool_name="updates_over_time",
        tool_result="",
        structured_data=temporal,
        requested_view="line",
    )
    assert "line" in payload["views"]
    assert payload["initialView"] == "line"


def test_single_record_exposes_detail_view() -> None:
    payload = build_presentation(
        tool_name="get_system_details",
        tool_result="",
        structured_data={"systems": [{"id": 1, "hostname": "client1.lab.local", "status": "online"}]},
        requested_view="detail",
    )
    assert "detail" in payload["views"]
    assert payload["initialView"] == "detail"
    assert any(item["label"] == "Hostname" for item in payload["detail"])


def test_empty_collection_has_explicit_empty_state() -> None:
    payload = build_presentation(
        tool_name="list_systems_needing_reboot",
        tool_result='{"systems": []}',
        structured_data={"systems": []},
        requested_view="auto",
    )
    assert payload["empty"] is True
    assert payload["views"] == ["empty"]
    assert payload["initialView"] == "empty"
    assert payload["metrics"][0]["value"] == 0


def test_unstructured_text_never_fabricates_chart_data() -> None:
    payload = build_presentation(
        tool_name="some_tool",
        tool_result="Uyuni says there is nothing structured here.",
        structured_data=None,
        requested_view="bar",
    )
    assert payload["views"] == ["raw"]
    assert payload["chart"] is None
    assert "Uyuni says" in payload["rawPreview"]


def test_parser_accepts_json_fenced_payload() -> None:
    assert parse_structured_value('```json\n{"items":[{"name":"x"}]}\n```') == {
        "items": [{"name": "x"}]
    }
