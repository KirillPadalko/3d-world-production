"""JSON Merge Patch (RFC 7396)."""

from __future__ import annotations

import copy
from typing import Any


def json_merge_patch(target: Any, patch: Any) -> Any:
    """Apply an RFC 7396 merge patch and return a new document.

    Objects merge recursively, ``null`` removes a key (restoring its default
    once the result is validated again) and any other value replaces the
    target value wholesale, including arrays.
    """
    if not isinstance(patch, dict):
        return copy.deepcopy(patch)
    result: dict[str, Any] = copy.deepcopy(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = json_merge_patch(result.get(key), value)
    return result
