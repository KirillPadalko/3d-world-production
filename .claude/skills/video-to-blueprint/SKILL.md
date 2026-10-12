---
name: video-to-blueprint
description: Turn a video of a real place (drone or ground footage, a downloaded clip, a phone video) into a LocationBlueprint v1.0 location package for the environment generator ("видео → описание локации"). Extracts frames with ffmpeg, maps the place at a measured scale, records honest provenance with frame citations, and runs a validate → fix loop until the blueprint is clean and generates. Use when the user gives footage or frames of a location and wants a location description, blueprint or game map from it, or wants to update such a blueprint with new footage.
---

# Video → LocationBlueprint

You turn footage of a real place into a **location package**: a folder with
`location.blueprint.json` (contract: `docs/LOCATION_BLUEPRINT.md`, schema:
`schemas/location-blueprint.schema.json`), the footage, the extracted frames
and your analysis notes. The blueprint is then generated into a scene manifest
(`envgen generate`) and imported into Unity (`integrations/unity`).

A video gives you approximate geometry. Your job is not to look precise; it is
to be **right about what you know and honest about what you do not**.

## Ground rules

1. **Never invent evidence.** Cite only frames that exist in `source.frames`
   and that you have actually looked at. No made-up GPS, dates, calibration,
   observations or measurements. If something is unknown, write `unknown`,
   leave the optional field out, or lower the confidence.
2. **Provenance on every physical entity**: `observed` (seen in the frames,
   cite them), `inferred` (deduced from indirect evidence, say which in
   `notes`), `manual` (told by the user or a design decision). Details:
   [reference/provenance.md](reference/provenance.md).
3. **Uncertainty is data.** Give `confidence` and `positionAccuracyM` from the
   rubric in [reference/sizes.md](reference/sizes.md#confidence-rubric).
   Without calibration, confidence stays at or below 0.8.
4. **One frame of reference**: metres, `+X` east, `+Z` north, origin at the
   south-west corner, yaw clockwise from north, `[x, z]` horizontal points.
   Convert image measurements only with `scripts/scale.py`; never eyeball
   coordinates and never flip axes silently.
5. **Stable IDs.** Readable, assigned once (`b-house-03`). When you update a
   blueprint, match entities to their existing IDs; never renumber.
6. **Never overwrite** an existing blueprint the user did not ask you to
   change. The scripts refuse to; do not work around them.
7. **Validation is not the goal, truth is.** Never silence a diagnostic by
   deleting evidence, raising confidence, citing frames you did not check or
   changing `source.type`. A warning that reflects reality stays, with a note.

## Tools

Run everything from the repository root. `$S` below stands for
`.claude/skills/video-to-blueprint/scripts`; write the full path in commands
(shell variables do not persist between commands).

| Command | Purpose |
| --- | --- |
| `python3 $S/frames.py probe VIDEO` | duration, resolution, fps, creation time, GPS tag, telemetry sidecar |
| `python3 $S/frames.py extract VIDEO --package DIR [--every S \| --method scene \| --method manual --at T ...] [--start S --end S]` | copy the video into `DIR/media/`, extract frames, labelled contact sheets, an index and `analysis/source.json` |
| `python3 $S/frames.py grid --package DIR --frame ID` | the frame with a labelled 0.1 grid, for reading normalised `u, v` |
| `python3 $S/frames.py crop --package DIR --frame ID --box U0 V0 U1 V1` | full-resolution detail from the video |
| `python3 $S/frames.py render out/<id>/preview.svg` | PNG of the generated preview, to compare with a frame |
| `python3 $S/scale.py footprint \| map \| ground \| ratio \| combine \| yaw \| along` | scale and image → ground conversions ([reference/sizes.md](reference/sizes.md)) |
| `uv run python $S/location_package.py init --package DIR ...` | create a valid, empty blueprint whose `source` lists the extracted material |
| `uv run python $S/location_package.py sync-source --package DIR [--write]` | add later extractions to the blueprint's `source` |
| `uv run python $S/review_blueprint.py DIR/location.blueprint.json` | contract validation plus the review checks of this skill |
| `uv run envgen generate -b DIR/location.blueprint.json -d out/<id> --preview` | generate the scene manifest and a top-down preview |

Prerequisites: `ffmpeg`/`ffprobe` on PATH and `uv sync` done. If ffmpeg is
missing, say so and how to install it; do not try to analyse a video without frames.

## Workflow

### 1. Set up

* Get the video path. Ask only what you cannot see: the place's name, and
  anything the user knows (where it is, which way is north, sizes they know).
* Location ID: lower-case, `-`/`_` (`dacha-ivanovka`). Package folder:
  `locations/<locationId>/` unless the user wants another place (footage and
  frames under `locations/` are git-ignored; the blueprint and notes are not).
* `frames.py probe` the video. Note duration, resolution, and whether there is
  a telemetry sidecar (DJI `.SRT`: altitude, focal length, GPS).

### 2. Extract frames

* Overview pass: aim for 60-150 frames. `--every` = duration / 100, at least
  1 s. Restrict to the part that shows the place (`--start`, `--end`).
* Edited clips with cuts: `--method scene` (one frame per shot plus fill-ins
  at least every `--max-gap` seconds).
* Later, for details or measurement: `--method manual --at 12.4 --at 31` and
  then `location_package.py sync-source --package DIR --write`.

Frames are named `<extractionId>-<milliseconds>`; that is the ID you cite.

### 3. Overview: understand the place before mapping it

* Read **every contact sheet** (`frames/<extraction>/sheets/sheet-*.jpg`; each
  tile shows its frame ID and time). Then open the 5-10 most informative
  frames at full size.
* Write `DIR/analysis/notes.md` as you go (template below): what each part of
  the video shows, the camera path, the best **overview frames** (high,
  looking down, covering much of the area), reference objects for scale,
  landmarks, what is hidden, open questions.
* Decide the extent of the location: the area the footage actually covers
  well. Do not extend it into places nobody filmed.

### 4. Frame of reference and scale

Follow [reference/sizes.md](reference/sizes.md); in short:

1. **North.** True north if known (telemetry heading, the user, a map,
   shadows with known time). Otherwise pick a local north (e.g. along the main
   road), say so in `source.calibration.notes`, and leave `geoReference` out.
2. **Scale** from the best available source, checked by a second independent
   one: telemetry footprint of a straight-down frame (`scale.py footprint`),
   known reference objects (`scale.py ratio`), a ground homography for oblique
   frames (`scale.py ground`), counted repeated units. Combine with
   `scale.py combine`; if estimates disagree, find out why instead of averaging.
3. **Bounds** (`widthM` east-west, `depthM` north-south): the mapped area plus
   about 5 m, rounded to 5 m. Every entity must lie inside.
4. Record it: `source.calibration` (`method`, `scaleConfidence`,
   `estimatedErrorM`, `notes`), and the key measurements as
   `source.observations` (`obs-scale-car-01`, with `frameIds`).

### 5. Create the package

```bash
uv run python $S/location_package.py init --package locations/<id> \
  --location-id <id> --name "<name>" --width <W> --depth <D> \
  --biome temperate --season summer --region "<region>" \
  [--calibration manual_scale|reference_points|gps --calibration-notes "..."] \
  [--geo LAT LON --heading DEG --geo-accuracy M]
```

Add `analysis/notes.md` to `source.analysisReports` as
`{"id": "rep-notes", "file": {"path": "analysis/notes.md", "mediaType": "text/markdown"}, "tool": {"name": "claude"}}`
(no checksum: the notes keep changing).

### 6. Map the place

Work from the overview frames. For each entity: measure its position and size
in a frame (grid → normalised `u, v` → `scale.py map` for straight-down frames,
`scale.py ground` for oblique ones), cross-check in a second frame, then write
it with provenance and 1-3 cited frames. What goes where, ID conventions and
vocabulary: [reference/mapping.md](reference/mapping.md).

Order: **roads → plots → buildings → fences → vegetation zones and notable
trees → infrastructure and wires → props → water and terrain → landmarks →
atmosphere**. Gameplay annotations only when the user asks: they are design
intent (`manual`), never observations.

Edit the JSON directly (or with a short Python script for many points). After
each collection, run the review (step 7); fixing ten problems early is cheaper
than fifty at the end.

### 7. Validate → fix loop

```bash
uv run python $S/review_blueprint.py locations/<id>/location.blueprint.json
```

Exit 0: no errors (warnings may remain). Exit 1: errors. The report groups
diagnostics by code, with path, entity IDs and a fix hint; `--json` gives the
same data for scripting.

Each round:

1. Fix **all errors** first (the document is unusable until then), then
   warnings, then read the info lines.
2. For every finding decide which of these it is, using
   [reference/fix-loop.md](reference/fix-loop.md):
   * **a mistake** (typo in an ID, wrong scale, point order, copy-paste) →
     correct the data;
   * **missing honesty** (no provenance, no frames, confidence too high) →
     add or lower it truthfully, look at the frames again if needed;
   * **reality** (the house really is 16 m wide; it is not calibrated) → keep
     the data and explain it in `provenance.notes` / `calibration.notes`.
3. Re-run the review. Repeat until there are no errors and every remaining
   warning is explained. If the same finding survives two rounds, re-measure
   from a different frame instead of nudging numbers. If a fix needs
   information the footage does not contain, ask the user.

Then generate:

```bash
uv run envgen generate -b locations/<id>/location.blueprint.json -d out/<id> --preview
uv run envgen verify out/<id>/scene-manifest.json
```

Exit 5 means the generated layout failed validation (overlaps, blocked
spawns...): read `out/<id>/generation-report.json`, fix the blueprint, run the
loop again. Render the preview (`frames.py render out/<id>/preview.svg`) and
compare it with an overview frame: road shape, plot sizes, building positions,
doors (the tick on each building marks its front). Mismatches are mapping
errors; fix them and loop.

### 8. Report

Tell the user, briefly: what was mapped (counts per collection), how the scale
was established and its estimated error, which areas are inferred or low
confidence, the warnings left and why, what they should check by eye, and the
next steps (a recipe, `envgen generate`, Unity import). Mention the files:
blueprint, notes, preview.

## Updating a blueprint with new footage

Extract the new video into the same package (it gets its own media ID), run
`sync-source --write`, then go through the entities: add the new frames to
existing entities' `frameIds`, correct positions where the new footage is
better (and update `positionAccuracyM`), add new entities with new IDs. Never
renumber or recreate existing entities; renames go through `previousIds`.

## Notes template (`analysis/notes.md`)

```markdown
# <name> - analysis notes

## Footage
- <mediaId>: <duration>, <resolution>; <what it shows, camera path, altitude>
- Segments: 0-35 s approach from the south over the road; 35-80 s orbit ...

## Frames used
- Overview: <frameId> (high, near straight down, covers plots 1-6)
- Detail: <frameId> (house facades, south side)

## Frame of reference
- North: <true / local, how determined>
- Origin and bounds: <...>
- Scale: <method, references, numbers, combined result and error>

## Findings and open questions
- <what is hidden, what is inferred and why, what to ask the user>
```

## Limits to state honestly

* Positions from video are typically good to 1-3 m with a calibrated
  overview frame, 3-8 m without; heights to 10-25 %.
* No heightmap from video: give `terrain.elevation` (min/max) only when you
  have real numbers (telemetry, user, map) and describe slopes as
  `slopeZones`. The built-in generator derives relief from the elevation span.
* Areas not seen are not mapped, or mapped as `inferred` with a note.
* For survey-grade results, build an orthophoto with photogrammetry (e.g.
  OpenDroneMap) and map on it with `scale.py map` at its known resolution.
