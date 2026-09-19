"""Resolves analyzer observations through the lab's own instrument mappings.

The backend matches an observation to an order item by catalog code alone: it
holds no copy of the per-code mappings the Instrumentos page curates. Analyzers
that report LOINC codes (the Mindray BC-30s sends "6690-2" for WBC) or
positional ones (the COR50 sends TP_0..TP_3) therefore matched no order item,
and linking came back "instrument payload matched an order but no order items
matched the observation codes".

Local mode never hit this, because it resolves every observation against
instrument_result_mappings before writing to the order. This module does that
same resolution on the client, so what reaches the server already carries the
lab's own test code, value and unit. The desktop app uses it when a capture is
linked by hand, and the headless importer for unattended imports.

An observation with no mapping is passed through untouched, so the analyzers
whose engine profile already emits the lab's codes (urinalysis, CM250) keep
matching on the server exactly as they did.
"""

from __future__ import annotations

import ast as _ast
import operator as _operator
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from spdxlims.database import Database, InstrumentResultMappingRecord

_FORMULA_OPS: dict = {
    _ast.Add: _operator.add,
    _ast.Sub: _operator.sub,
    _ast.Mult: _operator.mul,
    _ast.Div: _operator.truediv,
    _ast.USub: _operator.neg,
    _ast.UAdd: _operator.pos,
}


def safe_eval_formula(formula: str, x: float) -> float:
    """Evaluate a simple arithmetic formula with variable x.
    If the formula starts with an operator (e.g. *1000, /10, +5, -2) x is implied."""
    normalized = formula.strip()
    if normalized and normalized[0] in ("*", "/", "+", "-") and "x" not in normalized:
        normalized = "x " + normalized

    def _eval(node: _ast.AST) -> float:
        if isinstance(node, _ast.Expression):
            return _eval(node.body)
        if isinstance(node, _ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, _ast.Name) and node.id == "x":
            return x
        if isinstance(node, _ast.BinOp) and type(node.op) in _FORMULA_OPS:
            return _FORMULA_OPS[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, _ast.UnaryOp) and type(node.op) in _FORMULA_OPS:
            return _FORMULA_OPS[type(node.op)](_eval(node.operand))
        raise ValueError("unsupported expression")

    return _eval(_ast.parse(normalized, mode="eval"))


def normalize_test_code(value: str) -> str:
    return "".join(character for character in value.upper().strip() if character.isalnum() or character in {"-", "_"})


def extract_code_from_test_name(test_name: str) -> str:
    text = str(test_name or "")
    if "(" in text and ")" in text:
        candidate = text.rsplit("(", 1)[-1].split(")", 1)[0]
        return normalize_test_code(candidate)
    return ""


def observation_raw_code(obs: dict[str, Any]) -> str:
    return normalize_test_code(str(obs.get("instrument_test_code") or obs.get("mapped_lis_test_id") or ""))


def observation_value(obs: dict[str, Any], result_kind: str) -> str:
    if result_kind == "numeric":
        # Prefer the raw string from the instrument so trailing zeros are preserved
        # (e.g. "1.020" must not become "1.02" via float conversion)
        for key in ("value_raw", "value_text"):
            raw = obs.get(key)
            if raw is not None:
                s = str(raw).strip().replace(",", "")
                if s:
                    try:
                        float(s)
                        return s
                    except ValueError:
                        pass
        if obs.get("value_numeric") is not None:
            val = float(obs["value_numeric"])
            return str(int(val)) if val == int(val) else str(val)
        return ""
    for key in ("value_text", "value_raw", "value_numeric"):
        value = obs.get(key)
        if value is not None and str(value).strip():
            s = str(value).strip()
            return s.split("^")[0].strip() if "^" in s else s
    return ""


def mapping_targets_entry(mapping: InstrumentResultMappingRecord, entry: Any) -> bool:
    """Whether a mapping points at this order entry.

    Local mode compares catalog ids. In server mode the order's tests come from
    the backend, whose ids are UUIDs the local mapping table knows nothing
    about, so the entry is identified by the code the backend appends to the
    test name ("Leucocitos (WBC)").
    """
    if str(mapping.test_id) == str(entry.test_id):
        return True
    code = normalize_test_code(mapping.test_code or "")
    return bool(code) and code == extract_code_from_test_name(entry.test_name)


def resolve_observation_mapping(
    database: Database,
    *,
    profile_id: str,
    device_id: str,
    obs: dict[str, Any],
    entries: Sequence[Any] = (),
    profile_mappings: Sequence[InstrumentResultMappingRecord] | None = None,
) -> InstrumentResultMappingRecord | None:
    code = observation_raw_code(obs)
    if not code:
        return None
    mapping = database.resolve_instrument_result_mapping(
        instrument_profile=profile_id,
        device_id=device_id,
        raw_code=code,
        specimen_type=str(obs.get("specimen_type") or obs.get("sample_type") or ""),
        panel_hint=str(obs.get("panel_hint") or obs.get("panel") or ""),
    )
    if mapping is not None:
        return mapping
    # A mapping saved against a specimen or a panel (the COR50's "2" -> TPT is
    # scoped to "plasma citratado 2 ml") only resolves when those are supplied,
    # and the analyzer does not send them. Try the order's own tests instead,
    # keeping a candidate only when it points back at the test it was tried for.
    for entry in entries:
        candidate = database.resolve_instrument_result_mapping(
            instrument_profile=profile_id,
            device_id=device_id,
            raw_code=code,
            specimen_type=entry.specimen_type or "",
            panel_hint=entry.source_label or "",
        )
        if candidate is not None and mapping_targets_entry(candidate, entry):
            return candidate
    if not entries:
        return None
    # Last resort: a mapping scoped to a panel name this database does not use
    # can never match on scope - the COR50's "2" is saved under the local panel
    # "tp y ttp", while the server order calls it "TIEMPO DE PROTROMBINA Y
    # TROMBOPLASTINA". Take a mapping for this code regardless of its scope, but
    # only when the test it points at is one of the order's own, which is what
    # keeps a scoped mapping from landing on the wrong test.
    if profile_mappings is None:
        profile_mappings = database.list_instrument_result_mappings(instrument_profile=profile_id)
    for mapping in profile_mappings:
        if not mapping.is_active or normalize_test_code(mapping.raw_code) != code:
            continue
        for entry in entries:
            if mapping_targets_entry(mapping, entry):
                return mapping
    return None


def apply_value_transform(
    mapping: InstrumentResultMappingRecord | None,
    result_value: str,
    *,
    numeric: bool,
    fallback_multiplier: float | None = None,
) -> str:
    """Apply the mapping's slice, formula/multiplier and rounding to a value."""
    if mapping is not None and result_value:
        slice_start = mapping.value_slice_start
        slice_end = mapping.value_slice_end
        if slice_start is not None or slice_end is not None:
            py_start = (slice_start - 1) if slice_start is not None else 0
            py_end = slice_end if slice_end is not None else None
            result_value = result_value[py_start:py_end].strip()
    value_formula = mapping.value_formula if mapping is not None else None
    multiplier = (mapping.value_multiplier if mapping is not None and mapping.value_multiplier else None) or fallback_multiplier
    if numeric and result_value:
        if value_formula:
            try:
                raw = float(Decimal(result_value.replace(",", "")))
                transformed = Decimal(str(safe_eval_formula(value_formula, raw)))
                result_value = _trim_decimal(transformed)
            except (ValueError, TypeError, InvalidOperation, ZeroDivisionError):
                pass
        elif multiplier:
            try:
                multiplied = Decimal(result_value.replace(",", "")) * Decimal(str(multiplier))
                result_value = _trim_decimal(multiplied)
            except (ValueError, TypeError, InvalidOperation):
                pass
    decimal_places = mapping.decimal_places if mapping is not None else None
    if decimal_places is not None and numeric and result_value:
        try:
            result_value = str(round(Decimal(result_value.replace(",", "")), decimal_places))
        except (ValueError, TypeError, InvalidOperation):
            pass
    return result_value


def _trim_decimal(value: Decimal) -> str:
    formatted = format(value, "f")
    if "." in formatted:
        int_part, dec_part = formatted.split(".", 1)
        return formatted if dec_part.rstrip("0") else int_part
    return formatted


def resolve_payload(
    database: Database,
    capture: dict[str, Any],
    result: dict[str, Any],
    entries: Sequence[Any] = (),
) -> dict[str, Any]:
    """Return the capture's parsed result with its observations mapped for the server."""
    message = result.get("message")
    if not isinstance(message, dict):
        return result
    observations = [obs for obs in (message.get("observations") or []) if isinstance(obs, dict)]
    if not observations:
        return result
    profile_id = str(capture.get("profile_id") or message.get("source_profile_id") or "").strip()
    device_id = str(capture.get("device_id") or message.get("source_device_id") or "").strip()
    # Read the profile's mappings once, not once per observation that needs the
    # scope-blind last resort in resolve_observation_mapping.
    profile_mappings = database.list_instrument_result_mappings(instrument_profile=profile_id) if entries else []
    resolved = [
        _resolve_observation(
            database,
            obs,
            profile_id=profile_id,
            device_id=device_id,
            entries=entries,
            profile_mappings=profile_mappings,
        )
        for obs in observations
    ]
    return {**result, "message": {**message, "observations": resolved}}


def _resolve_observation(
    database: Database,
    obs: dict[str, Any],
    *,
    profile_id: str,
    device_id: str,
    entries: Sequence[Any],
    profile_mappings: Sequence[InstrumentResultMappingRecord] | None = None,
) -> dict[str, Any]:
    mapping = resolve_observation_mapping(
        database,
        profile_id=profile_id,
        device_id=device_id,
        obs=obs,
        entries=entries,
        profile_mappings=profile_mappings,
    )
    if mapping is None:
        return dict(obs)
    resolved = dict(obs)
    if (mapping.test_code or "").strip():
        resolved["mapped_lis_test_id"] = mapping.test_code.strip()
    if (mapping.unit_override or "").strip():
        resolved["units_normalized"] = mapping.unit_override.strip()
    numeric_value = observation_value(obs, "numeric")
    if numeric_value:
        transformed = apply_value_transform(mapping, numeric_value, numeric=True)
        if transformed and transformed != numeric_value:
            _set_observation_value(resolved, transformed, numeric=True)
        return resolved
    text_value = observation_value(obs, "text")
    transformed = apply_value_transform(mapping, text_value, numeric=False)
    # An empty transform is dropped rather than sent: a character range that
    # does not fit the value (the urinalysis LEU range starts at 0, outside the
    # 1-based range the editor asks for) would otherwise blank out a reading the
    # analyzer did report.
    if text_value and transformed and transformed != text_value:
        _set_observation_value(resolved, transformed, numeric=False)
    return resolved


def _set_observation_value(obs: dict[str, Any], value: str, *, numeric: bool) -> None:
    """Write a transformed value over every field the server may read it from.

    The server takes value_numeric for a numeric test and value_text/value_raw
    otherwise, so leaving any of them holding the untransformed number would
    store the analyzer's reading instead of the mapped one (the Mindray's PLT
    count is 245 where the lab reports 245000).
    """
    obs["value_raw"] = value
    obs["value_text"] = value
    if not numeric:
        obs["value_numeric"] = None
        return
    try:
        obs["value_numeric"] = float(Decimal(value.replace(",", "")))
    except (InvalidOperation, ValueError):
        obs["value_numeric"] = None
