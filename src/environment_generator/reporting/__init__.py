"""Human-facing outputs: text summaries and the SVG preview."""

from environment_generator.reporting.summary import render_issues, render_report
from environment_generator.reporting.svg_preview import render_svg

__all__ = ["render_issues", "render_report", "render_svg"]
