import ast
import json
import math
import re
from collections.abc import Sequence
from typing import Any


# The visual layer deliberately remains deterministic. The LLM is still used for
# routing/tool selection and for the textual answer, but it does not invent chart
# data or UI schemas. Visualizations are derived only from the real MCP result.

_TABLE_MAX_ROWS = 50
_TABLE_MAX_COLUMNS = 10
_CHART_MAX_POINTS = 20

_LABEL_FIELD_HINTS = (
    "name",
    "hostname",
    "system",
    "server",
    "host",
    "group",
    "category",
    "label",
    "cve",
    "date",
    "time",
    "created",
    "modified",
)

_METRIC_FIELD_HINTS = (
    "count",
    "total",
    "number",
    "quantity",
    "pending",
    "available",
    "installed",
    "updates",
    "packages",
    "systems",
    "servers",
    "hosts",
    "events",
    "actions",
    "score",
    "cvss",
    "percent",
    "percentage",
    "size",
)

_ID_FIELD_HINTS = (
    "id",
    "system_id",
    "server_id",
    "event_id",
    "action_id",
    "group_id",
    "pid",
    "port",
)

_GRAPH_WORDS = (
    "grafico",
    "gráfico",
    "grafica",
    "gráfica",
    "chart",
    "plot",
    "visualiza",
    "barras",
    "bar chart",
    "lineas",
    "líneas",
    "line chart",
    "pastel",
    "circular",
    "pie chart",
)


def build_visualizations(
    user_message: str,
    tool_name: str,
    tool_result: str,
    structured_data: Any | None = None,
) -> list[dict[str, Any]]:
    """Build safe UI payloads from a real MCP result.

    The function is intentionally best-effort: if the result is not structured
    JSON, the normal textual response keeps working and no visualization is sent.
    """

    parsed = structured_data
    if parsed is None:
        parsed = _parse_json_value(tool_result)
    if parsed is None:
        return []

    title = _humanize_tool_name(tool_name)
    visualizations: list[dict[str, Any]] = []

    records = _find_best_record_list(parsed)
    if records:
        table = _build_table(records, title)
        if table is not None:
            visualizations.append(table)

        chart = _build_chart(
            records=records,
            title=title,
            user_message=user_message,
        )
        if chart is not None:
            visualizations.append(chart)

        return visualizations

    details = _build_key_value(parsed, title)
    if details is not None:
        visualizations.append(details)

    return visualizations


def _parse_json_value(text: str) -> Any | None:
    clean = text.strip()
    if not clean:
        return None

    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s*```$", "", clean)

    candidates = [clean]

    first_object = clean.find("{")
    last_object = clean.rfind("}")
    if first_object != -1 and last_object > first_object:
        candidates.append(clean[first_object : last_object + 1])

    first_array = clean.find("[")
    last_array = clean.rfind("]")
    if first_array != -1 and last_array > first_array:
        candidates.append(clean[first_array : last_array + 1])

    for candidate in candidates:
        value: Any
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            # Fallback seguro para servidores que devuelvan la representación
            # Python de listas/dicts en lugar de JSON estricto.
            try:
                value = ast.literal_eval(candidate)
            except (ValueError, SyntaxError):
                continue

        # Some MCPs wrap a JSON document in a JSON string. Unwrap once.
        if isinstance(value, str):
            nested = value.strip()
            if nested.startswith(("{", "[")):
                try:
                    return json.loads(nested)
                except json.JSONDecodeError:
                    try:
                        return ast.literal_eval(nested)
                    except (ValueError, SyntaxError):
                        pass

        if isinstance(value, (dict, list)):
            return value

    return None


def _find_best_record_list(value: Any) -> list[dict[str, Any]] | None:
    candidates: list[list[dict[str, Any]]] = []

    def visit(node: Any, depth: int) -> None:
        if depth > 3:
            return

        if isinstance(node, list):
            dict_items = [item for item in node if isinstance(item, dict)]
            if dict_items and len(dict_items) == len(node):
                candidates.append(dict_items)
                return

            for item in node[:10]:
                visit(item, depth + 1)
            return

        if isinstance(node, dict):
            # Prefer common API/MCP collection keys before arbitrary recursion.
            preferred_keys = (
                "data",
                "items",
                "results",
                "systems",
                "servers",
                "hosts",
                "updates",
                "patches",
                "errata",
                "events",
                "actions",
                "groups",
                "activation_keys",
                "packages",
            )
            seen: set[str] = set()
            for key in preferred_keys:
                child = node.get(key)
                if child is not None:
                    seen.add(key)
                    visit(child, depth + 1)

            for key, child in node.items():
                if key not in seen:
                    visit(child, depth + 1)

    visit(value, 0)

    if not candidates:
        return None

    # A larger record collection is normally the user's primary result.
    return max(candidates, key=len)


def _build_table(
    records: Sequence[dict[str, Any]],
    title: str,
) -> dict[str, Any] | None:
    if not records:
        return None

    columns: list[str] = []
    for record in records[:_TABLE_MAX_ROWS]:
        for key in record:
            if key not in columns and _is_displayable_value(record.get(key)):
                columns.append(key)
            if len(columns) >= _TABLE_MAX_COLUMNS:
                break
        if len(columns) >= _TABLE_MAX_COLUMNS:
            break

    if not columns:
        return None

    rows: list[dict[str, Any]] = []
    for record in records[:_TABLE_MAX_ROWS]:
        row = {column: _display_value(record.get(column)) for column in columns}
        rows.append(row)

    return {
        "type": "table",
        "title": title,
        "columns": [
            {"key": column, "label": _humanize_key(column)}
            for column in columns
        ],
        "rows": rows,
        "truncated": len(records) > _TABLE_MAX_ROWS,
        "total_rows": len(records),
    }


def _build_key_value(value: Any, title: str) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None

    items: list[dict[str, str]] = []
    for key, item in value.items():
        if not _is_displayable_value(item):
            continue
        items.append(
            {
                "label": _humanize_key(str(key)),
                "value": str(_display_value(item)),
            }
        )
        if len(items) >= 12:
            break

    if not items:
        return None

    return {
        "type": "key_value",
        "title": title,
        "items": items,
    }


def _build_chart(
    records: Sequence[dict[str, Any]],
    title: str,
    user_message: str,
) -> dict[str, Any] | None:
    if len(records) < 2:
        return None

    requested_chart = _contains_any(user_message.lower(), _GRAPH_WORDS)
    keys = _ordered_keys(records)

    numeric_keys = [
        key
        for key in keys
        if _is_numeric_series(records, key) and not _looks_like_identifier(key)
    ]
    if not numeric_keys:
        return None

    strong_metric_keys = [
        key for key in numeric_keys if _contains_any(key.lower(), _METRIC_FIELD_HINTS)
    ]

    # Avoid drawing meaningless charts from arbitrary numeric IDs unless the
    # user explicitly asks for a graph.
    if not requested_chart and not strong_metric_keys:
        return None

    metric_key = strong_metric_keys[0] if strong_metric_keys else numeric_keys[0]
    label_key = _choose_label_key(records, keys, metric_key)
    if label_key is None:
        return None

    limited_records = list(records[:_CHART_MAX_POINTS])
    labels = [str(_display_value(record.get(label_key))) for record in limited_records]
    values = [_to_number(record.get(metric_key)) for record in limited_records]

    if any(value is None for value in values):
        return None

    chart_type = _choose_chart_type(user_message, label_key, len(labels))

    return {
        "type": chart_type,
        "title": f"{_humanize_key(metric_key)} · {title}",
        "labels": labels,
        "series": [
            {
                "name": _humanize_key(metric_key),
                "values": values,
            }
        ],
        "truncated": len(records) > _CHART_MAX_POINTS,
    }


def _choose_chart_type(user_message: str, label_key: str, _point_count: int) -> str:
    normalized = user_message.lower()

    if any(word in normalized for word in ("lineas", "líneas", "line chart")):
        return "line_chart"

    label_normalized = label_key.lower()
    if any(token in label_normalized for token in ("date", "time", "fecha", "hora")):
        return "line_chart"

    return "bar_chart"


def _choose_label_key(
    records: Sequence[dict[str, Any]],
    keys: Sequence[str],
    metric_key: str,
) -> str | None:
    candidates = [key for key in keys if key != metric_key]

    hinted = [
        key
        for key in candidates
        if _contains_any(key.lower(), _LABEL_FIELD_HINTS)
        and _is_label_series(records, key)
    ]
    if hinted:
        return hinted[0]

    textual = [key for key in candidates if _is_label_series(records, key)]
    if textual:
        return textual[0]

    return None


def _ordered_keys(records: Sequence[dict[str, Any]]) -> list[str]:
    keys: list[str] = []
    for record in records[:20]:
        for key in record:
            key_str = str(key)
            if key_str not in keys:
                keys.append(key_str)
    return keys


def _is_numeric_series(records: Sequence[dict[str, Any]], key: str) -> bool:
    seen = 0
    for record in records[:_CHART_MAX_POINTS]:
        if key not in record or record[key] is None:
            continue
        if _to_number(record[key]) is None:
            return False
        seen += 1
    return seen >= 2


def _is_label_series(records: Sequence[dict[str, Any]], key: str) -> bool:
    seen = 0
    for record in records[:_CHART_MAX_POINTS]:
        value = record.get(key)
        if value is None:
            continue
        if isinstance(value, (dict, list, tuple, set)):
            return False
        seen += 1
    return seen >= 2


def _to_number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value

    if isinstance(value, str):
        clean = value.strip().replace("%", "")
        if not clean:
            return None
        try:
            number = float(clean)
        except ValueError:
            return None
        if not math.isfinite(number):
            return None
        return int(number) if number.is_integer() else number

    return None


def _looks_like_identifier(key: str) -> bool:
    normalized = key.lower().strip()
    if normalized in _ID_FIELD_HINTS:
        return True
    return normalized.endswith("_id") or normalized.endswith("id")


def _is_displayable_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, (list, dict)):
        return len(value) <= 6
    return False


def _display_value(value: Any) -> str | int | float | bool:
    if value is None:
        return "—"
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _humanize_tool_name(tool_name: str) -> str:
    return _humanize_key(tool_name)


def _humanize_key(key: str) -> str:
    normalized = re.sub(r"[_\-]+", " ", key).strip()
    if not normalized:
        return key
    return normalized[0].upper() + normalized[1:]


def _contains_any(text: str, needles: Sequence[str]) -> bool:
    return any(needle in text for needle in needles)
