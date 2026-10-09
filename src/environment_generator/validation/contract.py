"""Loading documents and validating them against their public contract."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from environment_generator.core.errors import ContractValidationError, InputLoadError
from environment_generator.core.issues import ValidationIssue

ModelT = TypeVar("ModelT", bound=BaseModel)

#: A document given as a file path or as already-parsed JSON data.
InputSource = Path | str | Mapping[str, Any]

MAX_DOCUMENT_BYTES = 64 * 1024 * 1024


def read_json_document(source: InputSource, label: str) -> dict[str, Any]:
    """Return the JSON object for ``source`` (a path or a mapping)."""
    if isinstance(source, Mapping):
        return dict(source)
    path = Path(source)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise InputLoadError(f"Cannot read {label} file '{path}': {exc.strerror or exc}") from exc
    if size > MAX_DOCUMENT_BYTES:
        raise InputLoadError(f"{label} file '{path}' is larger than {MAX_DOCUMENT_BYTES} bytes")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise InputLoadError(f"Cannot read {label} file '{path}': {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputLoadError(
            f"{label} file '{path}' is not valid JSON (line {exc.lineno}, column {exc.colno}): "
            f"{exc.msg}"
        ) from exc
    if not isinstance(data, dict):
        raise InputLoadError(f"{label} file '{path}' must contain a JSON object")
    return data


def format_location(loc: tuple[int | str, ...]) -> str:
    """Render a pydantic error location as ``roads[0].geometry.points``."""
    text = ""
    for part in loc:
        if isinstance(part, int):
            text += f"[{part}]"
        else:
            text += f".{part}" if text else str(part)
    return text


def validation_issues(error: ValidationError, label: str) -> list[ValidationIssue]:
    issues = []
    for detail in error.errors(include_url=False):
        location = format_location(tuple(detail["loc"]))
        issues.append(
            ValidationIssue.error(
                "CONTRACT_" + detail["type"].upper(),
                detail["msg"],
                location=f"{label}:{location}" if location else label,
            )
        )
    return issues


def parse_document(model: type[ModelT], data: Mapping[str, Any], label: str) -> ModelT:
    """Validate ``data`` against ``model``; raises :class:`ContractValidationError`."""
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        issues = validation_issues(exc, label)
        raise ContractValidationError(
            f"{label} does not satisfy its contract ({len(issues)} problem(s))", issues=issues
        ) from exc


def load_document(model: type[ModelT], source: InputSource, label: str) -> ModelT:
    return parse_document(model, read_json_document(source, label), label)
