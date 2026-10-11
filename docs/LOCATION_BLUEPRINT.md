# LocationBlueprint contract v1.0

A **LocationBlueprint** is the engine-independent description of what is known
about one real-world place: its terrain, road network, plots, buildings,
vegetation, fences, infrastructure, props, landmarks, gameplay annotations and
atmosphere, plus where each piece of information came from.

It describes **what is there**, not how it must look in a game. Styling,
asset choices and generation rules belong to a separate **LocationRecipe**;
author edits belong to separate **LocationOverrides** (see
[Recipe and overrides](#recipe-and-overrides)).

This document is normative. The machine-readable contract is
[`schemas/location-blueprint.schema.json`](../schemas/location-blueprint.schema.json)
(JSON Schema 2020-12, generated from
`src/environment_generator/models/blueprint/`). Where this document describes
rules that a JSON Schema cannot express (references, geometry, files), the
reference implementation is `src/environment_generator/blueprint/`.

Contents:

1. [Design rules](#design-rules)
2. [Location package and files](#location-package-and-files)
3. [JSON encoding and canonical form](#json-encoding-and-canonical-form)
4. [Versioning and migration](#versioning-and-migration)
5. [Spatial conventions](#spatial-conventions)
6. [Identifiers](#identifiers)
7. [Provenance and confidence](#provenance-and-confidence)
8. [Document reference](#document-reference) (every section and field)
9. [Validation and diagnostics](#validation-and-diagnostics)
10. [Recipe and overrides](#recipe-and-overrides)
11. [Extensions](#extensions)
12. [The dacha fixture](#the-dacha-fixture)
13. [Implementing a consumer](#implementing-a-consumer)
14. [Python API and CLI](#python-api-and-cli)

---

## Design rules

* **Engine independent.** A blueprint never contains Unity instance IDs,
  prefab paths, serialized object references, Blender object pointers, Meshy
  task IDs as identifiers, runtime components, absolute paths or credentials.
  Assets are referred to by *semantic archetype names* (`wooden_house_small`);
  an asset registry maps them to concrete assets later.
* **Estimated, not exact.** Positions and sizes are estimates. Their quality
  is expressed through [provenance](#provenance-and-confidence), never hidden.
* **Measured data is never mixed with authored data silently.** Every entity
  can say whether it was observed, inferred, authored by hand or added by a
  tool.
* **No large arrays in JSON.** Heightmaps and masks are external binary files
  referenced by relative path, size and checksum.
* **Strict.** Unknown fields are errors (except inside `extensions`). Values
  are never silently repaired, axes are never silently reinterpreted.
* **Stable.** IDs are stable across loads and saves; serialization is
  deterministic.

---

## Location package and files

A blueprint lives in a **location package**: a folder containing the
blueprint file (conventionally `location.blueprint.json`) and every file it
references.

```text
dacha-forest-edge/
  location.blueprint.json
  terrain/heightmap.r16
  terrain/wetness.u8
  media/...              (optional: footage, frames, reports)
```

`FileReference` fields:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `path` | string | yes | POSIX path relative to the package root. |
| `mediaType` | string | no | e.g. `application/octet-stream`, `video/mp4`. |
| `sha256` | string | no | Lower-case hex SHA-256 of the file; verified when present. |
| `sizeBytes` | integer | no | Exact file size; verified when present. |

Path rules (enforced by the schema pattern and again after resolving
symlinks): no leading `/`, no drive letter (`C:`), no backslash, no URL scheme
(`://`), no empty, `.` or `..` segment, no control characters. A path that
resolves (through symlinks) outside the package is rejected
(`EXTERNAL_PATH_ESCAPES_PACKAGE`). The package can be moved or copied anywhere.

**Required vs optional files.** Files used for generation (`terrain.heightmap`,
`terrain.masks`) are required: a missing or mismatching file is an error.
Provenance material (`source.media`, `source.frames[].file`,
`source.analysisReports`) is optional: a missing file is a warning, because a
blueprint may be shared without its footage.

---

## JSON encoding and canonical form

* UTF-8 JSON object, field names in **camelCase**. snake_case names are not
  accepted (a document using `schema_version` is reported as
  `BLUEPRINT_LEGACY_FORMAT`).
* Numbers are JSON numbers; `NaN`/`Infinity` are invalid.
* An **absent field means its default** (see the tables below). `null` is only
  valid where a field is documented as optional; it means "not known".
* Timestamps are ISO 8601 with a time zone (`2026-10-01T09:00:00Z`).

**Canonical form** (what `envgen blueprint format` and `dumps_blueprint`
write, byte for byte):

1. fields in the order of the tables below (schema order);
2. fields equal to their default are omitted (`compact`);
3. keys of free-form maps (`extensions` at any depth, `externalIds`,
   `generation.subsystemSeeds`) sorted; array order is always preserved;
4. floats written exactly (shortest round-trip representation, no rounding);
5. 2-space indentation, non-ASCII characters kept as UTF-8, one trailing
   newline.

Loading and saving never changes data: `load -> save` of a canonical file is
byte-identical, and loading never generates IDs or fills values into the file.
`save_blueprint` refuses to replace an existing file unless asked explicitly.

---

## Versioning and migration

`schemaVersion` is a string `"MAJOR.MINOR"`. This release reads and writes
**`"1.0"`**.

| Declared version | Status | Result |
|---|---|---|
| equal to the supported version | current | loaded |
| same major, lower minor | readable | loaded (minor versions only add optional fields) |
| same major, higher minor | too new | rejected, `BLUEPRINT_VERSION_TOO_NEW` (newer optional fields would be lost) |
| higher major | unsupported | rejected, `BLUEPRINT_VERSION_UNSUPPORTED` |
| lower major with a registered migration chain | migratable | rejected until migrated, `BLUEPRINT_MIGRATION_REQUIRED` |
| lower major without migrations | unsupported | rejected, `BLUEPRINT_VERSION_UNSUPPORTED` |
| missing / not `"N.M"` / not a string | invalid | `BLUEPRINT_VERSION_MISSING` / `BLUEPRINT_VERSION_INVALID` |
| snake_case `schema_version` | invalid | `BLUEPRINT_LEGACY_FORMAT` (the unreleased 0.1 draft) |

Compatibility promise: within a major version, fields are only *added*, as
optional fields with defaults; enum values are only added in minor versions
together with a minor bump. Removing or renaming a field, or changing a
meaning, requires a new major version and a migration.

**Migrations** are pure functions on raw JSON (`Migration(source, target,
description, upgrade)`), registered in a `MigrationRegistry` and chained
(`0.9 -> 1.0 -> ...`). Rules:

* migration works on a deep copy; the input document is never modified;
* each step must set `schemaVersion` to its target, otherwise the migration
  fails (`MigrationError`);
* the migrated document is validated completely before it is written;
* validation never migrates implicitly;
* a file is only replaced with an explicit `--in-place`; a backup
  `<file>.v<old>.bak` is written first. `--output` writes a new file and
  refuses to overwrite the source or an existing file (unless `--force`).

v1.0 is the first public version, so the built-in registry is empty.

---

## Spatial conventions

| Property | Value |
|---|---|
| Unit | metre |
| `+X` | east |
| `+Y` | up (elevation) |
| `+Z` | north |
| Handedness | left-handed (the same as Unity) |
| Origin | south-west corner of the horizontal bounds; `x` in `[0, widthM]`, `z` in `[0, depthM]` |
| Yaw | degrees clockwise from north (`+Z`) around `+Y`, in `[0, 360)`; 90 = east |
| Object front | local `+Z`: an object with yaw 0 faces north |
| Horizontal geometry | `[x, z]` pairs (polygons, polylines, road nodes, curve control points) |
| Full positions | `[x, y, z]` with `y` the elevation in metres |
| Polygons | implicitly closed rings; the first point is **not** repeated; orientation is free; must be simple (no self-intersection) |

`coordinateSystem` repeats these values explicitly (`unit`, `upAxis`,
`eastAxis`, `northAxis`, `handedness`, `yawConvention`, `origin`). They are
constants: a document declaring any other value is rejected; nothing is ever
converted silently.

**Positions and terrain.** `transform.snapToTerrain` (default `true`) means
consumers place the object on the terrain surface; `y` is then only advisory.
With `false`, `y` is an absolute elevation (e.g. a lamp on a pole).

**Object axes.** For buildings `dimensions.widthM` runs along local `X` (side
to side), `depthM` along local `Z` (front to back), `heightM` along `Y`.
`transform.position` is the centre of the footprint at ground level.

**Geo reference (informative).** `coordinateSystem.geoReference` anchors the
origin approximately: `latitude`, `longitude`, `headingDeg` (compass bearing
of local `+Z`; 0 = local north is true north) and `accuracyM`. It never
changes the local frame.

### Conversions

| Target | Position | Yaw / rotation | Scale |
|---|---|---|---|
| Unity (left-handed, Y up, Z forward) | identity `(x, y, z)` | `eulerAngles.y = yaw` (`Quaternion.Euler(0, yaw, 0)`) | identity |
| Blender / Z-up right-handed ENU (`+X` east, `+Y` north, `+Z` up) | `(x, z, y)` | rotation about `+Z` by `-yaw` (counter-clockwise positive) | `(sx, sz, sy)` |
| Generator internal frame (same as Blender) | `(x, z, y)` | `-yaw` | `(sx, sz, sy)` |

The scene manifest produced by the generator uses the same location frame as
the blueprint (`rotationDeg` order Z, then X, then Y, extrinsic, as Unity's
`Quaternion.Euler`), so Unity integration needs no axis conversion.
`src/environment_generator/core/frames.py` is the only place that converts
to the generator frame.

### Road curves

A road segment's geometry is the point list
`[source node position, *curve.controlPoints, target node position]`.

* `polyline`: straight pieces between consecutive points.
* `catmull_rom`: **centripetal** Catmull-Rom spline (alpha = 0.5) through all
  points. End tangents use reflected phantom points
  `P[-1] = 2 P[0] - P[1]` and `P[n+1] = 2 P[n] - P[n-1]`. The piece between
  `P[i]` and `P[i+1]` uses `P[i-1], P[i], P[i+1], P[i+2]` with knots
  `t0 = 0`, `t(j+1) = t(j) + |P(j+1) - P(j)|^0.5`, evaluated with the
  Barry-Goldman pyramidal form for `t` in `[t1, t2]`:

  ```text
  A1 = (t1-t)/(t1-t0) P0 + (t-t0)/(t1-t0) P1
  A2 = (t2-t)/(t2-t1) P1 + (t-t1)/(t2-t1) P2
  A3 = (t3-t)/(t3-t2) P2 + (t-t2)/(t3-t2) P3
  B1 = (t2-t)/(t2-t0) A1 + (t-t0)/(t2-t0) A2
  B2 = (t3-t)/(t3-t1) A2 + (t-t1)/(t3-t1) A3
  C  = (t2-t)/(t2-t1) B1 + (t-t1)/(t2-t1) B2
  ```

  A two-point curve is a straight line. Consecutive points must differ.

The curve itself is exact; sampling density is a consumer choice. The
reference sampler (`core/curves.py`) splits each piece into
`ceil(chord / maxSegment)` equal parameter steps and keeps every control
point exactly; `tests/unit/test_frames_and_curves.py` pins reference values.

### Rasters (heightmaps and masks)

A raster covers exactly the horizontal bounds and is **corner-aligned**:
sample `(c, r)` lies at `x = c * widthM / (columns - 1)` and, for
`rowOrder: "south_to_north"`, `z = r * depthM / (rows - 1)` (row 0 on the south
edge). For `"north_to_south"` row 0 is the north edge. Samples are stored
row-major (all columns of row 0 west to east, then row 1, ...), without header
or padding, so the file size is exactly `columns * rows * bytesPerSample`.

| Encoding | Bytes | Used by | Value |
|---|---|---|---|
| `raw_u16_le` | 2 | heightmap | unsigned 16-bit little endian |
| `raw_f32_le` | 4 | heightmap | IEEE-754 float32 little endian |
| `raw_u8` | 1 | masks | `0..255`, read as `value / 255` |

Heightmap elevation: `elevationM = heightOffsetM + value * heightScaleM`.
Between samples, consumers interpolate bilinearly. `terrain.elevation`
(`minM`, `maxM`) must contain the heightmap range (0.5 m tolerance), or
`HEIGHTMAP_ELEVATION_MISMATCH` is reported.

---

## Identifiers

`id` (and `locationId`) match `^[a-z0-9][a-z0-9_-]{0,63}$`: lower-case ASCII
letters, digits, `-` and `_`; no dots, no spaces, at most 64 characters.

**One namespace per document.** IDs are unique across the whole document:
entities in every collection, road nodes and segments, terrain zones, water
bodies and masks, gameplay items and source items (media, frames,
extractions, reports, reference points, observations). A reference is
therefore unambiguous without naming its collection, and each reference
field states which kinds it accepts (validation reports
`REFERENCE_WRONG_TYPE` otherwise).

**Policy.**

* *Creation.* An ID is assigned once, when the entity is first recorded, and
  stored. Prefer readable, semantic IDs (`b-house-02`, `s-main-west`). Tools
  must never generate fresh random IDs on load or save; a tool that needs
  generated IDs derives them deterministically (e.g. from the source feature)
  and stores them.
* *Stability.* Editing any field other than `id` keeps the ID. Re-analysing a
  location should match entities to existing IDs instead of renumbering.
* *Renaming.* Change `id` and append the old value to `previousIds`.
  Overrides that still use the old ID resolve to the entity (with an
  `OVERRIDE_TARGET_RENAMED` note). References *inside* the document must use
  current IDs (`REFERENCE_USES_PREVIOUS_ID` is an error). A former ID may
  never be reused by another entity (`PREVIOUS_ID_CONFLICT`).
* *Deletion.* Remove the entity. Do not reuse its ID for something else;
  overrides that target it then fail visibly (`OVERRIDE_TARGET_MISSING`).
* *Migration.* Migrations keep IDs. If a migration must change an ID, it
  records the old one in `previousIds`.
* *Labels.* `label` is a human-readable name and never a key.

---

## Provenance and confidence

Every entity may carry `provenance`:

| Field | Type | Meaning |
|---|---|---|
| `category` | `observed` \| `inferred` \| `manual` \| `procedural` | how the data came to be (below) |
| `confidence` | 0..1, optional | 0 = guess, 1 = certain. Expected for `observed` and `inferred`. |
| `method` | vocabulary, optional | `photogrammetry`, `visual_estimate`, `survey`, `gps`, ... |
| `positionAccuracyM` | metres, optional | estimated horizontal position error (1 sigma) |
| `frameIds` | IDs | `source.frames` that show the entity |
| `observationIds` | IDs | `source.observations` supporting it |
| `notes` | text | free text |

| Category | Meaning |
|---|---|
| `observed` | measured or detected directly in source material (footage, survey) |
| `inferred` | estimated from indirect evidence (a fence line hidden by trees) |
| `manual` | authored or corrected by a person, without a measurement claim |
| `procedural` | added by a generator or tool, not observed |

An entity without provenance is a manual authoring decision without a
measurement claim. Rules:

* Do not fabricate source references: `frameIds`, `observationIds` and
  `source` describe real material only. A hand-authored blueprint uses
  `manual` provenance and `source.type: "manual"` or `"synthetic"`.
* `observed`/`inferred` data without `confidence` -> warning
  (`PROVENANCE_CONFIDENCE_MISSING`); without a `source` section -> warning
  (`PROVENANCE_WITHOUT_SOURCE`); with calibration missing or `"none"` -> warning
  (`UNCALIBRATED_MEASUREMENTS`).
* `confidence < 0.3` is reported as info. A recipe's `filters.minConfidence`
  drops entities below a threshold before generation (listed in the report,
  never silently).

`source` describes the material itself:

| Field | Meaning |
|---|---|
| `type` | `manual`, `video`, `images`, `survey`, `satellite`, `mixed`, `synthetic` |
| `description` | free text |
| `media[]` | `{id, kind: video\|image\|image_sequence\|point_cloud\|document\|other, file, capturedAt?, durationS?, description?, externalIds}` |
| `frameExtractions[]` | `{id, mediaId, method: fixed_interval\|keyframes\|manual, intervalS?, frameCount?, outputDirectory?, tool?}` |
| `frames[]` | `{id, mediaId, extractionId?, timestampS?, file?}` |
| `analysisReports[]` | `{id, file, tool?, createdAt?}` |
| `calibration` | `{method: none\|manual_scale\|reference_points\|gps\|photogrammetry\|survey, scaleConfidence?, estimatedErrorM?, referencePointIds, notes?}` |
| `referencePoints[]` | `{id, position [x,y,z], description?, geo? {latitude, longitude}, provenance?}` |
| `observations[]` | `{id, description, kind?, frameIds, reportId?, confidence?}` |
| `externalIds` | map of identifiers in other systems (`{"capture.app": "A-17"}`); never required for processing |

---

## Document reference

Notation: **R** = required; otherwise the default is shown (`[]` empty list,
`{}` empty map, `-` absent/null). `0..1` means a number in `[0, 1]`.
Every *entity* (anything with an `id` in a collection) also has the common
fields:

| Field | Default | Meaning |
|---|---|---|
| `id` | R | stable ID |
| `label` | - | human-readable name |
| `tags` | `[]` | `^[a-z0-9][a-z0-9_:-]{0,47}$`, at most 32 |
| `previousIds` | `[]` | former IDs (renames) |
| `provenance` | - | see above |
| `extensions` | `{}` | see [Extensions](#extensions) |

`transform` (point entities): `position` `[x, y, z]` **R**, `yawDeg` (`0`,
`[0, 360)`), `snapToTerrain` (`true`).

### Top level

| Field | Default | Meaning |
|---|---|---|
| `schemaVersion` | R | `"1.0"` |
| `locationId` | R | stable ID of the location |
| `name` | R | display name |
| `description` | - | text |
| `status` | `draft` | `draft`, `review`, `approved`, `deprecated` |
| `metadata` | R | below |
| `coordinateSystem` | R | below |
| `generation` | defaults | below |
| `source` | - | see provenance |
| `terrain` | defaults | below |
| `roads` | empty | `{nodes, segments}` |
| `plots`, `buildings`, `vegetationZones`, `trees`, `fences`, `infrastructure`, `props`, `landmarks` | `[]` | entity collections |
| `gameplay` | empty | below |
| `atmosphere` | neutral | below |
| `extensions` | `{}` | namespaced extension data |

### `metadata`

| Field | Default | Meaning |
|---|---|---|
| `createdAt` | R | timestamp with time zone |
| `updatedAt` | - | must not be before `createdAt` |
| `createdBy` | - | `{name, version?}` of the tool or person |
| `generatorVersion` | - | environment-generator version last used to check the file |
| `authors` | `[]` | names |
| `tags` | `[]` | |
| `biome` | `unknown` | `temperate`, `boreal`, `steppe`, `mediterranean`, `arid`, `tropical`, `alpine`, `unknown` |
| `season` | `unknown` | `spring`, `summer`, `autumn`, `winter`, `unknown` |
| `region` | - | informative text ("Central Russia") |

### `coordinateSystem`

All of `unit` (`"meter"`), `upAxis` (`"+y"`), `eastAxis` (`"+x"`), `northAxis`
(`"+z"`), `handedness` (`"left"`), `yawConvention`
(`"degrees_clockwise_from_north"`), `origin` (`"southwest_corner"`) and
`bounds` `{widthM, depthM}` (metres, `> 0`) are **R**; `geoReference` is
optional (see [Spatial conventions](#spatial-conventions)).

### `generation`

Generation controls stored with the location. They are preferences, not
observations; a recipe may override each one.

| Field | Default | Meaning |
|---|---|---|
| `masterSeed` | `0` | `0..2^63-1` |
| `structuralSimilarity` | `1.0` | `0..1`; 1 = keep the observed structure exactly, lower = allow deviation |
| `visualVariation` | `0.5` | `0..1`; 0 = uniform look, 1 = maximum variety |
| `subsystemSeeds` | `{}` | explicit seeds per subsystem: `terrain`, `roads`, `buildings`, `fences`, `infrastructure`, `vegetation`, `props`, `atmosphere`, `assets` |

Seed precedence: command-line `--seed` > recipe `seed` > `masterSeed`.
Subsystem seeds: recipe `subsystemSeeds` > blueprint `subsystemSeeds` >
derived from the master seed. Reusing one seed for several subsystems is
reported (`SUBSYSTEM_SEED_REUSED`). The built-in generators record
`structuralSimilarity` and `visualVariation` in the plan and manifest but do
not vary their output with them yet (info `GENERATION_CONTROL_RECORDED`).

### `terrain`

| Field | Default | Meaning |
|---|---|---|
| `elevation` | - | `{minM, maxM}` lowest and highest ground elevation |
| `heightmap` | - | external raster, see [Rasters](#rasters-heightmaps-and-masks): `file`, `encoding` (`raw_u16_le`\|`raw_f32_le`), `columns`, `rows` (`2..16385`), `rowOrder`, `heightScaleM` (`> 0`), `heightOffsetM` (`0`) |
| `masks[]` | `[]` | `{id, file, encoding: raw_u8, columns, rows, rowOrder, meaning}`; `meaning` is a vocabulary word such as `ground_wetness` |
| `defaultSurface` | `grass` | surface outside every surface zone |
| `surfaceZones[]` | `[]` | `{surface, polygon}`; surfaces: `grass`, `dirt`, `gravel`, `sand`, `mud`, `asphalt`, `concrete`, `moss`, `leaf_litter`, `rock`, `snow`, `unknown` |
| `slopeZones[]` | `[]` | `{slopeClass, polygon, averageSlopeDeg?, aspectDeg?}`; classes `flat` (<3 deg), `gentle` (3-8), `moderate` (8-15), `steep` (15-30), `cliff` (>30); `aspectDeg` = downhill direction clockwise from north |
| `waterBodies[]` | `[]` | `{waterType, polygon, surfaceElevationM?, depthM?}`; types `pond`, `lake`, `stream`, `river`, `ditch`, `puddle`, `marsh` |
| `notes` | - | text |

When surface zones overlap, the later zone in the list wins.

### `roads`

A graph: `nodes[]` and `segments[]`.

Node: `position` `[x, z]` **R**, `elevationM` (optional estimate), `nodeType`
(`endpoint` default, `junction`, `entrance`, `dead_end`, `boundary`,
`bridge_end`). A `junction` should join three or more segments; `dead_end`
and `boundary` nodes exactly one (`ROAD_NODE_DEGREE_MISMATCH`, warning).
Nodes used by no segment are reported (`ROAD_NODE_ISOLATED`).

Segment:

| Field | Default | Meaning |
|---|---|---|
| `sourceNodeId`, `targetNodeId` | R | road node IDs; segments are undirected |
| `curve` | polyline, no points | `{type: polyline\|catmull_rom, controlPoints: [[x, z], ...]}` between the nodes (exclusive) |
| `widthM` | R | carriageway width, `0.3 < w <= 60` |
| `surface` | R | `asphalt`, `concrete`, `gravel`, `dirt`, `grass`, `sand`, `unknown` |
| `importance` | R | `primary`, `secondary`, `access`, `track`, `path` (relative within the location) |
| `condition` | `1.0` | `0..1`; 0 = destroyed, 1 = good |
| `vegetationIntrusion` | `0.0` | `0..1`; 0 = clear, 1 = overgrown edges and centre |

A loop (`sourceNodeId == targetNodeId`) needs at least two control points.

### `plots`

| Field | Default | Meaning |
|---|---|---|
| `plotType` | R | `dacha_plot`, `yard`, `garden`, `vacant_lot`, `common_area`, `unknown` |
| `polygon` | R | parcel outline (the fence around it is a separate entity) |
| `condition` | - | `0..1` upkeep |
| `abandonment` | - | `0..1` |

### `buildings`

| Field | Default | Meaning |
|---|---|---|
| `archetype` | R | semantic archetype name (`wooden_house_small`) or a dotted registry ID; resolved by the asset registry |
| `buildingType` | R | `house`, `bathhouse`, `garage`, `shed`, `barn`, `greenhouse`, `outhouse`, `gazebo`, `workshop`, `shop`, `church`, `apartment_block`, `warehouse`, `factory`, `office`, `other`, `unknown` |
| `transform` | R | footprint centre at ground level; `yawDeg` = direction the front (entrance side) faces |
| `dimensions` | R | `{widthM, depthM, heightM}` (side to side, front to back, ground to ridge) |
| `footprint` | - | exact outline polygon; omitted = rectangle from transform and dimensions. When present its centroid and minimum rectangle should agree with transform and dimensions (`BUILDING_FOOTPRINT_MISMATCH`) |
| `floors` | - | `1..60`; `heightM` below `2 m * floors` is reported |
| `condition` | `1.0` | `0..1`; **0 = destroyed**, 1 = good condition |
| `abandonment` | `0.0` | `0..1`; **0 = inhabited or maintained**, 1 = strongly abandoned |
| `roofType` | `unknown` | `gable`, `hip`, `flat`, `shed`, `mansard`, `collapsed`, `unknown` |
| `wallMaterial` | `unknown` | `wood_log`, `wood_board`, `brick`, `concrete`, `cinder_block`, `stone`, `metal_sheet`, `plaster`, `glass`, `unknown` |
| `openings` | unknown | `{windows: intact\|broken\|boarded\|missing\|mixed\|unknown, doors: closed\|open\|broken\|missing\|boarded\|unknown}` |
| `plotId` | - | plot the building stands on |

Condition and abandonment are independent: an inhabited but shell-damaged
house is `condition 0.3, abandonment 0.0`; a sound but empty one is
`condition 0.9, abandonment 0.8`. Overlapping footprints are reported
(`BUILDING_OVERLAP`, warning).

### `vegetationZones` and `trees`

Zone:

| Field | Default | Meaning |
|---|---|---|
| `zoneType` | R | `forest_dense`, `forest_light`, `meadow`, `overgrown_yard`, `road_edge`, `clearing`, `wet_area`, `orchard`, `garden_beds`, `shrubland`, `unknown` |
| `polygon` | R | area |
| `density` | R | `0..1` canopy/plant cover; 0 = bare, 1 = closed |
| `species` | `[]` | `[{species, weight}]`; weights are relative (`> 0`, need not sum to 1); `species` is a vocabulary word (`birch`, `pine`, `lilac`) or `unknown`; empty list = species unknown; each species at most once |
| `understoryDensity` | - | `0..1` shrubs below the canopy |
| `grassDensity` | - | `0..1` ground cover |
| `heightRange` | - | `{minM, maxM}` typical plant heights |

`unknown` is a legitimate answer: do not guess species. Consumers choose a
generic plant for the unknown share.

Tree (a significant individual tree): `species` (`unknown`), `archetype` (-),
`transform` **R**, `heightM` (-), `crownDiameterM` (-), `condition` (`1.0`;
0 = dead or broken).

### `fences`

| Field | Default | Meaning |
|---|---|---|
| `fenceType` | R | `wooden_picket`, `wooden_board`, `chain_link`, `metal_sheet`, `wire`, `brick`, `concrete`, `stone`, `metal_railing`, `unknown` |
| `path` | R | `[x, z]` points (at least two) |
| `closed` | `false` | the fence returns from the last point to the first |
| `heightM` | R | `0 < h <= 10` |
| `condition` | `1.0` | `0..1` |
| `missingSections` | `[]` | `[{start, end}]`, see below |
| `archetype` | - | semantic archetype name |
| `materialHint` | - | vocabulary word (`weathered_pine`) |
| `plotId` | - | plot it encloses |
| `gameplay` | - | `{movement?, projectileCover?, vision?}`, see [gameplay](#gameplay) |

**Missing sections** are gaps where the fence has fallen or was never built.
`start` and `end` are fractions `0..1` of the total path length measured from
the first point along the path (including the closing edge when `closed`),
with `start < end`. Sections must not overlap; a fence missing completely is
reported (`FENCE_FULLY_MISSING`).

### `infrastructure`

A list of points and wires, discriminated by `infrastructureType`.

Point: `infrastructureType` (`utility_pole`, `well`, `light`, `sign`,
`water_tower`, `container`, `transformer`, `pump`, `other`) **R**, `archetype`
(-), `transform` **R**, `heightM` (-), `condition` (`1.0`), `parentId` (-; the
structure it is attached to, e.g. a light on a pole; parents must form a
tree), `gameplay` (-).

Wire: `infrastructureType: "wire"`, `wireKind` (`power`, `telephone`,
`unknown`; default `unknown`), `poleIds` **R** (at least two point IDs, in
order; the same pole twice in a row is an error), `sagM` (-), `condition`
(`1.0`). Wires normally hang from `utility_pole`, `light` or `water_tower`
points (`WIRE_UNUSUAL_SUPPORT` otherwise).

### `props`

`propType` **R** (`barrel`, `tires`, `pallet`, `woodpile`, `tools`, `bicycle`,
`wheelbarrow`, `debris`, `bucket`, `bench`, `crate`, `gas_cylinder`, `car`,
`car_wreck`, `boat`, `cart`, `dumpster`, `hay_bale`, `sandbags`, `other`),
`archetype` (-), `transform` **R**, `condition` (`1.0`), `parentId` (-; plot,
building, infrastructure point, tree or prop it belongs to or rests on).

### `landmarks`

Points of orientation or significance.

| Field | Default | Meaning |
|---|---|---|
| `landmarkType` | R | `water_tower`, `church`, `shop`, `large_tree`, `crossroads`, `well`, `gate`, `ruin`, `sign`, `bus_stop`, `building`, `other` |
| `position` | R | `[x, y, z]`; may lie outside the bounds (a distant church tower) |
| `importance` | `0.5` | `0..1` |
| `visibility` | `medium` | `low`, `medium`, `high` |
| `visibilityRadiusM` | - | distance from which it is recognisable |
| `linkedEntityId` | - | building, tree, road node or infrastructure point it marks; should be within 50 m |
| `gameplayRoles` | `[]` | vocabulary words: `orientation`, `objective`, `rally_point`, ... |

### `gameplay`

Gameplay intent, kept separate from physical description. Three effects are
always distinguished:

* **movement** - `none`, `slow`, `block` (can a unit pass?);
* **projectileCover** - `none`, `partial`, `full` (does it stop bullets?);
* **vision** - `none`, `partial`, `full` (does it hide what is behind it?).

A board fence blocks movement and vision but stops no projectiles; tall grass
slows movement and partially hides but gives no cover.

| Field | Meaning |
|---|---|
| `navigationAreas[]` | `{id, areaType: walkable\|blocked, polygon?, entityIds, reason?}`; needs a polygon or entity IDs |
| `coverZones[]` | `{id, polygon, movement (none), projectileCover (partial), vision (partial), linkedEntityIds, notes?}` |
| `combatZones[]` | `{id, polygon, intensity: low\|medium\|high, engagementRange: close\|medium\|long\|mixed, notes?}` |
| `spawnClearances[]` | `{id, position [x, z], radiusM, role (spawn)}`; must not lie inside a building |
| `connectivity` | `{requireRoadNetworkConnected (true), requireEntrancesReachable (true), entranceIds}`; entrances are road nodes or plots |
| `lineOfSight[]` | `{id, fromPosition [x,y,z], toPosition [x,y,z], expected: clear\|partial\|blocked, notes?}` designer expectations to test against |
| `notes` | text |

Per-entity `gameplay` hints on fences and infrastructure points use the same
three fields; `null` means "derive downstream".

### `atmosphere`

The observed or intended look. Every value has a neutral default.

| Field | Default | Range | Meaning |
|---|---|---|---|
| `weather` | `clear` | `clear`, `partly_cloudy`, `overcast`, `fog`, `light_rain`, `rain`, `storm`, `snow` | |
| `timeOfDay` | `afternoon` | `dawn`, `morning`, `noon`, `afternoon`, `dusk`, `night` | |
| `groundWetness` | `0` | `0..1` | 0 = dry, 1 = waterlogged |
| `abandonment` | `0` | `0..1` | overall impression; buildings carry their own value |
| `vegetationCondition` | `1` | `0..1` | 0 = dead or dry, 1 = lush |
| `fogDensity` | `0` | `0..1` | 0 = none, 1 = very dense (not a physical coefficient) |
| `saturation` | `1` | `0..2` | colour saturation multiplier, 1 = neutral |
| `contrast` | `1` | `0..2` | contrast multiplier, 1 = neutral |
| `palette` | `[]` | at most 32 | `[{role, color: "#RRGGBB"}]` reference colours |

---

## Validation and diagnostics

Validation runs in phases; a phase only runs when the previous ones allow it:

1. **version** - `schemaVersion` (above);
2. **schema** - types, ranges, enums, required fields, unknown fields;
3. **semantic** - rules across fields (geometry, ranges, duplicates);
4. **reference** - every ID reference resolves to the right kind;
5. **external** - referenced files exist, stay in the package, match size,
   checksum and raster dimensions.

Every diagnostic has:

| Field | Meaning |
|---|---|
| `severity` | `error` (the document is invalid), `warning` (valid but suspicious), `info` |
| `code` | stable `UPPER_SNAKE_CASE` identifier |
| `message` | human-readable explanation |
| `category` | `version`, `schema`, `semantic`, `reference`, `external` (and `interpretation`, `override` from the generator) |
| `path` | JSON path into the document: `buildings[2].transform.yawDeg` |
| `entityIds` | affected entity IDs, most relevant first |
| `suggestion` | how to fix it, when known |

Schema diagnostics use the code `SCHEMA_<PYDANTIC_ERROR_TYPE>` (e.g.
`SCHEMA_MISSING`, `SCHEMA_EXTRA_FORBIDDEN`, `SCHEMA_LESS_THAN_EQUAL`,
`SCHEMA_ENUM`, `SCHEMA_STRING_PATTERN_MISMATCH`, `SCHEMA_LITERAL_ERROR`).
Other codes:

| Code | Severity | Phase | Meaning |
|---|---|---|---|
| `BLUEPRINT_VERSION_MISSING` / `_INVALID` / `_TOO_NEW` / `_UNSUPPORTED` | error | version | see [Versioning](#versioning-and-migration) |
| `BLUEPRINT_MIGRATION_REQUIRED` | error | version | migrate first |
| `BLUEPRINT_LEGACY_FORMAT` | error | version | snake_case 0.1 draft |
| `DUPLICATE_ID` | error | semantic | ID used twice anywhere in the document |
| `PREVIOUS_ID_CONFLICT` | error | semantic | a former ID collides with another ID or alias |
| `METADATA_TIME_ORDER` | error | semantic | `updatedAt < createdAt` |
| `RANGE_INVERTED` | error | semantic | a `min` above its `max` |
| `SUBSYSTEM_SEED_REUSED` | warning | semantic | two subsystems share a seed |
| `POLYGON_SELF_INTERSECTING` / `_DEGENERATE` / `_DUPLICATE_POINT` / `_CLOSING_POINT_REPEATED` | error | semantic | invalid polygon |
| `POLYLINE_DEGENERATE` / `_DUPLICATE_POINT` / `_CLOSING_POINT_REPEATED` | error | semantic | invalid path (use `closed` instead of repeating the first point) |
| `ENTITY_OUTSIDE_BOUNDS` | error | semantic | entity entirely outside the bounds (0.5 m tolerance) |
| `ENTITY_PARTIALLY_OUTSIDE_BOUNDS` | warning | semantic | entity crosses the bounds |
| `TRANSFORM_ELEVATION_OUT_OF_RANGE` | warning | semantic | non-snapped `y` far outside `terrain.elevation` |
| `ROAD_SEGMENT_DEGENERATE` | error | semantic | loop without two control points |
| `ROAD_CURVE_DUPLICATE_POINT` | error | semantic | consecutive identical curve points (incl. node positions) |
| `ROAD_NODE_ISOLATED` | warning | semantic | node without segments |
| `ROAD_NODE_DEGREE_MISMATCH` | warning | semantic | junction with < 3 segments, dead end or boundary with > 1 |
| `BUILDING_FOOTPRINT_MISMATCH` | warning | semantic | footprint disagrees with transform/dimensions |
| `BUILDING_HEIGHT_IMPLAUSIBLE` | warning | semantic | `heightM < 2 m * floors` |
| `BUILDING_OVERLAP` | warning | semantic | footprints overlap |
| `VEGETATION_SPECIES_DUPLICATE` | error | semantic | species listed twice |
| `MISSING_SECTION_INVALID` / `MISSING_SECTION_OVERLAP` | error | semantic | bad fence gap |
| `FENCE_FULLY_MISSING` | warning | semantic | missing sections cover the whole fence |
| `WIRE_DUPLICATE_POLE` | error | semantic | the same pole twice in a row |
| `LANDMARK_OUTSIDE_BOUNDS` | info | semantic | distant landmark |
| `NAVIGATION_AREA_EMPTY` | error | semantic | neither polygon nor entity IDs |
| `SPAWN_CLEARANCE_BLOCKED` | warning | semantic | spawn centre inside a building |
| `PROVENANCE_CONFIDENCE_MISSING` | warning | semantic | observed/inferred without confidence |
| `PROVENANCE_LOW_CONFIDENCE` | info | semantic | confidence < 0.3 |
| `PROVENANCE_WITHOUT_SOURCE` | warning | semantic | measured data but no `source` |
| `UNCALIBRATED_MEASUREMENTS` | warning | semantic | measured data without calibration |
| `REFERENCE_NOT_FOUND` | error | reference | no entity with that ID |
| `REFERENCE_WRONG_TYPE` | error | reference | entity of the wrong kind |
| `REFERENCE_USES_PREVIOUS_ID` | error | reference | reference by a former ID |
| `PARENT_CYCLE` | error | reference | `parentId` chain loops |
| `WIRE_UNUSUAL_SUPPORT` | warning | reference | wire attached to e.g. a well |
| `LANDMARK_FAR_FROM_LINKED_ENTITY` | warning | reference | linked entity more than 50 m away |
| `EXTERNAL_FILE_MISSING` | error / warning | external | required / optional file missing |
| `EXTERNAL_FILE_SIZE_MISMATCH` / `_CHECKSUM_MISMATCH` | error | external | file differs from the reference |
| `EXTERNAL_RASTER_SIZE_MISMATCH` | error | external | size is not `columns * rows * bytes` |
| `EXTERNAL_PATH_ESCAPES_PACKAGE` | error | external | resolved path leaves the package |
| `EXTERNAL_FILES_NOT_CHECKED` | warning | external | no package root known (document given as data) |
| `HEIGHTMAP_UNREADABLE` | error | external | heightmap cannot be decoded |
| `HEIGHTMAP_ELEVATION_MISMATCH` | warning | external | heightmap range outside `terrain.elevation` |

Validation never repairs input. A document with any `error` is not loaded.

---

## Recipe and overrides

Three documents, three responsibilities:

| Document | Contains | Never contains |
|---|---|---|
| LocationBlueprint | facts and estimates about one place, with provenance | styles, asset choices, generation rules |
| LocationRecipe (`schemas/location-recipe.schema.json`) | how to interpret any blueprint: style, asset filters (`allowedArchetypes`, tags), density, generator settings, seeds and controls | geometry, observations, entity IDs |
| LocationOverrides (`schemas/location-overrides.schema.json`) | explicit author changes to one location, by entity ID | anything the blueprint already says |

A recipe is reusable: `appliesTo` (glob patterns on `locationId`) can restrict
it to a family of locations (`dacha-*`). Recipe values left `null`
(`seed`, `structuralSimilarity`, `visualVariation`, `abandonment`) fall back to
the blueprint (`generation.*`, `atmosphere.abandonment`); `detailDensity`
(default 1) scales procedural detail.

### Overrides

```json
{
  "schemaVersion": "1.0",
  "id": "dacha-designer-pass-01",
  "locationId": "dacha-forest-edge",
  "recipeId": "dacha-overgrown",
  "conflictPolicy": "fail",
  "entityOperations": [
    { "op": "update", "id": "b-house-02", "expectedType": "buildings",
      "patch": { "condition": 0.4, "openings": { "windows": "boarded" } } },
    { "op": "replaceArchetype", "id": "b-house-06", "archetype": "wooden_house_medium" },
    { "op": "delete", "id": "pr-tires-06", "expectedType": "props" },
    { "op": "add", "collection": "props", "entity": { "id": "pr-sandbags-junction", "...": "..." } }
  ],
  "placementOverrides": [
    { "entityId": "building.b-garage-06", "position": [101.0, 141.02, 27.0] }
  ]
}
```

* `locationId` must match the blueprint; `recipeId`, when set, must match the
  recipe.
* **Entity operations** change the blueprint *before* generation, in document
  order: `update` applies an RFC 7396 JSON merge patch (objects merge, `null`
  removes an optional field, arrays are replaced; `id` cannot change),
  `replaceArchetype` sets `archetype`, `delete` removes the entity, `add`
  appends a complete entity to `collection` (`roadNodes`, `roadSegments`,
  `plots`, `buildings`, `vegetationZones`, `trees`, `fences`,
  `infrastructure`, `props`, `landmarks`, `waterBodies`, `surfaceZones`).
  `expectedType` guards against a target that moved to another collection.
  Targets may be found through `previousIds`.
* **Placement overrides** move, turn or scale *generated* entities (manifest
  IDs such as `building.b-12`) after generation, in the location frame
  (`position [x, y, z]`, `yawDeg` clockwise, `scale [width, height, depth]`).
* **The source blueprint is never modified.** A new effective blueprint is
  built from a copy and fully re-validated; if the result is invalid (for
  example a deleted building still linked by a landmark), the run fails with
  every diagnostic.
* **Conflicts are never dropped silently.** Missing target
  (`OVERRIDE_TARGET_MISSING`), wrong collection (`OVERRIDE_TYPE_MISMATCH`),
  duplicate or former ID on add (`OVERRIDE_ID_CONFLICT`), add without ID
  (`OVERRIDE_ADD_WITHOUT_ID`), ID change (`OVERRIDE_ID_CHANGE`) and
  `replaceArchetype` on an entity without archetype (`OVERRIDE_NO_ARCHETYPE`):
  with `conflictPolicy: "fail"` (default) the run stops; with `"report"` the
  operation is skipped and reported as a warning listing the operation. A
  different `locationId` always fails.
* **Traceability.** Every generated entity lists the operations that shaped
  it in `provenance.overrides` (`dacha-designer-pass-01#entityOperations[0]`,
  `...#placementOverrides[1]`).

---

## Extensions

`extensions` is allowed at the top level and on every entity. Keys must match
`^x-[a-z0-9][a-z0-9_.-]{0,63}$` (prefix with your tool or studio:
`x-studio.ruts`). Values are any JSON. Consumers must ignore keys they do not
understand and must preserve them when they rewrite a document. Object keys
inside extensions are sorted on load; extensions must not change the meaning
of standard fields.

---

## The dacha fixture

`examples/locations/dacha-forest-edge/` is the stable reference package
(synthetic and hand-authored; no footage, Meshy assets, Blender, Unity or
network needed):

* 160 m x 120 m, temperate, autumn; a 65 x 65 `raw_u16_le` heightmap
  (`terrain/heightmap.r16`, 140.5-146.4 m, rising towards the forest) and a
  33 x 33 `raw_u8` wetness mask, both with SHA-256 and size;
* a gravel main road (`primary`, Catmull-Rom) with a junction, a dirt lane
  (`secondary`) to the forest gate and a forest path (`path`);
* eight plots, wooden houses (small, medium, two-storey), a bathhouse, a metal
  garage, a shed, an outhouse and a collapsed greenhouse, with condition and
  abandonment from 0.15 to 1;
* a mixed forest, a forest edge, an overgrown yard with partly `unknown`
  species, an orchard, garden beds, a wet area by a pond, roadside nettles and
  a meadow; four notable trees;
* six fences with eight missing sections and gameplay hints;
* seven utility poles, two power wires, a lamp attached to a pole, a well, a
  sign and a container; nine props with parents;
* four landmarks, navigation areas, four cover zones (movement, projectile and
  vision set independently), a combat zone, spawn clearances, connectivity and
  a line-of-sight expectation;
* overcast autumn morning with light fog and a palette.

The matching `examples/recipes/dacha-overgrown.recipe.json` and
`examples/overrides/dacha-forest-edge.designer-pass.overrides.json` are separate
files; `examples/expected-output/dacha-forest-edge.dacha-overgrown.designer-pass-01/`
is the generated result. The fixture validates with no diagnostics and is
byte-identical after `load -> save`.

---

## Implementing a consumer

A compatible consumer (another language, an engine importer, an analysis tool):

1. Read the file as UTF-8 JSON. Check `schemaVersion` first and apply the
   version table; never guess field meanings of an unsupported version.
2. Validate against `schemas/location-blueprint.schema.json`. Treat absent
   fields as their schema defaults.
3. Apply the rules the schema cannot express that matter to you: the
   document-wide ID namespace and reference kinds, polygon validity, bounds,
   and file checks. The diagnostic codes above are the shared vocabulary.
4. Resolve files relative to the blueprint's folder; reject paths that
   escape it. Decode rasters exactly as described (corner-aligned, row order,
   scale and offset).
5. Keep the frame: `+X` east, `+Y` up, `+Z` north, yaw clockwise. Convert
   only at your boundary with explicit formulas (table above).
6. Interpret roads with the Catmull-Rom definition above; choose your own
   sampling density.
7. Preserve unknown `extensions` and every ID when writing documents back;
   write canonical form if you want byte-stable diffs.

Producers (location-analysis tools) additionally: assign stable IDs once;
record provenance honestly (`observed` vs `inferred` vs `manual` vs
`procedural`, with confidence); reference only real source material; write
large data as external files with checksums.

---

## Python API and CLI

```python
from environment_generator.blueprint import dumps_blueprint, load_blueprint, validate_source

path = "examples/locations/dacha-forest-edge/location.blueprint.json"
blueprint = load_blueprint(path)  # raises with diagnostics on any error
result = validate_source(path)  # never raises for invalid content
report = result.report()  # ValidationReport: valid, counts, diagnostics
text = dumps_blueprint(blueprint)  # canonical JSON
```

Also available: `parse_blueprint` (from data), `save_blueprint`,
`migrate_document` / `migrate_file`, `apply_entity_operations` (overrides) and
`blueprint_to_site`; see `environment_generator/blueprint/__init__.py`.

```bash
envgen blueprint validate PATH [--json] [--package-root DIR] [--no-external]
envgen blueprint format PATH [--check | --output FILE [--force]]
envgen blueprint migrate PATH (--output FILE | --in-place) [--force]
envgen generate -b PATH -r RECIPE -o OVERRIDES -d OUT --preview
```

`blueprint validate` exits with 0 when the document is valid (warnings
allowed) and 3 otherwise; `--json` prints the `ValidationReport`.
