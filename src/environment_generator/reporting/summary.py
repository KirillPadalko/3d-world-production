"""Plain-text rendering of reports for terminals and logs."""

from __future__ import annotations

from collections.abc import Iterable

from environment_generator.core.issues import ValidationIssue, sort_issues
from environment_generator.models.report import GenerationReport, StageStatus

_STATUS_MARK = {
    StageStatus.SUCCEEDED: "ok  ",
    StageStatus.FAILED: "FAIL",
    StageStatus.SKIPPED: "skip",
}


def render_issues(issues: Iterable[ValidationIssue], limit: int = 25) -> list[str]:
    ordered = sort_issues(issues)
    lines = [f"  {issue.format()}" for issue in ordered[:limit]]
    if len(ordered) > limit:
        lines.append(f"  ... {len(ordered) - limit} more (see the JSON report)")
    return lines


def render_report(report: GenerationReport, issue_limit: int = 25) -> str:
    title = "DRY RUN" if report.dry_run else "GENERATION"
    status = "succeeded" if report.success else "FAILED"
    lines = [f"{title} {status} - {report.generator.name} {report.generator.version}"]
    if report.blueprint_id:
        lines.append(
            f"  blueprint={report.blueprint_id} recipe={report.recipe_id} "
            f"overrides={report.overrides_id or '-'} seed={report.seed}"
        )
    lines.append("Stages:")
    for stage in report.stages:
        duration = f"{stage.duration_ms:9.1f} ms" if stage.duration_ms is not None else " " * 12
        details = ", ".join(f"{k}={v}" for k, v in stage.summary.items() if k != "content_hash")
        lines.append(
            f"  [{_STATUS_MARK[stage.status]}] {stage.name:<16} {duration}  {details}".rstrip()
        )
    if report.statistics:
        stats = ", ".join(f"{k}={v}" for k, v in report.statistics.items())
        lines.append(f"Statistics: {stats}")
    counts = report.issue_counts
    if counts:
        lines.append(
            f"Issues: {counts.get('error', 0)} error(s), {counts.get('warning', 0)} warning(s), "
            f"{counts.get('info', 0)} info"
        )
    issues = [issue for stage in report.stages for issue in stage.issues]
    lines.extend(render_issues(issues, issue_limit))
    if report.manifest_content_hash:
        lines.append(f"Manifest hash: {report.manifest_content_hash}")
    if report.outputs:
        lines.append("Outputs: " + ", ".join(sorted(report.outputs.values())))
    return "\n".join(lines)
