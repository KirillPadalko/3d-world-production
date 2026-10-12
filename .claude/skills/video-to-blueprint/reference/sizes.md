# Scale, sizes and confidence

How to turn pixels into metres without fooling yourself. Every number you
write into a blueprint should be traceable to one of the methods below, with
the frames and references named in `provenance.notes` or a
`source.observations` entry.

## Image coordinates

Measure in **normalised image coordinates**: `u` from the left edge (0) to
the right edge (1), `v` from the top (0) to the bottom (1). You see frames
downscaled, so pixel counts are unreliable; fractions are not.
`frames.py grid` draws a labelled 0.1 grid; read values to about 0.01 and use
`frames.py crop` (full resolution) for small objects. An extent is a
difference of coordinates along one image axis (a car spanning `u` 0.41-0.47
has a width extent of 0.06).

## Sources of scale, best first

| # | Source | Typical error | Use when |
| --- | --- | --- | --- |
| 1 | Survey or GPS reference points known in both the footage and the ground | < 0.5 m | the user provides them |
| 2 | Orthophoto from photogrammetry with known resolution | < 0.5 m | someone ran OpenDroneMap / RealityCapture |
| 3 | Telemetry footprint of a straight-down frame (`scale.py footprint`) | 5-10 % | DJI `.SRT` with altitude and focal length, camera at -90 deg |
| 4 | Reference objects of known size in the same frame (`scale.py ratio`) | 10-20 % per reference | almost always available |
| 5 | Ground homography of an oblique frame (`scale.py ground`) | 1-3 m | four or more ground points with known positions |
| 6 | Counting repeated units (fence panels, pole spans, standard plots) | 15-30 % | as a cross-check |
| 7 | Typical size of the object type itself | 30 %+ | last resort; never use it to "confirm" the same type |

Rules:

* Every key dimension (bounds, the overview frame's ground width, the main
  road width) needs **two independent estimates**, combined with
  `scale.py combine`. Independent means different reference objects or
  different methods, not the same car measured twice.
* If estimates disagree beyond their errors (`"consistent": false`), one of
  them is wrong: a reference at a different distance, a misidentified object,
  a crop mode of the camera. Find it; do not average it away.
* Note what you used: `"notes": "width from f-...-00042000: 3.1 car lengths (Lada 2107, 4.15 m) and 2 fence panels (2.5 m)"`.

### Straight-down frames (`scale.py footprint`, `scale.py map`)

Ground width of the frame = altitude x equivalent image width / 35 mm-equivalent
focal length. `frames.py extract` reads DJI telemetry and puts the result in
each frame's `scaleHint` in `analysis/frames-<extraction>.json`.

Caveats, each a real source of error:

* `rel_alt` is relative to the **take-off point**. If the mapped ground is
  10 m lower than the take-off spot, the camera is 10 m higher above it.
* "Straight down" means the gimbal at -90 deg; a 10 deg tilt changes the scale
  across the frame. Use `scaleHint` only for frames that look straight down
  (vertical walls invisible, rectangles look rectangular).
* Video modes may crop the sensor; check the footprint against one reference
  object before trusting it.
* Lens distortion grows towards the edges: measure near the centre.

Then `scale.py map --ground-width W --anchor U V X Z --up-bearing B --point NAME U V ...`
converts image points to `[x, z]`. `--anchor` ties one image point to a known
ground position (the first time: a point you define, e.g. the main junction
at `[60, 40]`); `--up-bearing` is the direction the top of the image faces
(0 = north, 90 = east). For polygons and paths pass `--json FILE` with
`{"plot-03": [[u, v], [u, v], ...]}`.

### Reference objects (`scale.py ratio`)

The target and the reference must be at the **same distance from the camera**
and measured **along the same direction** (both horizontal, or both vertical).
In an oblique frame, a car in the foreground does not scale a house in the
background.

```bash
python3 $S/scale.py ratio --ref-size 4.15 --ref-min 4.0 --ref-max 4.3 \
  --ref-extent 0.060 --extent 0.115          # -> 7.95 m +- 1.16, confidence 0.65
```

| Reference | Size (m) | Reliability | Notes |
| --- | --- | --- | --- |
| Adult person | height 1.6-1.85 | medium | standing, not too far away |
| Passenger car | length 4.0-4.7, width 1.65-1.85, height 1.4-1.6 | high from above | Lada 2105/2107 4.1-4.15, Lada Niva 3.7, sedans 4.4-4.8 |
| Pickup / SUV | length 4.6-5.4, width 1.8-1.95 | high | |
| Shipping container | 20 ft: 6.06 x 2.44 x 2.59; 40 ft: 12.19 long | very high | common on rural sites |
| Entrance door | 2.0-2.1 high, 0.8-0.9 wide | high on facades | |
| Residential window | 1.2-1.5 high, sill 0.8-0.9 above the floor | medium | |
| Storey | 2.7-3.2 floor to floor (housing), 3.5-6 (industrial) | medium | count window rows |
| Brick | 250 x 120 x 65 mm, about 13 courses per metre | high in close-ups | Russian standard brick |
| Profiled-sheet fence | sheet about 1.15 wide, 1.8-2.0 high | high | "профнастил" |
| Concrete fence panel | about 4 long, 2-2.5 high | medium | precast panels |
| Fence posts | every 2-3 m | medium | count spans |
| Utility pole (0.4-10 kV) | 7.5-9.5 above ground | medium | spans 30-50 m (0.4 kV), 50-100 m (10 kV) |
| Road lane | 3.0-3.75 | medium | marked roads |
| Rural single-lane road | 3-4.5 | low | between the verges |
| Wheel ruts of a dirt track | about 1.4-1.6 apart | medium | car track width |
| Parking space | 2.5 x 5 | high where marked | |
| Dacha plot "6 соток" | 600 m2, often 20 x 30 | medium | 8-15 соток in newer settlements |
| 200 l steel drum | 0.58 diameter, 0.88 high | high in close-ups | |
| Euro pallet | 1.2 x 0.8 | high in close-ups | |
| Sports fields | football 100-110 x 64-75, basketball 28 x 15, tennis 23.8 x 11 | very high | |
| Railway gauge | 1.52 (Russia), 1.435 (Europe) | very high | |

Trees, bushes and buildings are **not** references: their sizes vary too much.

### Oblique frames (`scale.py ground`)

A flat ground plane seen at an angle maps to the map by a homography. Give at
least four image points whose ground positions you already know (from a
straight-down frame, from known plot or road geometry, from reference points),
spread over the area and not on one line, then convert other **ground-level**
points (where a pole meets the ground, building corners at the base, road
edges):

```bash
python3 $S/scale.py ground \
  --pair 0.21 0.78 10 10  --pair 0.63 0.74 40 10 \
  --pair 0.70 0.52 40 40  --pair 0.30 0.50 10 40 \
  --pair 0.46 0.63 25 25 \
  --point pole-04 0.48 0.61
```

Four pairs always fit exactly; give **five or more** so that `referenceRmsM`
can tell you how well they agree: below 1 m is good; above 2 m, a pair is
wrong or the ground is not flat. Roofs, treetops and wires are
not on the ground plane; never map them this way.

### Heights

* Facades: count storeys (2.7-3.2 m each) plus the roof; compare with doors.
* Poles, trees and roofs next to each other: `scale.py ratio` with a known
  height at the same distance.
* Shadows (same frame, flat ground): height = known height x shadow length /
  shadow length of the known object.
* From straight above you cannot measure heights; say so (`confidence` lower,
  `notes: "height from typical storey count"`).

### Positions and orientation

* Building `transform.position` is the centre of the footprint at ground
  level; measure the footprint corners and take the centre, or give an exact
  `footprint` polygon.
* `yawDeg` is the direction the **entrance side** faces, clockwise from north:
  `scale.py yaw --up-bearing B --image-angle A` with `A` measured clockwise
  from the top of the image.
* Fence gaps: `scale.py along --path "x,z x,z ..." --point X Z` gives the
  fraction along the fence for `missingSections`.
* Round sensibly: positions to 0.5 m, sizes to 0.1 m (small objects) or 0.5 m
  (buildings). `7.4637` claims a precision you do not have.

## Confidence rubric

`confidence` is your trust in the entity **as described**: that it exists,
that its type is right, and that its position and size are within the stated
error. Take the lowest of the three.

| Confidence | Existence and type | Size (relative 1-sigma) | Position |
| --- | --- | --- | --- |
| 0.9 | clearly visible in several frames | within 5 % (calibrated only) | within `estimatedErrorM` |
| 0.8 | clearly visible | within 10 % | 1-2 m |
| 0.65 | visible, partly occluded | within 20 % | 2-4 m |
| 0.5 | glimpsed or mostly occluded | within 35 % | 4-8 m |
| 0.3 | barely visible, or inferred | rough guess | > 8 m |

* Without calibration (`calibration.method: "none"`) the maximum is **0.8**.
* `scale.py ratio` and `combine` suggest a size confidence from the relative
  error; it is an upper bound for the entity.
* Below 0.3: leave the entity out unless it matters; recipes can drop
  low-confidence entities (`filters.minConfidence`).

`positionAccuracyM` (1 sigma, horizontal): 0.5-1.5 m on a calibrated
straight-down frame, 1-3 m through a good homography, 3-8 m when placed by eye
relative to neighbours. Never smaller than `calibration.estimatedErrorM`.

## Plausibility ranges

`review_blueprint.py` compares sizes with
[`size_rules.json`](../size_rules.json): outside the *typical* range is
reported as info (double-check), outside the *plausible* range as a warning
(almost always a scale or unit error). The ranges describe rural and suburban
Eastern Europe; if the footage shows something genuinely unusual, keep the
measurement and explain it in `provenance.notes`. Edit `size_rules.json`
only to widen a range for a region, never to make one blueprint pass.
