"""Top-down SVG preview of a scene manifest.

A dependency-free, read-only visualisation for humans and reviewers. It only
consumes the public manifest, so it can render output from any generator
implementation (or a manifest edited by hand). Manifest coordinates are in
the location frame: the map shows X (east) to the right and Z (north) up;
yaw turns clockwise from north.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from xml.sax.saxutils import escape, quoteattr

from environment_generator.core.frames import location_yaw_to_generator
from environment_generator.core.geometry import rectangle_corners
from environment_generator.models.assets import AssetCategory
from environment_generator.models.scene import (
    EntityPolygon,
    EntityPolyline,
    ManifestEntity,
    SceneManifest,
)

MAP_SIZE_PX = 900.0
MARGIN_PX = 24.0
LEGEND_WIDTH_PX = 210.0
HEADER_PX = 34.0

RGB = tuple[float, float, float]

GROUND_COLORS: dict[str, RGB] = {
    "grass": (122, 154, 82),
    "dirt": (150, 122, 86),
    "sand": (214, 196, 148),
    "gravel": (150, 146, 138),
    "snow": (232, 236, 240),
    "mud": (110, 92, 70),
    "rock": (128, 124, 120),
    "paved": (140, 140, 140),
}
ROAD_COLORS = {
    "asphalt": "#55585c",
    "concrete": "#8d9094",
    "gravel": "#a89f8f",
    "dirt": "#9c7d55",
    "cobblestone": "#7d6e63",
}
BUILDING_COLORS = {"intact": "#d9b38c", "damaged": "#b07a50", "ruined": "#6f5b4c"}
VEGETATION_COLORS = {
    "tree": "#2f6b34",
    "fruit_tree": "#5d8a2d",
    "bush": "#4f8c45",
    "hedge": "#3f7a3a",
    "grass_clump": "#9fbf5a",
}
FENCE_COLORS = {
    "stone_wall": "#8c8478",
    "brick_wall": "#9a5844",
    "concrete_wall": "#a3a3a3",
    "chain_link": "#c9ced3",
    "metal_railing": "#c9ced3",
    "wire": "#d8d2c4",
}
PLACEHOLDER_COLOR = "#e5383b"
LEGEND = [
    ("Road", "#55585c"),
    ("Water", "#4a8fc0"),
    ("Building", BUILDING_COLORS["intact"]),
    ("Damaged / ruined", BUILDING_COLORS["ruined"]),
    ("Fence / wall", "#6b4f33"),
    ("Tree / bush", VEGETATION_COLORS["tree"]),
    ("Infrastructure", "#6a4c93"),
    ("Prop", "#e08a2c"),
    ("Placeholder asset", PLACEHOLDER_COLOR),
]


def _fmt(value: float | int | str) -> str:
    return f"{value:.1f}" if isinstance(value, float) else str(value)


def element(tag: str, title: str | None = None, **attributes: float | int | str) -> str:
    """One SVG element; ``stroke_width`` style keywords become ``stroke-width``."""
    attrs = " ".join(
        f"{name.rstrip('_').replace('_', '-')}={quoteattr(_fmt(value))}"
        for name, value in attributes.items()
    )
    if title is None:
        return f"<{tag} {attrs}/>"
    return f"<{tag} {attrs}><title>{escape(title)}</title></{tag}>"


def text(x: float, y: float, content: str, **attributes: float | int | str) -> str:
    attrs = "".join(
        f" {name.rstrip('_').replace('_', '-')}={quoteattr(_fmt(value))}"
        for name, value in attributes.items()
    )
    return f'<text x="{x:.1f}" y="{y:.1f}"{attrs}>{escape(content)}</text>'


class _Canvas:
    def __init__(self, width_m: float, depth_m: float) -> None:
        self.scale = MAP_SIZE_PX / max(width_m, depth_m)
        self.width_m = width_m
        self.depth_m = depth_m
        self.map_w = width_m * self.scale
        self.map_h = depth_m * self.scale
        self.parts: list[str] = []

    def x(self, value: float) -> float:
        return MARGIN_PX + value * self.scale

    def y(self, value: float) -> float:
        return HEADER_PX + MARGIN_PX + (self.depth_m - value) * self.scale

    def points(self, coords: Sequence[tuple[float, float]]) -> str:
        return " ".join(f"{self.x(px):.1f},{self.y(py):.1f}" for px, py in coords)

    def add(self, markup: str) -> None:
        self.parts.append(markup)


def _rgb(color: RGB) -> str:
    r, g, b = (max(0, min(255, round(c))) for c in color)
    return f"#{r:02x}{g:02x}{b:02x}"


def _terrain(canvas: _Canvas, manifest: SceneManifest) -> None:
    terrain = manifest.terrain
    if terrain is None:
        canvas.add(
            element(
                "rect",
                x=canvas.x(0),
                y=canvas.y(canvas.depth_m),
                width=canvas.map_w,
                height=canvas.map_h,
                fill="#7a9a52",
            )
        )
        return
    base = GROUND_COLORS.get(terrain.ground_cover.value, GROUND_COLORS["grass"])
    low, high = terrain.min_elevation_m, terrain.max_elevation_m
    span = max(high - low, 1e-6)
    cell = terrain.cell_size_m
    heights = terrain.heights
    light = (-0.5, 0.5, 0.7)  # from the north-west, as on paper maps
    norm = math.sqrt(sum(c * c for c in light))
    for j in range(terrain.rows - 1):
        for i in range(terrain.columns - 1):
            h00, h10 = heights[j][i], heights[j][i + 1]
            h01, h11 = heights[j + 1][i], heights[j + 1][i + 1]
            nx = -((h10 - h00) + (h11 - h01)) / (2 * cell)
            ny = -((h01 - h00) + (h11 - h10)) / (2 * cell)
            shade = (nx * light[0] + ny * light[1] + light[2]) / (
                norm * math.sqrt(nx * nx + ny * ny + 1.0)
            )
            elevation = ((h00 + h10 + h01 + h11) / 4 - low) / span
            factor = (0.78 + 0.3 * elevation) * (0.55 + 0.5 * shade)
            x0 = min(i * cell, canvas.width_m)
            y1 = min((j + 1) * cell, canvas.depth_m)
            w = min((i + 1) * cell, canvas.width_m) - x0
            h = y1 - min(j * cell, canvas.depth_m)
            if w <= 0 or h <= 0:
                continue
            canvas.add(
                element(
                    "rect",
                    x=canvas.x(x0),
                    y=canvas.y(y1),
                    width=w * canvas.scale + 0.6,
                    height=h * canvas.scale + 0.6,
                    fill=_rgb((base[0] * factor, base[1] * factor, base[2] * factor)),
                )
            )


def _box(canvas: _Canvas, entity: ManifestEntity, fill: str, stroke: str) -> None:
    position = entity.transform.position
    corners = rectangle_corners(
        (position[0], position[2]),
        max(entity.dimensions.width_m, 0.3),
        max(entity.dimensions.depth_m, 0.3),
        location_yaw_to_generator(entity.transform.yaw_deg),
    )
    extra: dict[str, float | int | str] = {}
    if entity.placeholder:
        stroke = PLACEHOLDER_COLOR
        extra["stroke_dasharray"] = "3 2"
    canvas.add(
        element(
            "polygon",
            f"{entity.id} ({entity.archetype_id})",
            points=canvas.points(corners),
            fill=fill,
            stroke=stroke,
            stroke_width=1,
            **extra,
        )
    )


def _front_tick(canvas: _Canvas, entity: ManifestEntity) -> None:
    """Short line on the front (local +Z) edge to show orientation."""
    x, _, y = entity.transform.position
    yaw = math.radians(entity.transform.yaw_deg)
    fx, fy = math.sin(yaw), math.cos(yaw)
    reach = entity.dimensions.depth_m / 2.0
    canvas.add(
        element(
            "line",
            x1=canvas.x(x + fx * reach * 0.6),
            y1=canvas.y(y + fy * reach * 0.6),
            x2=canvas.x(x + fx * reach),
            y2=canvas.y(y + fy * reach),
            stroke="#3a2e25",
            stroke_width=2,
        )
    )


def _water(canvas: _Canvas, entities: list[ManifestEntity]) -> None:
    for entity in entities:
        if isinstance(entity.geometry, EntityPolygon):
            points = [(p[0], p[2]) for p in entity.geometry.points]
            canvas.add(
                element(
                    "polygon",
                    entity.id,
                    points=canvas.points(points),
                    fill="#4a8fc0",
                    fill_opacity="0.9",
                    stroke="#2f6f9f",
                    stroke_width=1.5,
                )
            )


def _roads(canvas: _Canvas, entities: list[ManifestEntity]) -> None:
    for entity in entities:
        color = ROAD_COLORS.get(str(entity.parameters.get("surface", "asphalt")), "#55585c")
        if isinstance(entity.geometry, EntityPolyline) and entity.geometry.width_m:
            points = [(p[0], p[2]) for p in entity.geometry.points]
            canvas.add(
                element(
                    "polyline",
                    entity.id,
                    points=canvas.points(points),
                    fill="none",
                    stroke=color,
                    stroke_width=entity.geometry.width_m * canvas.scale,
                    stroke_linecap="round",
                    stroke_linejoin="round",
                )
            )
        elif entity.kind == "junction":
            x, _, y = entity.transform.position
            radius = entity.dimensions.width_m / 2.0 * canvas.scale
            canvas.add(element("circle", cx=canvas.x(x), cy=canvas.y(y), r=radius, fill=color))


def _fences(canvas: _Canvas, entities: list[ManifestEntity]) -> None:
    for entity in entities:
        x, _, y = entity.transform.position
        yaw = math.radians(entity.transform.yaw_deg)
        half = entity.dimensions.width_m / 2.0
        # Local +X (the fence run) points east rotated clockwise by the yaw.
        dx, dy = math.cos(yaw) * half, -math.sin(yaw) * half
        color = FENCE_COLORS.get(entity.kind, "#6b4f33")
        canvas.add(
            element(
                "line",
                entity.id,
                x1=canvas.x(x - dx),
                y1=canvas.y(y - dy),
                x2=canvas.x(x + dx),
                y2=canvas.y(y + dy),
                stroke=PLACEHOLDER_COLOR if entity.placeholder else color,
                stroke_width=max(1.2, entity.dimensions.depth_m * canvas.scale),
            )
        )


def _infrastructure(canvas: _Canvas, entities: list[ManifestEntity]) -> list[ManifestEntity]:
    lines: list[ManifestEntity] = []
    for entity in entities:
        if isinstance(entity.geometry, EntityPolyline):
            lines.append(entity)
        elif max(entity.dimensions.width_m, entity.dimensions.depth_m) < 1.0:
            x, _, y = entity.transform.position
            canvas.add(
                element(
                    "circle",
                    entity.id,
                    cx=canvas.x(x),
                    cy=canvas.y(y),
                    r=2.6,
                    fill="#6a4c93",
                    stroke="#2d1f40",
                    stroke_width=0.8,
                )
            )
        else:
            _box(canvas, entity, "#8f74b8", "#2d1f40")
    return lines


def _vegetation(canvas: _Canvas, entities: list[ManifestEntity]) -> None:
    for entity in entities:
        x, _, y = entity.transform.position
        canopy = min(entity.dimensions.width_m, entity.dimensions.depth_m) / 2.0
        canvas.add(
            element(
                "circle",
                entity.id,
                cx=canvas.x(x),
                cy=canvas.y(y),
                r=max(canopy * canvas.scale, 1.2),
                fill=PLACEHOLDER_COLOR
                if entity.placeholder
                else VEGETATION_COLORS.get(entity.kind, "#3d7a3a"),
                fill_opacity="0.82",
                stroke="#1f3f22",
                stroke_width=0.5,
            )
        )


def _overhead_lines(canvas: _Canvas, entities: list[ManifestEntity]) -> None:
    for entity in entities:
        assert isinstance(entity.geometry, EntityPolyline)
        points = [(p[0], p[2]) for p in entity.geometry.points]
        width = (entity.geometry.width_m or 0.15) * canvas.scale
        canvas.add(
            element(
                "polyline",
                entity.id,
                points=canvas.points(points),
                fill="none",
                stroke="#2d1f40",
                stroke_width=max(width, 1.0),
                stroke_dasharray="6 3",
            )
        )


def _entities(canvas: _Canvas, manifest: SceneManifest) -> None:
    groups: dict[AssetCategory, list[ManifestEntity]] = {c: [] for c in AssetCategory}
    for entity in manifest.entities:
        groups[entity.category].append(entity)
    _water(canvas, groups[AssetCategory.WATER])
    _roads(canvas, groups[AssetCategory.ROAD])
    _fences(canvas, groups[AssetCategory.FENCE])
    for entity in groups[AssetCategory.BUILDING]:
        condition = str(entity.parameters.get("condition", "intact"))
        _box(canvas, entity, BUILDING_COLORS.get(condition, BUILDING_COLORS["intact"]), "#3a2e25")
        _front_tick(canvas, entity)
    for entity in groups[AssetCategory.PROP]:
        _box(canvas, entity, "#e08a2c", "#7a4a12")
    lines = _infrastructure(canvas, groups[AssetCategory.INFRASTRUCTURE])
    _vegetation(canvas, groups[AssetCategory.VEGETATION])
    _overhead_lines(canvas, lines)


def _legend(canvas: _Canvas, manifest: SceneManifest) -> None:
    left = MARGIN_PX * 2 + canvas.map_w
    top = HEADER_PX + MARGIN_PX
    canvas.add(text(left, top + 4, "Legend", class_="h"))
    for index, (label, color) in enumerate(LEGEND):
        y = top + 24 + index * 20
        canvas.add(
            element(
                "rect",
                x=left,
                y=y - 11,
                width=14,
                height=14,
                fill=color,
                stroke="#333",
                stroke_width=0.5,
            )
        )
        canvas.add(text(left + 22, y, label))
    stats_top = top + 24 + len(LEGEND) * 20 + 16
    canvas.add(text(left, stats_top, "Entities", class_="h"))
    lines = [f"total: {manifest.statistics.entity_count}"]
    lines.extend(f"{k}: {v}" for k, v in manifest.statistics.by_category.items())
    if manifest.statistics.placeholder_count:
        lines.append(f"placeholders: {manifest.statistics.placeholder_count}")
    for index, line in enumerate(lines):
        canvas.add(text(left, stats_top + 20 + index * 17, line))
    # Scale bar: the largest 1/2/5 x 10^n length not exceeding a quarter of the map.
    target = canvas.width_m / 4.0
    bar = 10 ** math.floor(math.log10(target))
    for step in (5, 2, 1):
        if bar * step <= target:
            bar *= step
            break
    bar_y = HEADER_PX + MARGIN_PX + canvas.map_h + 16
    canvas.add(
        element("rect", x=canvas.x(0), y=bar_y, width=bar * canvas.scale, height=5, fill="#222")
    )
    canvas.add(text(canvas.x(0) + bar * canvas.scale + 8, bar_y + 6, f"{bar:g} m"))
    canvas.add(text(canvas.x(canvas.width_m) - 4, bar_y + 6, "N ↑", text_anchor="end"))


def render_svg(manifest: SceneManifest) -> str:
    """Render ``manifest`` as a standalone SVG document."""
    canvas = _Canvas(manifest.extent.width_m, manifest.extent.depth_m)
    total_w = canvas.map_w + LEGEND_WIDTH_PX + MARGIN_PX * 3
    total_h = max(canvas.map_h + HEADER_PX + MARGIN_PX * 2 + 30, 420.0)
    source = manifest.source
    overrides = f" + {source.overrides_id}" if source.overrides_id else ""
    title = f"{source.location_name} - recipe {source.recipe_id}{overrides} - seed {source.seed}"
    subtitle = (
        f"{manifest.generator.name} {manifest.generator.version} - {manifest.content_hash[:23]}..."
    )
    canvas.add(
        element(
            "rect",
            x=canvas.x(0) - 1,
            y=canvas.y(canvas.depth_m) - 1,
            width=canvas.map_w + 2,
            height=canvas.map_h + 2,
            fill="none",
            stroke="#222",
        )
    )
    _terrain(canvas, manifest)
    _entities(canvas, manifest)
    _legend(canvas, manifest)
    header = text(MARGIN_PX, MARGIN_PX + 6, title, class_="t") + text(
        MARGIN_PX, MARGIN_PX + 24, subtitle, class_="s"
    )
    body = "\n".join(canvas.parts)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w:.0f}" height="{total_h:.0f}" '
        f'viewBox="0 0 {total_w:.0f} {total_h:.0f}" '
        'font-family="Helvetica, Arial, sans-serif" font-size="12">\n'
        "<style>.t{font-size:16px;font-weight:bold}.s{fill:#555}.h{font-weight:bold}</style>\n"
        f'<rect width="100%" height="100%" fill="#f4f1ea"/>\n{header}\n{body}\n</svg>\n'
    )
