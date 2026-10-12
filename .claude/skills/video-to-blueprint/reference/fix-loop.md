# Validate → fix: what each finding usually means

Run `review_blueprint.py` after every batch of edits. For each finding, ask
first: **is the data wrong, is the provenance dishonest, or is this reality?**
Only the first two are fixed by changing data. Reality stays, explained in a
note.

Never fix a finding by: deleting an entity you saw, raising `confidence`,
citing a frame you did not check, removing `provenance`, setting
`source.type` to `manual`, claiming a calibration you did not do, or editing
`size_rules.json` to fit one blueprint.

## Contract errors (the document is unusable until they are gone)

| Code | Usual cause with footage | Fix |
| --- | --- | --- |
| `SCHEMA_MISSING` | a required field left out (`widthM`, `importance`, `transform`) | add it, measured or `unknown` where the vocabulary allows |
| `SCHEMA_EXTRA_FORBIDDEN` | a field in the wrong place or snake_case (`height_m`) | use the camelCase field from the docs; free data goes into `extensions` under `x-...` |
| `SCHEMA_ENUM`, `SCHEMA_LITERAL_ERROR` | a word outside the vocabulary (`"wooden"` as fenceType) | pick the closest listed value or `unknown` |
| `SCHEMA_STRING_PATTERN_MISMATCH` | an ID with dots, spaces or capitals | `b-house-03` style |
| `SCHEMA_LESS_THAN_EQUAL`, `SCHEMA_GREATER_THAN...` | yaw 360, confidence 1.2, negative size | correct the value (yaw `0 <= yaw < 360`) |
| `DUPLICATE_ID` | copy-paste | give the copy its own ID |
| `POLYGON_SELF_INTERSECTING` | points not in order around the outline | reorder them (walk around the edge) |
| `POLYGON_CLOSING_POINT_REPEATED`, `POLYLINE_CLOSING_POINT_REPEATED` | first point repeated at the end | drop the last point; fences use `closed: true` |
| `POLYGON_DEGENERATE`, `*_DUPLICATE_POINT` | points too close, or a zero-area outline | re-measure the corners |
| `ENTITY_OUTSIDE_BOUNDS` | bounds too small, wrong anchor, or a sign error (north and south swapped) | check the anchor and `--up-bearing` first; widen bounds only if the area really extends |
| `ROAD_CURVE_DUPLICATE_POINT`, `ROAD_SEGMENT_DEGENERATE` | a control point on a node, a loop without control points | remove the duplicate; loops need two control points |
| `MISSING_SECTION_INVALID`, `MISSING_SECTION_OVERLAP` | gap fractions reversed or overlapping | recompute with `scale.py along`, `start < end`, merge overlaps |
| `WIRE_DUPLICATE_POLE` | the same pole twice in a row | fix `poleIds` |
| `REFERENCE_NOT_FOUND` | typo in an ID; a frame that was never extracted | fix the ID; extract the frame (`--method manual --at T`), `sync-source --write`, look at it |
| `REFERENCE_WRONG_TYPE` | e.g. `parentId` pointing at a plot where a building is expected | point at the right kind of entity |
| `REFERENCE_USES_PREVIOUS_ID` | an entity was renamed | use the current ID |
| `PARENT_CYCLE` | two props parented to each other | parent to the plot or building |
| `METADATA_TIME_ORDER`, `RANGE_INVERTED` | `updatedAt` before `createdAt`, `min > max` | correct the order |
| `EXTERNAL_FILE_SIZE_MISMATCH`, `_CHECKSUM_MISMATCH` | a media file or frame index changed after extraction | re-run the extraction with `--force`, then `sync-source --write`; never edit checksums by hand |
| `EXTERNAL_PATH_ESCAPES_PACKAGE` | a file outside the package or a symlink | let `frames.py` copy footage into `media/` |

## Contract warnings

| Code | Meaning for footage | Fix |
| --- | --- | --- |
| `ENTITY_PARTIALLY_OUTSIDE_BOUNDS` | a road or zone crosses the edge | fine for roads leaving the area (end them on a `boundary` node at the edge); otherwise clip the polygon |
| `ROAD_NODE_DEGREE_MISMATCH`, `ROAD_NODE_ISOLATED` | node type does not match its segments | `junction` needs 3+, `dead_end`/`boundary` exactly 1; remove unused nodes |
| `BUILDING_OVERLAP` | footprints overlap | usually a scale or position error: re-measure; attached outbuildings are part of the building |
| `BUILDING_FOOTPRINT_MISMATCH` | `footprint` and `transform`/`dimensions` disagree | derive both from the same corners |
| `BUILDING_HEIGHT_IMPLAUSIBLE` | `heightM < 2 m x floors` | recount floors or re-measure the height |
| `FENCE_FULLY_MISSING` | gaps cover the whole fence | then it is not there: remove it, or describe what remains |
| `WIRE_UNUSUAL_SUPPORT` | a wire hangs from a well or sign | check which points the wire really runs between |
| `LANDMARK_FAR_FROM_LINKED_ENTITY` | linked entity more than 50 m away | link the right entity or none |
| `SPAWN_CLEARANCE_BLOCKED` | a spawn inside a building | move it (design intent, ask the user) |
| `PROVENANCE_CONFIDENCE_MISSING` | observed/inferred without confidence | add it from the rubric |
| `PROVENANCE_WITHOUT_SOURCE` | measured data but no `source` | the package was not created with `location_package.py`; add `source` from `analysis/source.json` |
| `UNCALIBRATED_MEASUREMENTS` | `calibration.method` is `none` | calibrate if you can (`manual_scale` with cross-checked references, `gps` with telemetry) and record how; if you cannot, the warning is the truth: leave it and say so in the report |
| `EXTERNAL_FILE_MISSING` (warning) | footage or frames not present (shared package) | expected when the media are not shipped; otherwise re-extract |
| `HEIGHTMAP_ELEVATION_MISMATCH` | heightmap and `terrain.elevation` disagree | only with a real heightmap; fix the range |

## Review findings (`REVIEW_*`)

| Code | Fix |
| --- | --- |
| `REVIEW_NO_ENTITIES` | start mapping (roads first) |
| `REVIEW_PROVENANCE_MISSING` | add `provenance`: observed / inferred / manual |
| `REVIEW_OBSERVED_WITHOUT_EVIDENCE` | add the `frameIds` you saw it in; if you did not see it, it is `inferred` |
| `REVIEW_INFERRED_WITHOUT_REASON` | write the evidence into `notes` (and cite the frames it is in) |
| `REVIEW_CONFIDENCE_ABOVE_CALIBRATION` | lower to 0.8 or less, or calibrate and record it |
| `REVIEW_POSITION_ACCURACY_MISSING` (info) | add `positionAccuracyM` (1 sigma) from [sizes.md](sizes.md#confidence-rubric) |
| `REVIEW_POSITION_ACCURACY_OPTIMISTIC` | no entity is more precise than the map: at least `estimatedErrorM` (0.5 m uncalibrated) |
| `REVIEW_SIZE_IMPLAUSIBLE` | almost always a scale error: re-measure with two references; a factor of about 2 suggests a wrong reference or a half/whole confusion |
| `REVIEW_SIZE_UNUSUAL` (info) | double-check; keep it if the frames show it, with a note |
| `REVIEW_HEIGHT_FOR_FLOORS` | recount window rows; a tall roof counts, but not 10 m of it |
| `REVIEW_ARCHETYPE_UNKNOWN` | choose from `uv run envgen assets list --category <c>`, or remove `archetype` |
| `REVIEW_DUPLICATE_POSITION` | a copied entity that was not moved |
| `REVIEW_YAW_ALL_ZERO` (info) | set `yawDeg` to the direction each entrance faces |
| `REVIEW_SOURCE_NOT_FOOTAGE` | `source.type` must say `video` / `mixed` when entities are observed |
| `REVIEW_SOURCE_OUT_OF_DATE` | `location_package.py sync-source --package <dir> --write` |
| `REVIEW_EVIDENCE_COVERAGE` (info) | how many frames are cited; very low coverage means few entities cite evidence |

## Generation (`envgen generate`)

The generator validates the layout it builds. Errors stop it with exit code
5; warnings are listed in `out/<id>/generation-report.json` either way.

| Code | Severity | Usual cause | Fix |
| --- | --- | --- | --- |
| `LAYOUT_BUILDING_OVERLAP` | error | two buildings closer than the recipe's minimum spacing | re-measure both; attached outbuildings belong to one building |
| `LAYOUT_ROAD_OBSTRUCTED` | error for buildings, else warning | an object on the carriageway | road too wide, or the object misplaced |
| `LAYOUT_WATER_OBSTRUCTED` | error for buildings, else warning | something standing in a pond | check the water polygon and the object |
| `LAYOUT_SOLID_OVERLAP` | warning | a tree, pole or prop inside a building | a mapping error: move or remove it |
| `LAYOUT_OUT_OF_BOUNDS`, `LAYOUT_GEOMETRY_OUTSIDE_EXTENT` | error | generated geometry crosses the bounds | keep objects a few metres inside the edge |
| `LAYOUT_UNKNOWN_ARCHETYPE` | error | an archetype the palette does not contain | see `REVIEW_ARCHETYPE_UNKNOWN` |
| `LAYOUT_PLACEHOLDER_ASSETS` | warning | no registry archetype for a kind | expected for unusual objects; mention it |
| `LAYOUT_GROUND_CONTACT` | warning | an object far above or below the terrain | check `snapToTerrain` and `y` |
| `LAYOUT_ENTITY_BUDGET` | error / warning | more entities than the recipe allows | a recipe question, not a blueprint error: tell the user |

## When to stop

* No errors.
* Every warning fixed or explained (in a note, and in your report).
* `envgen generate` succeeds and the preview matches the overview frames.

If a finding survives two rounds, measure again from another frame. If the
footage cannot answer the question, ask the user instead of guessing.
