"""Canonical JSON serialisation and content fingerprints.

Two serialisations are provided:

* :func:`canonical_json` - compact, key-sorted, floats rounded to
  :data:`FLOAT_DECIMALS`. Used for hashing; byte-identical for identical data.
* :func:`pretty_json` - human-friendly and diff-friendly, keeps key order and
  writes short numeric arrays (points, colours, heightfield rows) on one line.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

FLOAT_DECIMALS = 4


def canonicalize(value: Any, decimals: int = FLOAT_DECIMALS) -> Any:
    """Recursively round floats, normalise ``-0.0`` and convert tuples to lists."""
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"non-finite float cannot be serialised: {value!r}")
        rounded = round(value, decimals)
        return 0.0 if rounded == 0.0 else rounded
    if isinstance(value, Mapping):
        return {str(k): canonicalize(v, decimals) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonicalize(v, decimals) for v in value]
    raise TypeError(f"unsupported type for canonical JSON: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        canonicalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fingerprint(value: Any) -> str:
    """``sha256:<hex>`` digest of the canonical JSON form of ``value``."""
    return "sha256:" + sha256_hex(canonical_json(value))


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _dump_scalar(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _inline(value: list[Any]) -> str:
    return "[" + ", ".join(_dump_scalar(v) for v in value) + "]"


def _format(value: Any, level: int, indent: int) -> str:
    if _is_scalar(value):
        return _dump_scalar(value)
    pad = " " * (indent * (level + 1))
    closing = " " * (indent * level)
    if isinstance(value, list):
        if not value:
            return "[]"
        if all(_is_scalar(v) for v in value):
            return _inline(value)
        items = [_format(v, level + 1, indent) for v in value]
        return "[\n" + ",\n".join(pad + item for item in items) + "\n" + closing + "]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = [
            f"{pad}{_dump_scalar(str(k))}: {_format(v, level + 1, indent)}"
            for k, v in value.items()
        ]
        return "{\n" + ",\n".join(items) + "\n" + closing + "}"
    raise TypeError(f"unsupported type for JSON: {type(value).__name__}")


def pretty_json(value: Any, indent: int = 2) -> str:
    """Readable JSON with rounded floats and inline scalar arrays; ends with a newline."""
    return _format(canonicalize(value), 0, indent) + "\n"
