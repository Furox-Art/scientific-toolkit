"""Fail-closed JSON decoder shared by both MCP wire transports.

Reject duplicate object keys at any nesting depth and non-finite numeric
values, which Python's default json.loads silently accepts or overflows to.
"""

from __future__ import annotations

import json
import math
from typing import Any


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite JSON number")
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate JSON object key")
        obj[key] = value
    return obj


def loads(payload: str | bytes) -> Any:
    """Decode untrusted wire JSON without ambiguous object membership."""
    return json.loads(
        payload,
        parse_float=_finite_float,
        parse_constant=_reject_constant,
        object_pairs_hook=_unique_keys,
    )
