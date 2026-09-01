from __future__ import annotations

import ast
import json
import math
import re
from collections import Counter
from collections.abc import Sequence
from typing import Any

_TABLE_MAX_ROWS = 60
_TABLE_MAX_COLUMNS = 10
_CHART_MAX_POINTS = 24

_LABEL_HINTS = (
    "name", "hostname", "system", "server", "host", "group", "category",
    "label", "cve", "date", "time", "created", "modified", "status",
)
_METRIC_HINTS = (
    "count", "total", "number", "quantity", "pending", "available", "installed",
    "updates", "packages", "systems", "servers", "hosts", "events", "actions",
    "score", "cvss", "percent", "percentage", "size",
)
_ID_HINTS = (
    "id", "system_id", "server_id", "event_id", "action_id", "group_id", "pid", "port",
)
_TIME_HINTS = ("date", "time", "created", "modified", "scheduled", "earliest", "latest", "fecha", "hora")
_STATUS_HINTS = ("status", "state", "result", "type", "advisory", "severity")


def build_presentation(
    *,
    tool_name: str,
    tool_result: str,
    structured_data: Any | None,
    requested_view: str = "auto",
) -> dict[str, Any]:
    """Prepare bounded, truthful view candidates from the real MCP result.

    This function does NOT decide the final visualization in the MCP Apps flow.
    It only derives safe candidate data (table/chart/timeline/etc.) from Uyuni.
    ``PresentationAgent`` chooses the final view with the LLM afterwards.
    ``requested_view`` remains only for unit-test/backward compatibility and for
    the deterministic fallback if the presentation LLM fails.
    """

    parsed = structured_data if isinstance(structured_data, (dict, list)) else None
    if parsed is None:
        parsed = parse_structured_value(tool_result)

    title = humanize_tool_name(tool_name)
    payload: dict[str, Any] = {
        "schemaVersion": 1,
        "source": "Uyuni MCP",
        "toolName": tool_name,
        "title": title,
        "requestedView": requested_view,
        "views": [],
        "initialView": "empty",
        "empty": False,
        "metrics": [],
        "columns": [],
        "rows": [],
        "chart": None,
        "distribution": [],
        "detail": [],
        "timeline": [],
        "notice": None,
    }

    if parsed is None:
        payload["notice"] = "El resultado no contiene una estructura tabular representable; se mantiene la respuesta textual real."
        payload["views"] = ["raw"]
        payload["initialView"] = "raw"
        payload["rawPreview"] = _truncate_text(tool_result, 4000)
        return payload

    records = find_best_record_list(parsed)
    if records is not None:
        if not records:
            payload["empty"] = True
            payload["views"] = ["empty"]
            payload["initialView"] = "empty"
            payload["metrics"] = [{"label": "Resultados", "value": 0, "hint": "Sin elementos"}]
            return payload

        columns, rows = build_table(records)
        payload["columns"] = columns
        payload["rows"] = rows
        payload["metrics"] = build_metrics(records)
        payload["distribution"] = build_distribution(records)
        payload["chart"] = build_numeric_chart(records)
        if payload["chart"] is None and payload["distribution"]:
            payload["chart"] = build_category_count_chart(payload["distribution"])
        payload["timeline"] = build_timeline(records)
        if len(records) == 1:
            payload["detail"] = build_detail(records[0])
        payload["totalRows"] = len(records)
        payload["truncated"] = len(records) > _TABLE_MAX_ROWS

        views: list[str] = []
        if payload["metrics"]:
            views.append("metrics")
        if columns and rows:
            views.append("table")
        if payload["chart"]:
            views.append("bar")
            if payload["chart"].get("supportsLine"):
                views.append("line")
        if payload["distribution"]:
            views.append("donut")
        if payload["detail"]:
            views.append("detail")
        if payload["timeline"]:
            views.append("timeline")
        payload["views"] = _unique(views) or ["table"]
        payload["initialView"] = choose_initial_view(requested_view, payload["views"], records)
        return payload

    if isinstance(parsed, dict):
        detail = build_detail(parsed)
        payload["detail"] = detail
        payload["metrics"] = build_object_metrics(parsed)
        views = []
        if payload["metrics"]:
            views.append("metrics")
        if detail:
            views.append("detail")
        if not views:
            views = ["raw"]
            payload["rawPreview"] = _truncate_text(tool_result, 4000)
        payload["views"] = views
        payload["initialView"] = choose_initial_view(requested_view, views, None)
        return payload

    payload["views"] = ["raw"]
    payload["initialView"] = "raw"
    payload["rawPreview"] = _truncate_text(tool_result, 4000)
    return payload


def parse_structured_value(text: str) -> Any | None:
    clean = text.strip()
    if not clean:
        return None

    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s*```$", "", clean)

    candidates = [clean]
    starts = [(clean.find("{"), clean.rfind("}")), (clean.find("["), clean.rfind("]"))]
    for start, end in starts:
        if start != -1 and end > start:
            candidates.append(clean[start : end + 1])

    for candidate in candidates:
        for parser in (json.loads, ast.literal_eval):
            try:
                value = parser(candidate)
            except (ValueError, SyntaxError, json.JSONDecodeError):
                continue
            if isinstance(value, str) and value.strip().startswith(("{", "[")):
                try:
                    nested = json.loads(value)
                    if isinstance(nested, (dict, list)):
                        return nested
                except json.JSONDecodeError:
                    pass
            if isinstance(value, (dict, list)):
                return value
    return None


def find_best_record_list(value: Any) -> list[dict[str, Any]] | None:
    if isinstance(value, list) and not value:
        return []

    candidates: list[list[dict[str, Any]]] = []
    empty_collection_found = False

    def visit(node: Any, depth: int) -> None:
        nonlocal empty_collection_found
        if depth > 4:
            return
        if isinstance(node, list):
            if not node:
                empty_collection_found = True
                return
            dict_items = [item for item in node if isinstance(item, dict)]
            if len(dict_items) == len(node):
                candidates.append(dict_items)
                return
            for item in node[:12]:
                visit(item, depth + 1)
            return
        if isinstance(node, dict):
            preferred = (
                "data", "items", "results", "systems", "servers", "hosts", "updates",
                "patches", "errata", "events", "actions", "groups", "activation_keys",
                "activationKeys", "packages", "history",
            )
            seen: set[str] = set()
            for key in preferred:
                if key in node:
                    seen.add(key)
                    visit(node[key], depth + 1)
            for key, child in node.items():
                if key not in seen:
                    visit(child, depth + 1)

    visit(value, 0)
    if candidates:
        return max(candidates, key=len)
    if empty_collection_found and isinstance(value, (dict, list)):
        # Empty collection is meaningful for read-only fleet queries.
        for key in ("data", "items", "results", "systems", "updates", "events", "actions", "groups", "packages"):
            if isinstance(value, dict) and key in value and value[key] == []:
                return []
        if value == []:
            return []
    return None


def build_table(records: Sequence[dict[str, Any]]) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    keys: list[str] = []
    for record in records[:_TABLE_MAX_ROWS]:
        for raw_key, value in record.items():
            key = str(raw_key)
            if key not in keys and is_displayable(value):
                keys.append(key)
            if len(keys) >= _TABLE_MAX_COLUMNS:
                break
        if len(keys) >= _TABLE_MAX_COLUMNS:
            break

    columns = [{"key": key, "label": humanize_key(key)} for key in keys]
    rows = [
        {key: display_value(record.get(key)) for key in keys}
        for record in records[:_TABLE_MAX_ROWS]
    ]
    return columns, rows


def build_metrics(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = [
        {"label": "Resultados", "value": len(records), "hint": "Elementos devueltos"}
    ]
    keys = ordered_keys(records)

    # Status/category diversity gives an informative second metric without inventing values.
    status_key = next((key for key in keys if contains_any(key.lower(), _STATUS_HINTS)), None)
    if status_key:
        values = [str(display_value(r.get(status_key))) for r in records if r.get(status_key) is not None]
        if values:
            metrics.append({"label": humanize_key(status_key), "value": len(set(values)), "hint": "Valores distintos"})

    for key in keys:
        if looks_like_identifier(key) or not contains_any(key.lower(), _METRIC_HINTS):
            continue
        nums = [to_number(r.get(key)) for r in records if r.get(key) is not None]
        nums = [n for n in nums if n is not None]
        if len(nums) >= 1:
            total = sum(nums)
            metrics.append({"label": f"Total {humanize_key(key)}", "value": _pretty_number(total), "hint": f"Suma de {len(nums)} valores"})
            break

    return metrics[:4]


def build_object_metrics(value: dict[str, Any]) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    for key, item in value.items():
        if looks_like_identifier(str(key)):
            continue
        number = to_number(item)
        if number is not None and contains_any(str(key).lower(), _METRIC_HINTS):
            metrics.append({"label": humanize_key(str(key)), "value": _pretty_number(number), "hint": "Valor real"})
        if len(metrics) >= 4:
            break
    return metrics


def build_numeric_chart(records: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    if len(records) < 2:
        return None
    keys = ordered_keys(records)
    numeric_keys = [key for key in keys if numeric_series(records, key) and not looks_like_identifier(key)]
    strong = [key for key in numeric_keys if contains_any(key.lower(), _METRIC_HINTS)]
    metric_key = strong[0] if strong else (numeric_keys[0] if numeric_keys else None)
    if metric_key is None:
        return None

    label_key = choose_label_key(records, keys, metric_key)
    if label_key is None:
        return None

    limited = list(records[:_CHART_MAX_POINTS])
    labels = [str(display_value(record.get(label_key))) for record in limited]
    values = [to_number(record.get(metric_key)) for record in limited]
    if any(value is None for value in values):
        return None

    return {
        "labelKey": label_key,
        "metricKey": metric_key,
        "xLabel": humanize_key(label_key),
        "yLabel": humanize_key(metric_key),
        "labels": labels,
        "values": values,
        "derived": False,
        "supportsLine": contains_any(label_key.lower(), _TIME_HINTS),
        "truncated": len(records) > _CHART_MAX_POINTS,
    }


def build_category_count_chart(distribution: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """Build a truthful bar chart from an already-derived categorical count.

    The only derived operation is counting records per real category; no values
    are inferred by the LLM. A line chart is deliberately disabled because a
    categorical distribution has no meaningful temporal/order axis.
    """

    if not distribution:
        return None
    labels = [str(item.get("label", "")) for item in distribution[:_CHART_MAX_POINTS]]
    values = [to_number(item.get("value")) for item in distribution[:_CHART_MAX_POINTS]]
    if not labels or any(value is None for value in values):
        return None

    field = str(distribution[0].get("field") or "Categoría")
    return {
        "labelKey": field,
        "metricKey": "count",
        "xLabel": field,
        "yLabel": "Número de registros",
        "labels": labels,
        "values": values,
        "derived": True,
        "derivation": "category_count",
        "supportsLine": False,
        "truncated": len(distribution) > _CHART_MAX_POINTS,
    }


def build_distribution(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(records) < 2:
        return []
    keys = ordered_keys(records)
    candidates = [
        key for key in keys
        if contains_any(key.lower(), _STATUS_HINTS + ("group", "category", "type", "os", "architecture"))
        and label_series(records, key)
    ]
    if not candidates:
        candidates = [key for key in keys if label_series(records, key)]

    for key in candidates:
        values = [str(display_value(r.get(key))) for r in records if r.get(key) is not None]
        counts = Counter(values)
        if 2 <= len(counts) <= 8:
            return [
                {"label": label, "value": count, "field": humanize_key(key)}
                for label, count in counts.most_common(8)
            ]
    return []


def build_timeline(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    if not records:
        return []
    keys = ordered_keys(records)
    time_key = next((key for key in keys if contains_any(key.lower(), _TIME_HINTS)), None)
    if not time_key:
        return []

    label_key = next(
        (
            key for key in keys
            if key != time_key and contains_any(key.lower(), ("name", "action", "event", "summary", "type", "status"))
        ),
        None,
    )
    status_key = next((key for key in keys if key != time_key and contains_any(key.lower(), _STATUS_HINTS)), None)

    items: list[dict[str, Any]] = []
    for record in records[:30]:
        when = record.get(time_key)
        if when is None:
            continue
        title = display_value(record.get(label_key)) if label_key else humanize_key(time_key)
        items.append(
            {
                "time": str(display_value(when)),
                "title": str(title),
                "status": str(display_value(record.get(status_key))) if status_key and record.get(status_key) is not None else "",
            }
        )
    return items


def build_detail(value: dict[str, Any]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for key, item in value.items():
        if not is_displayable(item):
            continue
        items.append({"label": humanize_key(str(key)), "value": str(display_value(item))})
        if len(items) >= 20:
            break
    return items


def choose_initial_view(requested: str, views: Sequence[str], records: Sequence[dict[str, Any]] | None) -> str:
    if requested in views:
        return requested
    if requested == "detail" and "table" in views and records and len(records) == 1:
        return "table"
    if requested != "auto":
        # Requested representation is impossible for the real data; choose a safe fallback.
        if "table" in views:
            return "table"
        return views[0]

    if records is not None:
        if len(records) == 1 and "table" in views:
            return "table"
        if "table" in views:
            return "table"
    if "detail" in views:
        return "detail"
    if "metrics" in views:
        return "metrics"
    return views[0] if views else "empty"


def ordered_keys(records: Sequence[dict[str, Any]]) -> list[str]:
    keys: list[str] = []
    for record in records[:20]:
        for key in record:
            key = str(key)
            if key not in keys:
                keys.append(key)
    return keys


def choose_label_key(records: Sequence[dict[str, Any]], keys: Sequence[str], metric_key: str) -> str | None:
    candidates = [key for key in keys if key != metric_key]
    hinted = [key for key in candidates if contains_any(key.lower(), _LABEL_HINTS) and label_series(records, key)]
    if hinted:
        return hinted[0]
    textual = [key for key in candidates if label_series(records, key)]
    return textual[0] if textual else None


def numeric_series(records: Sequence[dict[str, Any]], key: str) -> bool:
    seen = 0
    for record in records[:_CHART_MAX_POINTS]:
        if key not in record or record[key] is None:
            continue
        if to_number(record[key]) is None:
            return False
        seen += 1
    return seen >= 2


def label_series(records: Sequence[dict[str, Any]], key: str) -> bool:
    seen = 0
    for record in records[:_CHART_MAX_POINTS]:
        value = record.get(key)
        if value is None:
            continue
        if isinstance(value, (dict, list, tuple, set)) or isinstance(value, bool):
            return False
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return False
        seen += 1
    return seen >= 2


def looks_like_identifier(key: str) -> bool:
    normalized = key.lower().strip()
    return normalized in _ID_HINTS or normalized.endswith("_id") or normalized.startswith("id_")


def to_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        clean = value.strip().replace("%", "").replace(",", ".")
        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", clean):
            try:
                number = float(clean)
                return number if math.isfinite(number) else None
            except ValueError:
                return None
    return None


def is_displayable(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def display_value(value: Any) -> Any:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Sí" if value else "No"
    if isinstance(value, float):
        return _pretty_number(value)
    return value


def _pretty_number(value: float) -> int | float:
    if float(value).is_integer():
        return int(value)
    return round(value, 2)


def humanize_key(key: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", key)
    text = text.replace("_", " ").replace("-", " ")
    return " ".join(part for part in text.split()).strip().capitalize()


def humanize_tool_name(tool_name: str) -> str:
    return humanize_key(tool_name)


def contains_any(text: str, needles: Sequence[str]) -> bool:
    return any(needle in text for needle in needles)


def _unique(values: Sequence[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out


def _truncate_text(text: str, limit: int) -> str:
    clean = text.strip()
    return clean if len(clean) <= limit else clean[:limit] + "…"



def apply_ai_selection(
    payload: dict[str, Any],
    *,
    selected_view: str,
    reason: str = "",
    title: str | None = None,
    mode: str = "llm",
) -> dict[str, Any]:
    """Apply an LLM presentation decision without allowing it to alter data.

    The LLM may only select one of the safe views already present in ``payload``.
    All rows, metrics, series and timeline entries remain server-derived.
    """

    views = [view for view in payload.get("views", []) if isinstance(view, str)]
    if selected_view not in views:
        raise ValueError(
            f"Vista seleccionada no permitida: {selected_view!r}. Permitidas: {views}."
        )

    payload["initialView"] = selected_view
    if title:
        payload["title"] = title
    payload["presentationSelection"] = {
        "mode": mode,
        "selectedView": selected_view,
        "reason": reason,
    }
    return payload
