#!/usr/bin/env python3
"""Measurement helpers for the video-to-blueprint skill.

All image coordinates are normalised: ``u`` from the left edge (0) to the
right edge (1), ``v`` from the top edge (0) to the bottom edge (1), as on the
grids drawn by ``frames.py grid``. Ground coordinates are the blueprint frame:
metres, ``x`` east, ``z`` north, origin at the south-west corner of the bounds.

Subcommands (all print JSON)::

    footprint --altitude M --focal35 MM [--aspect 16:9]
        ground covered by a camera pointing straight down
    map --ground-width M [--aspect 16:9 | --ground-height M] (--origin U V | --anchor U V X Z)
        [--up-bearing DEG] (--point NAME U V ... | --json FILE)
        image -> ground for a straight-down frame (or an orthophoto)
    ground --pair U V X Z (at least 4) (--point NAME U V ... | --json FILE)
        image -> ground through the ground-plane homography of an oblique frame
    yaw --up-bearing DEG --image-angle DEG
        yaw of an object whose front points image-angle clockwise from image-up
    ratio --ref-size M [--ref-min M --ref-max M] --ref-extent E --extent E
        size from a known reference object at the same distance and orientation
    combine VALUE:SIGMA [VALUE:SIGMA ...]
        weighted mean of independent estimates, with a consistency check
    along --path "X,Z X,Z ..." [--closed] --point X Z [--point X Z ...]
        fraction of a fence path's length at each point (for missingSections)

``--json FILE`` holds ``{"name": [u, v]}`` or ``{"name": [[u, v], ...]}``
(polygons and paths); the output keeps the same shape in metres.

Only the standard library is used.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

FULL_FRAME_DIAGONAL_MM = math.hypot(36.0, 24.0)

Point = tuple[float, float]
Matrix = list[list[float]]


class ScaleError(Exception):
    pass


# --------------------------------------------------------------------------- basics


def parse_aspect(text: str) -> float:
    """``16:9`` -> 1.777..., ``1.5`` -> 1.5 (width / height)."""
    if ":" in text:
        w, h = text.split(":", 1)
        return float(w) / float(h)
    return float(text)


def footprint(altitude_m: float, focal_35mm: float, aspect: float) -> dict[str, float]:
    """Ground width and height seen by a camera pointing straight down."""
    if altitude_m <= 0 or focal_35mm <= 0 or aspect <= 0:
        raise ScaleError("altitude, focal length and aspect must be positive")
    equivalent_width_mm = FULL_FRAME_DIAGONAL_MM * aspect / math.hypot(aspect, 1.0)
    width = altitude_m * equivalent_width_mm / focal_35mm
    return {
        "groundWidthM": round(width, 3),
        "groundHeightM": round(width / aspect, 3),
        "metresPerTenthOfWidth": round(width / 10, 3),
        "horizontalFovDeg": round(
            math.degrees(2 * math.atan(equivalent_width_mm / (2 * focal_35mm))), 2
        ),
    }


def image_to_ground(
    point: Point,
    *,
    origin: Point,
    ground_width_m: float,
    ground_height_m: float,
    up_bearing_deg: float,
) -> Point:
    """Straight-down image point -> ``(x, z)``.

    ``origin`` is where the south-west corner of the bounds is in the image;
    ``up_bearing_deg`` is the direction of the image's top edge in the
    blueprint frame, clockwise from +Z (0 = image top is north, 90 = east).
    """
    right_m = (point[0] - origin[0]) * ground_width_m
    up_m = (origin[1] - point[1]) * ground_height_m
    b = math.radians(up_bearing_deg)
    up = (math.sin(b), math.cos(b))
    right = (math.cos(b), -math.sin(b))
    return (right_m * right[0] + up_m * up[0], right_m * right[1] + up_m * up[1])


def yaw_from_image(up_bearing_deg: float, image_angle_deg: float) -> float:
    return round((up_bearing_deg + image_angle_deg) % 360.0, 2) % 360.0


# --------------------------------------------------------------------------- homography


def _solve(a: Matrix, b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting."""
    n = len(b)
    m = [[*row, rhs] for row, rhs in zip(a, b, strict=True)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            raise ScaleError("the reference points are degenerate (collinear or repeated)")
        m[col], m[pivot] = m[pivot], m[col]
        for row in range(col + 1, n):
            factor = m[row][col] / m[col][col]
            for k in range(col, n + 1):
                m[row][k] -= factor * m[col][k]
    x = [0.0] * n
    for row in range(n - 1, -1, -1):
        x[row] = (m[row][n] - sum(m[row][k] * x[k] for k in range(row + 1, n))) / m[row][row]
    return x


def _normaliser(points: Sequence[Point]) -> Matrix:
    """Similarity moving the centroid to 0 and the mean distance to sqrt(2) (Hartley)."""
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    mean = sum(math.hypot(p[0] - cx, p[1] - cy) for p in points) / len(points)
    if mean < 1e-12:
        raise ScaleError("the reference points are degenerate (all in one place)")
    s = math.sqrt(2) / mean
    return [[s, 0.0, -s * cx], [0.0, s, -s * cy], [0.0, 0.0, 1.0]]


def _apply(h: Matrix, p: Point) -> Point:
    w = h[2][0] * p[0] + h[2][1] * p[1] + h[2][2]
    if abs(w) < 1e-12:
        raise ScaleError("the point maps to the horizon (it is not on the ground plane)")
    return (
        (h[0][0] * p[0] + h[0][1] * p[1] + h[0][2]) / w,
        (h[1][0] * p[0] + h[1][1] * p[1] + h[1][2]) / w,
    )


def _matmul(a: Matrix, b: Matrix) -> Matrix:
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _inverse_similarity(t: Matrix) -> Matrix:
    s = t[0][0]
    return [[1 / s, 0.0, -t[0][2] / s], [0.0, 1 / s, -t[1][2] / s], [0.0, 0.0, 1.0]]


def _check_spread(points: Sequence[Point]) -> None:
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            for k in range(j + 1, len(points)):
                (ax, ay), (bx, by), (cx, cy) = points[i], points[j], points[k]
                if abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax)) > 1e-9:
                    return
    raise ScaleError("the reference points are collinear")


def fit_homography(image: Sequence[Point], ground: Sequence[Point]) -> Matrix:
    """Least-squares plane-to-plane homography (normalised DLT, h33 = 1)."""
    if len(image) != len(ground) or len(image) < 4:
        raise ScaleError("a ground homography needs at least four point pairs")
    _check_spread(image)
    _check_spread(ground)
    ti, tg = _normaliser(image), _normaliser(ground)
    rows: Matrix = []
    rhs: list[float] = []
    for p, q in zip(image, ground, strict=True):
        u, v = _apply(ti, p)
        x, z = _apply(tg, q)
        rows.append([u, v, 1.0, 0.0, 0.0, 0.0, -u * x, -v * x])
        rhs.append(x)
        rows.append([0.0, 0.0, 0.0, u, v, 1.0, -u * z, -v * z])
        rhs.append(z)
    normal = [[sum(r[i] * r[j] for r in rows) for j in range(8)] for i in range(8)]
    target = [sum(r[i] * b for r, b in zip(rows, rhs, strict=True)) for i in range(8)]
    h = _solve(normal, target)
    hn = [[h[0], h[1], h[2]], [h[3], h[4], h[5]], [h[6], h[7], 1.0]]
    result = _matmul(_inverse_similarity(tg), _matmul(hn, ti))
    scale = result[2][2]
    return [[value / scale for value in row] for row in result]


def map_ground(h: Matrix, point: Point) -> Point:
    return _apply(h, point)


# --------------------------------------------------------------------------- estimates


def confidence_for(relative_error: float) -> float:
    """Suggested size confidence for a relative 1-sigma error (see reference/sizes.md)."""
    for limit, confidence in ((0.05, 0.9), (0.10, 0.8), (0.20, 0.65), (0.35, 0.5)):
        if relative_error <= limit:
            return confidence
    return 0.3


def ratio_estimate(
    ref_size: float,
    ref_extent: float,
    extent: float,
    *,
    ref_min: float | None = None,
    ref_max: float | None = None,
    measure_error: float = 0.1,
) -> dict[str, float]:
    """Size of an object from a reference object seen at the same distance and angle."""
    if ref_size <= 0 or ref_extent <= 0 or extent <= 0:
        raise ScaleError("sizes and extents must be positive")
    low = ref_min if ref_min is not None else ref_size
    high = ref_max if ref_max is not None else ref_size
    if not low <= ref_size <= high:
        raise ScaleError("--ref-size must lie between --ref-min and --ref-max")
    value = ref_size * extent / ref_extent
    relative = math.hypot((high - low) / (2 * ref_size), measure_error * math.sqrt(2))
    return {
        "valueM": round(value, 3),
        "sigmaM": round(value * relative, 3),
        "relativeError": round(relative, 3),
        "suggestedConfidence": confidence_for(relative),
    }


def combine(estimates: Sequence[tuple[float, float]]) -> dict[str, Any]:
    """Inverse-variance mean of independent estimates ``(value, sigma)``."""
    if not estimates:
        raise ScaleError("nothing to combine")
    if any(sigma <= 0 for _, sigma in estimates):
        raise ScaleError("every sigma must be positive")
    weights = [1 / sigma**2 for _, sigma in estimates]
    mean = sum(w * v for w, (v, _) in zip(weights, estimates, strict=True)) / sum(weights)
    sigma = 1 / math.sqrt(sum(weights))
    outliers = [
        i for i, (value, s) in enumerate(estimates) if abs(value - mean) > 2.5 * max(s, sigma)
    ]
    if outliers:
        # Disagreeing estimates: trust the spread, not the formal error.
        values = [value for value, _ in estimates]
        sigma = max(sigma, (max(values) - min(values)) / 2)
    relative = sigma / abs(mean) if mean else math.inf
    return {
        "valueM": round(mean, 3),
        "sigmaM": round(sigma, 3),
        "relativeError": round(relative, 3),
        "suggestedConfidence": confidence_for(relative),
        "consistent": not outliers,
        "outlierIndexes": outliers,
    }


def along_path(path: Sequence[Point], point: Point, *, closed: bool = False) -> dict[str, float]:
    """Where ``point`` projects onto a path: fraction of the total length (0..1)."""
    pts = [*path, path[0]] if closed else list(path)
    if len(pts) < 2:
        raise ScaleError("a path needs at least two points")
    lengths = [math.dist(a, b) for a, b in itertools.pairwise(pts)]
    total = sum(lengths)
    if total <= 0:
        raise ScaleError("the path has no length")
    best = (math.inf, 0.0)
    travelled = 0.0
    for (a, b), length in zip(itertools.pairwise(pts), lengths, strict=True):
        if length > 0:
            t = ((point[0] - a[0]) * (b[0] - a[0]) + (point[1] - a[1]) * (b[1] - a[1])) / length**2
            t = min(1.0, max(0.0, t))
            foot = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
            best = min(best, (math.dist(point, foot), travelled + t * length))
        travelled += length
    return {
        "fraction": round(best[1] / total, 4),
        "distanceAlongM": round(best[1], 2),
        "offsetM": round(best[0], 2),
        "pathLengthM": round(total, 2),
    }


# --------------------------------------------------------------------------- CLI


def _points(args: argparse.Namespace) -> dict[str, Any]:
    if args.json:
        data: dict[str, Any] = json.loads(Path(args.json).read_text(encoding="utf-8"))
        return data
    if not args.point:
        raise ScaleError("give --point NAME U V (repeatable) or --json FILE")
    return {name: [float(u), float(v)] for name, u, v in args.point}


def _convert(shape: Any, convert: Callable[[Point], Point]) -> Any:
    if (
        isinstance(shape, list)
        and len(shape) == 2
        and all(isinstance(c, int | float) for c in shape)
    ):
        x, z = convert((float(shape[0]), float(shape[1])))
        return [round(x, 2), round(z, 2)]
    if isinstance(shape, list):
        return [_convert(item, convert) for item in shape]
    raise ScaleError(f"expected [u, v] or a list of them, got {shape!r}")


def cmd_footprint(args: argparse.Namespace) -> dict[str, Any]:
    return footprint(args.altitude, args.focal35, parse_aspect(args.aspect))


def cmd_map(args: argparse.Namespace) -> dict[str, Any]:
    height = args.ground_height or args.ground_width / parse_aspect(args.aspect)
    if (args.origin is None) == (args.anchor is None):
        raise ScaleError("give exactly one of --origin U V and --anchor U V X Z")
    if args.anchor is not None:
        origin, offset = (args.anchor[0], args.anchor[1]), (args.anchor[2], args.anchor[3])
    else:
        origin, offset = (args.origin[0], args.origin[1]), (0.0, 0.0)

    def convert(p: Point) -> Point:
        x, z = image_to_ground(
            p,
            origin=origin,
            ground_width_m=args.ground_width,
            ground_height_m=height,
            up_bearing_deg=args.up_bearing,
        )
        return (x + offset[0], z + offset[1])

    return {name: _convert(shape, convert) for name, shape in _points(args).items()}


def cmd_ground(args: argparse.Namespace) -> dict[str, Any]:
    pairs = args.pair or []
    image = [(p[0], p[1]) for p in pairs]
    ground = [(p[2], p[3]) for p in pairs]
    h = fit_homography(image, ground)
    residuals = [math.dist(map_ground(h, p), q) for p, q in zip(image, ground, strict=True)]
    points = {
        name: _convert(shape, lambda p: map_ground(h, p)) for name, shape in _points(args).items()
    }
    return {
        "points": points,
        "referenceRmsM": round(math.sqrt(sum(r * r for r in residuals) / len(residuals)), 3),
        "referenceMaxM": round(max(residuals), 3),
        "note": "valid only for points on the ground plane (bases, corners at ground level)",
    }


def cmd_yaw(args: argparse.Namespace) -> dict[str, Any]:
    return {"yawDeg": yaw_from_image(args.up_bearing, args.image_angle)}


def cmd_ratio(args: argparse.Namespace) -> dict[str, Any]:
    return ratio_estimate(
        args.ref_size,
        args.ref_extent,
        args.extent,
        ref_min=args.ref_min,
        ref_max=args.ref_max,
        measure_error=args.measure_error,
    )


def cmd_combine(args: argparse.Namespace) -> dict[str, Any]:
    estimates = []
    for item in args.estimates:
        value, _, sigma = item.partition(":")
        if not sigma:
            raise ScaleError(f"'{item}' is not VALUE:SIGMA")
        estimates.append((float(value), float(sigma)))
    return combine(estimates)


def cmd_along(args: argparse.Namespace) -> dict[str, Any]:
    path = []
    for item in args.path.split():
        x, _, z = item.partition(",")
        path.append((float(x), float(z)))
    if not args.point:
        raise ScaleError("give at least one --point X Z")
    return {"points": [along_path(path, (p[0], p[1]), closed=args.closed) for p in args.point]}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scale.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    fp = sub.add_parser("footprint")
    fp.add_argument("--altitude", type=float, required=True, help="metres above the ground")
    fp.add_argument("--focal35", type=float, required=True, help="35 mm equivalent focal length")
    fp.add_argument("--aspect", default="16:9")
    fp.set_defaults(func=cmd_footprint)

    mp = sub.add_parser("map")
    mp.add_argument("--ground-width", type=float, required=True)
    mp.add_argument("--ground-height", type=float)
    mp.add_argument("--aspect", default="16:9")
    mp.add_argument(
        "--origin", type=float, nargs=2, metavar=("U", "V"), help="image position of x=0, z=0"
    )
    mp.add_argument(
        "--anchor",
        type=float,
        nargs=4,
        metavar=("U", "V", "X", "Z"),
        help="image position of a known ground point",
    )
    mp.add_argument("--up-bearing", type=float, default=0.0)
    mp.add_argument("--point", nargs=3, action="append", metavar=("NAME", "U", "V"))
    mp.add_argument("--json")
    mp.set_defaults(func=cmd_map)

    gr = sub.add_parser("ground")
    gr.add_argument("--pair", type=float, nargs=4, action="append", metavar=("U", "V", "X", "Z"))
    gr.add_argument("--point", nargs=3, action="append", metavar=("NAME", "U", "V"))
    gr.add_argument("--json")
    gr.set_defaults(func=cmd_ground)

    yw = sub.add_parser("yaw")
    yw.add_argument("--up-bearing", type=float, default=0.0)
    yw.add_argument("--image-angle", type=float, required=True)
    yw.set_defaults(func=cmd_yaw)

    rt = sub.add_parser("ratio")
    rt.add_argument("--ref-size", type=float, required=True)
    rt.add_argument("--ref-min", type=float)
    rt.add_argument("--ref-max", type=float)
    rt.add_argument("--ref-extent", type=float, required=True)
    rt.add_argument("--extent", type=float, required=True)
    rt.add_argument("--measure-error", type=float, default=0.1, help="relative, per extent")
    rt.set_defaults(func=cmd_ratio)

    cb = sub.add_parser("combine")
    cb.add_argument("estimates", nargs="+", metavar="VALUE:SIGMA")
    cb.set_defaults(func=cmd_combine)

    al = sub.add_parser("along")
    al.add_argument("--path", required=True, help='"x,z x,z ..." in metres')
    al.add_argument("--closed", action="store_true")
    al.add_argument("--point", type=float, nargs=2, action="append", metavar=("X", "Z"))
    al.set_defaults(func=cmd_along)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    func: Callable[[argparse.Namespace], dict[str, Any]] = args.func
    try:
        print(json.dumps(func(args), indent=2))
    except (ScaleError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
