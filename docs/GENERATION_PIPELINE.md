# Generation pipeline

## Stages

| # | Stage (`name`) | Class | Input | Output | Fails with |
| --- | --- | --- | --- | --- | --- |
| 1 | `load_inputs` | `LoadInputsStage` | `InputBundle` (paths or parsed JSON) | `LoadedInputs` | `InputLoadError`, `ContractValidationError`, `SemanticValidationError` |
| 2 | `resolve_inputs` | `ResolveInputsStage` | `LoadedInputs` | `ResolvedInputs` | `OverrideError`, `SemanticValidationError` |
| 3 | `resolve_assets` | `ResolveAssetsStage` | `ResolvedInputs` | `AssetPalette` | `AssetResolutionError` |
| 4 | `plan_generation` | `PlanGenerationStage` | `PlanningInput(resolved, palette)` | `GenerationPlan` | `PlanningError` |
| 5 | `generate_scene` | `GenerateSceneStage` | `GenerationPlan` | `Scene` | `PlanningError`, `GenerationError`, `AssetResolutionError`, `OverrideError` |
| 6 | `validate_layout` | `ValidateLayoutStage` | `LayoutInput(scene, plan)` | `LayoutValidationResult` | `LayoutValidationError` |
| 7 | `export_manifest` | `ExportManifestStage` | `ExportInput(scene, plan, directory)` | `ExportResult(manifest, path)` | `ExportError` |
| 8 | `build_report` | `BuildReportStage` | `ReportInput` | `GenerationReport` | - |

Each stage returns a `StageOutcome(output, issues, summary)`: non-fatal issues
(warnings, info) travel with the result; fatal problems raise. The
`Pipeline` records a `StageReport` (status, duration, summary, issues) per
stage.

* **Dry run** (`--dry-run`, `PipelineOptions(dry_run=True)`, `envgen plan`):
  stages 1-4 run; 5-7 are reported as skipped; `generation-plan.json` is
  written.
* **Replay** (`envgen generate --plan`, `Pipeline.run_plan`): stages 5-8 run
  from a saved plan; 1-4 are reported as skipped. The plan is self-contained
  (effective blueprint, effective recipe, filtered archetypes, seeds, pending
  entity operations), and replaying it yields the same manifest as the direct
  run.

### 1. Load inputs

Reads each document (file path or mapping), validates it against its model
and collects *all* contract violations before failing, with locations such as
`blueprint:buildings[3].geometry.points`. Missing recipe -> built-in default
recipe; missing registry -> built-in registry. Then runs semantic checks on
the blueprint, recipe, registry and their compatibility (recipe
`applies_to` globs, overrides `blueprint_id` / `recipe_id`). Computes content
fingerprints of every input.

### 2. Resolve recipe and overrides

In order:

1. `recipe_patch` is applied to the recipe as an RFC 7396 merge patch (`null`
   resets a field to its default) and the result is validated again.
2. `feature_operations` (`add`, `remove`, `patch`) are applied to the blueprint
   in document order; the result is validated by the model and the semantic
   checks again. Unknown targets or duplicate IDs raise `OverrideError`.
3. The master seed is chosen: `--seed` / `seed_override` > `overrides.seed` >
   `recipe.seed`.
4. Features below `recipe.filters.min_confidence` are dropped (reported as
   info).

`entity_operations` are carried forward to stage 5.

### 3. Resolve asset archetypes

The registry is filtered to a **palette**: archetypes that carry all
`required_tags`, none of the `excluded_tags`, and support the blueprint biome
(empty `biomes` = any). Every enabled generator reports the archetype kinds it
will request (`WorkEstimate.asset_needs`); needs no palette archetype covers
produce `ASSET_KIND_UNAVAILABLE` warnings, or an `AssetResolutionError` when
the recipe sets `assets.fallback: error`.

### 4. Plan

Enabled generators (recipe `<slot>.enabled`) are ordered topologically by their
declared dependencies, ties broken by the canonical slot order
`terrain, roads, buildings, fences, infrastructure, vegetation, props,
atmosphere`. Dependencies on disabled generators are dropped (they are
ordering constraints, not hard requirements). Each task records its
`implementation@version`, its seed, its source features and an entity estimate.

### 5. Generate the scene

Tasks run in plan order with a shared `GenerationContext`. After each task the
pipeline checks the slot contract: categories must be in the slot's
`produces`, IDs must be unique, the terrain slot must return a heightfield and
the atmosphere slot must return settings. Generator crashes (`ValueError`,
`ArithmeticError`, model validation errors, ...) become `GenerationError`
naming the generator. Finally `entity_operations` are applied and entities are
sorted by ID.

### 6. Validate the layout

`RuleBasedLayoutValidator` rebuilds footprints from the scene and runs:

| Rule | Issue code | Severity |
| --- | --- | --- |
| `unique_ids` | `LAYOUT_DUPLICATE_ID` | error |
| `within_extent` | `LAYOUT_OUT_OF_BOUNDS` / `LAYOUT_GEOMETRY_OUTSIDE_EXTENT` | error / warning |
| `known_archetypes` | `LAYOUT_UNKNOWN_ARCHETYPE` / `LAYOUT_PLACEHOLDER_ASSETS` | error / warning |
| `building_spacing` | `LAYOUT_BUILDING_OVERLAP` (closer than `min_building_spacing_m`) | error |
| `obstructions` | `LAYOUT_ROAD_OBSTRUCTED` (buildings, infrastructure, props on roads) | error (warning for vegetation and fences) |
| `obstructions` | `LAYOUT_WATER_OBSTRUCTED` (same categories in water) | error (warning for vegetation and fences) |
| `obstructions` | `LAYOUT_SOLID_OVERLAP` (anything intersecting a building) | warning |
| `ground_contact` | `LAYOUT_GROUND_CONTACT` (more than `ground_tolerance_m` off the terrain) | warning |
| `entity_budget` | `LAYOUT_ENTITY_BUDGET` (over / above 90 % of `max_entities`) | error / warning |

With `validation.fail_on_error` (default) any error stops the pipeline before
export.

### 7. Export

`JsonManifestExporter` writes `scene-manifest.json` (see [Manifest
format](#manifest-format)) and computes its content hash.

### 8. Report

`generation-report.json` lists every stage with status, duration (omit with
`--no-timings` for byte-stable reports), summary values and issues, plus run
metadata, statistics, issue counts and output file names. The CLI prints the
same information as text.

## Coordinate system and units

| Aspect | Convention |
| --- | --- |
| Units | metres, degrees |
| Axes | right-handed, **+X east, +Y north, +Z up** |
| Origin | south-west corner of the blueprint `extent`; the playable area is `[0, width_m] x [0, depth_m]` |
| Rotation | `rotation_deg = [x, y, z]`, extrinsic X then Y then Z; `z` is the yaw, counter-clockwise seen from above |
| Object frame | local +X = width, local +Y = depth and **front**, local +Z = up; at yaw 0 the front faces north |
| Archetype dimensions | `width_m` along local X, `depth_m` along local Y, `height_m` along local Z; buildings use `width >= depth` with the front on a long side |
| Geometry | `geometry.points` are always world coordinates; the entity transform then sits on the first point (roads, cables) or centroid (water) with identity rotation |
| Heightfield | `heights[row][column]`; row 0 is the southern edge (`y = 0`), column 0 the western edge; sample spacing `cell_size_m`; bilinear interpolation between samples |
| Geo reference | optional and informative; `heading_deg` is the compass bearing of local +Y |

The current generators only produce yaw rotations. See
[ADAPTERS.md](ADAPTERS.md#coordinate-conversion) for the Unity mapping.

## Entities

```jsonc
{
  "id": "building.b-shop",                 // stable, see table below
  "category": "building",                  // terrain|water|road|building|fence|infrastructure|vegetation|prop
  "kind": "shop",                          // semantic kind (blueprint kind or generator-chosen)
  "archetype_id": "building.house.flat_modern",
  "asset_ref": "envgen://building/house/flat_modern",
  "variant": 0,                            // < archetype.variants
  "placeholder": false,
  "transform": { "position": [149.0, 126.0, 2.0133], "rotation_deg": [0, 0, 183.0], "scale": [1, 1, 1] },
  "dimensions": { "width_m": 10.0, "depth_m": 9.0, "height_m": 6.5 },   // world size after scaling
  "geometry": null,                        // polyline/polygon for roads, cables, pipelines, water
  "parameters": { "condition": "intact", "cover": "full", "floors": 1, "foundation_m": 0.0829, "roof": "flat" },
  "tags": ["intact"],
  "provenance": {
    "generator": "buildings",
    "implementation": "footprint_buildings@1.0.0",
    "rule": "explicit_footprint",
    "source_feature": "buildings/b-shop",
    "overrides": ["designer-pass-01#entity_operations[0]"]
  }
}
```

`parameters.cover` (`none|partial|half|full`) is a tactical hint copied from
the archetype. Building `parameters.floors` is kept for modular engine
prefabs; the archetype keeps its designed height and only the footprint is
scaled to fit.

### Entity IDs

| Entity | ID |
| --- | --- |
| Terrain | `terrain` |
| Water body | `water.<feature>` |
| Road | `road.<feature>` |
| Road junction | `road.junction.<roadA>.<roadB>.<n>` |
| Surveyed building | `building.<feature>` |
| Infill building | `building.fill.<zone>.<road>.<l\|r><nnn>` |
| Fence / wall panel | `fence.<feature>.e<edge>p<panel>` |
| Point infrastructure, pipeline | `infrastructure.<feature>` |
| Pole of a line | `infrastructure.<feature>.pole<nnn>` |
| Cable of a line | `infrastructure.<feature>.cable` |
| Street light | `infrastructure.street_light.<road>.<l\|r><nnn>` |
| Scattered plant | `vegetation.<feature>.<candidate:05d>` |
| Orchard tree | `vegetation.<feature>.r<row>c<column>` |
| Hedge / tree-line plant | `vegetation.<feature>.<index:04d>` |
| Single surveyed plant | `vegetation.<feature>` |
| Surveyed prop | `prop.<feature>` |
| Clutter prop | `prop.clutter.<building>.<nn>` |

IDs depend only on feature IDs and local indices. A scattered plant keeps its
ID and position when other candidates are blocked or freed, because every
candidate draws from its own random stream.

### Provenance

`generator` and `implementation` name the code that created the entity,
`rule` the placement rule (`explicit_footprint`, `zone_infill`,
`area_scatter`, `orchard_grid`, `line_planting`, `panel`, `line_pole`,
`line_cable`, `street_light_spacing`, `building_clutter`, `junction`,
`centerline`, `water_surface`, `heightfield`, `explicit_point`),
`source_feature` the blueprint feature (`collection/id`) and `overrides` every
entity operation applied (`<overrides-id>#entity_operations[<i>]`).

## Generators

* **Terrain (`heightfield@1.0.0`)** - grid with `cell_size_m` spacing covering
  the extent. With spot heights, the base surface interpolates them (inverse
  distance weighting); otherwise it is `base_elevation_m`. Fractal value noise
  (`noise_amplitude_m`, default from `relief`: flat 0, gentle 1.5, hilly 6,
  rugged 14 m) adds relief and fades out near spot heights so surveyed values
  are reproduced exactly. Each water body becomes a flat surface at its lowest
  shoreline height; the terrain beneath is carved `water_depth_m` deeper.
* **Roads (`polyline_roads@1.0.0`)** - one entity per road with a
  terrain-following, densified centre line and width (defaults per road kind,
  times `width_scale`); surface defaults per kind. Junctions are detected
  between all road pairs (crossings, T-junctions, shared end points) and
  merged when close.
* **Buildings (`footprint_buildings@1.0.0`)** - rectangles are used directly,
  polygons are reduced to their minimum-area rectangle; the archetype is
  chosen by kind, footprint fit, floors, roof and condition, and scaled to the
  footprint. With `orient_to_roads` the front faces the nearest road.
  `damage_ratio` / `ruin_fraction` deterministically degrade intact buildings.
  Zone infill samples lots every `lot_spacing_m` along each road inside zones
  of the listed kinds, keeps a lot with probability `zone.density`, and
  places a weighted random building facing the road if it lies fully in the
  zone and keeps `spacing_m` from roads, buildings, water, fences and
  surveyed point features.
* **Fences (`panel_fences@1.0.0`)** - each polyline edge is split into equal
  panels no longer than the archetype panel; declared gaps are cut exactly;
  with `gap_at_roads` panels crossing a road are left out. Heights default per
  fence kind.
* **Infrastructure (`standard_infrastructure@1.0.0`)** - point features placed
  as surveyed; power/telephone lines get poles at every vertex and in between
  (at most `pole_spacing_m` apart; blocked poles are nudged along the line or
  dropped with a warning), poles list their neighbours in `connects_to`, and
  one cable entity runs through the pole tops; pipelines are one polyline
  entity. Street lights are placed every `spacing_m` beside roads of the listed
  kinds, facing the road, skipping blocked spots.
* **Vegetation (`scatter_vegetation@1.0.0`)** - areas: dart throwing with a
  target of `area/100 x rate x density x density_scale` (rate per 100 m^2:
  forest 4, woodland 1.6, scrub 5, meadow 3), kind-dependent spacing and
  clearance from roads, buildings, water, fences and infrastructure; forests
  and woodland get an understory share of bushes. Orchards are jittered grids.
  Hedgerows and tree lines are planted along their polylines. Single surveyed
  plants are always placed. Species come from the archetype palette (biome
  filtered, weighted, preferred tags boosted).
* **Props (`clutter_props@1.0.0`)** - surveyed props as given; clutter around
  every building (`per_building` on average, kinds from a per-building-kind
  table or `kind_weights`), placed beside the walls, aligned to the building,
  avoiding everything already placed.
* **Atmosphere (`preset_atmosphere@1.0.0`)** - for each of time of day,
  weather and season the recipe wins, then the blueprint observation, then
  afternoon / clear / summer. Presets give key light elevation, azimuth,
  colour and intensity, ambient light, fog, clouds, precipitation (rain turns
  to snow in winter), wind and foliage state. The azimuth is mirrored for the
  southern hemisphere and rotated by the blueprint heading.

### Asset resolution

`PaletteAssetResolver.resolve(request)`:

1. Candidates are palette archetypes of the requested category supporting the
   first requested kind that any archetype supports (later kinds are
   fallbacks, e.g. `("fruit_tree", "tree")`).
2. Each candidate gets a fit score (0 = perfect): `-2 |ln(w/w0)| - 2 |ln(d/d0)|`
   for footprint size, `-|ln(h/h0)|` for height, up to `-3` for floors outside
   `[min_floors, max_floors]`, `-1` for a roof mismatch and `-3` for a
   condition or surface mismatch.
3. Archetypes within 0.5 of the best score are drawn by weight, where each
   matched preferred tag doubles the weight, using a stream derived from the
   entity ID. The variant is derived from the entity ID too.
4. If nothing matches: a `placeholder.<category>.<kind>` archetype sized to the
   request, or `AssetResolutionError` with `fallback: error`.

## Determinism

**Guarantee:** the same blueprint, recipe, overrides, registry, generator
version and seed produce a byte-identical `scene-manifest.json` (and, with
`--no-timings`, `generation-report.json`) in any process, independent of
`PYTHONHASHSEED`, input file formatting or key order. This is covered by
`tests/integration/test_determinism.py`, which also runs the CLI in separate
processes with different hash seeds.

How:

* **Seeds.** `derive_seed(base, *labels)` = first 8 bytes (big-endian) of
  `SHA-256("base\x1flabel1\x1flabel2...")`, masked to 63 bits.
  * master seed: `--seed` > `overrides.seed` > `recipe.seed`;
  * generator task seed: `derive_seed(master, "generator", <slot>)` (listed in
    the plan and in `manifest.source.generator_seeds`);
  * per feature / candidate streams: `derive_seed(task_seed, <labels...>)`,
    e.g. `("scatter", "forest-east", 42)`;
  * asset choices: `derive_seed(master, "assets")`, then per entity ID.
* **PRNG.** xoshiro256**, state initialised with four SplitMix64 outputs of
  the seed; `random()` = `(next_u64 >> 11) * 2^-53`. Reference values are
  pinned in `tests/unit/test_core_primitives.py`.
* **Ordering.** Features are processed sorted by ID, generators in plan
  order, spatial queries return insertion order, entities are sorted by ID,
  set iteration is never used for output.
* **Serialisation.** Floats are rounded to 4 decimals (0.1 mm), `-0.0`
  becomes `0.0`. `content_hash` is the SHA-256 of the canonical JSON
  (sorted keys, compact) of the manifest without the `content_hash` field;
  `envgen verify` recomputes it.
* **Versioning.** Any change that alters output must bump the generator's
  `version` and the package version; both are recorded in the plan, the
  manifest (`generator.version`, `provenance.implementation`) and the input
  fingerprint. Replaying a plan with a different generator version is
  rejected.

Platform note: trigonometric and logarithm functions come from the platform's
C library and may differ in the last bit between operating systems. Rounding
to 0.1 mm absorbs this in practice; the golden tests compare floats with a
1e-3 tolerance so that such a difference would not fail CI spuriously.

## Manifest format

| Field | Content |
| --- | --- |
| `manifest_version` | `"1.0"` |
| `generator` | `{name, version}` |
| `coordinate_system` | the conventions above, as constants |
| `source` | blueprint id and name, recipe id, overrides id, registry id, master seed, `generator_seeds`, `input_fingerprint` |
| `extent` | `{width_m, depth_m}` |
| `terrain` | heightfield (`cell_size_m`, `columns`, `rows`, `heights`, min/max, `ground_cover`) or `null` when disabled |
| `atmosphere` | `AtmosphereSettings` or `null` when disabled |
| `entities` | sorted by `id` |
| `statistics` | counts by category and generator, placeholder count |
| `content_hash` | `sha256:<hex>` |

The file is pretty-printed with short numeric arrays (points, colours,
heightfield rows) on one line, which keeps diffs readable.
