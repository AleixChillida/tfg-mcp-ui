from agents.visualization_builder import build_visualizations


def test_list_of_records_builds_table():
    result = """
    [
      {"hostname": "srv-a", "status": "online"},
      {"hostname": "srv-b", "status": "offline"}
    ]
    """

    visualizations = build_visualizations(
        user_message="Lista los sistemas",
        tool_name="list_systems",
        tool_result=result,
    )

    assert len(visualizations) == 1
    table = visualizations[0]
    assert table["type"] == "table"
    assert table["rows"][0]["hostname"] == "srv-a"
    assert table["columns"][0]["key"] == "hostname"


def test_numeric_metric_builds_table_and_bar_chart():
    result = """
    [
      {"hostname": "srv-a", "pending_updates": 4},
      {"hostname": "srv-b", "pending_updates": 9},
      {"hostname": "srv-c", "pending_updates": 2}
    ]
    """

    visualizations = build_visualizations(
        user_message="Muéstrame las actualizaciones pendientes",
        tool_name="list_systems",
        tool_result=result,
    )

    assert [visual["type"] for visual in visualizations] == [
        "table",
        "bar_chart",
    ]
    chart = visualizations[1]
    assert chart["labels"] == ["srv-a", "srv-b", "srv-c"]
    assert chart["series"][0]["values"] == [4, 9, 2]


def test_time_series_prefers_line_chart():
    result = """
    [
      {"date": "2026-08-15", "event_count": 3},
      {"date": "2026-08-16", "event_count": 8},
      {"date": "2026-08-17", "event_count": 5}
    ]
    """

    visualizations = build_visualizations(
        user_message="Enséñame la evolución de eventos",
        tool_name="list_events",
        tool_result=result,
    )

    assert visualizations[1]["type"] == "line_chart"


def test_single_object_builds_detail_card():
    result = '{"hostname":"srv-a","os":"SLES 15","reboot_required":false}'

    visualizations = build_visualizations(
        user_message="Dame el detalle del sistema",
        tool_name="get_system_details",
        tool_result=result,
    )

    assert len(visualizations) == 1
    assert visualizations[0]["type"] == "key_value"
    labels = {item["label"] for item in visualizations[0]["items"]}
    assert "Hostname" in labels
    assert "Reboot required" in labels


def test_structured_content_has_priority_over_text():
    structured = {
        "systems": [
            {"hostname": "srv-a", "pending_updates": 1},
            {"hostname": "srv-b", "pending_updates": 2},
        ]
    }

    visualizations = build_visualizations(
        user_message="Lista los sistemas",
        tool_name="list_systems",
        tool_result="texto no estructurado",
        structured_data=structured,
    )

    assert visualizations[0]["type"] == "table"
    assert visualizations[0]["rows"][1]["hostname"] == "srv-b"


def test_plain_text_keeps_visual_layer_empty():
    visualizations = build_visualizations(
        user_message="Consulta",
        tool_name="some_tool",
        tool_result="No hay resultados disponibles.",
    )

    assert visualizations == []
