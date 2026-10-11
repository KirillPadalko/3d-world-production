# Generation pipeline

## Stages

| # | Stage (`name`) | Class | Input | Output | Fails with |
| --- | --- | --- | --- | --- | --- |
| 1 | `load_inputs` | `LoadInputsStage` | `InputBundle` (paths or parsed JSON) | `LoadedInputs` | `InputLoadError`, `UnsupportedVersionError`, `MigrationError`, `ContractValidationError`, `SemanticValidationError` |
| 2 | `resolve_inputs` | `ResolveInputsStage` | `LoadedInputs` | `ResolvedInputs` | `OverrideError`, `ExternalDataError` |
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
  (the generator's site description including measured heights, the effective
  recipe, controls, filtered archetypes, seeds, placement overrides and
  annotations; floats are written exactly), and replaying it yields the same
  manifest as the direct run.

### 1. Load inputs

The blueprint is validated with every phase of the
[LocationBlueprint contract](LOCATION_BLUEPRINT.md#validation-and-diagnostics)
(version, schema, semantic, reference, external files resolved against the
*package root*: `InputBundle.package_root`, default the blueprint file's
folder). An unsupported or migratable version stops here
(`UnsupportedVersionError` / `MigrationError`). Recipe, overrides and registry
are validated against their models (camelCase keys only). All contract
violations of all documents are collected before failing, each with a
`location` (document) and `path` (`buildings[3].transform.yawDeg`). Missing
recipe -> built-in default recipe; missing registry -> built-in registry. Then
recipe, registry and compatibility checks run (recipe `appliesTo` globs on
`locationId`, overrides `locationId` / `recipeId`). Content fingerprints of
every input, including the referenced heightmap and mask files, are computed.

### 2. Resolve overrides, seeds, controls and the site view

In order:

1. Entity operations of the overrides (`update`, `replaceArchetype`,
   `delete`, `add`) are applied to a copy of the blueprint and the result is
   validated completely again (see
   [Recipe and overrides](LOCATION_BLUEPRINT.md#recipe-and-overrides)).
   Conflicts fail or are reported according to `conflictPolicy`; the input
   blueprint is never modified. Which operations shaped which entity is kept
   (`override_trace`) and later written to the entities' provenance.
2. The master seed is chosen: `--seed` / `seed_override` > `recipe.seed` >
   `blueprint.generation.masterSeed`. Explicit subsystem seeds are merged
   (recipe over blueprint).
3. Generation controls are resolved: `structuralSimilarity`,
   `visualVariation` (recipe, else blueprint `generation`), `detailDensity`
   (recipe) and `abandonment` (recipe, else blueprint `atmosphere`).
4. The blueprint is converted into the generator's internal **site
   description** (`blueprint/site_adapter.py`): positions and headings are
   converted to the generator frame, road curves are sampled
   (2 m), the heightmap is decoded, fence missing sections become gaps in
   metres, wires attach to their poles. Entities whose provenance confidence
   is below `recipe.filters.minConfidence` are dropped (reported as info).
   Data the built-in generators do not use yet (surface and slope zones,
   masks, garden beds) is listed as `NOT_INTERPRETED` info; landmarks and
   gameplay annotations are passed through to the manifest.

Placement overrides are carried forward to stage 5.

### 3. Resolve asset archetypes

The registry is filtered to a **palette**: archetypes that carry all
`requiredTags`, none of the `excludedTags`, match one of the
`allowedArchetypes` globs (when given), and support the location's biome
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
naming the generator. Finally the entity-operation trace is copied to the
affected entities' provenance, placement overrides are applied (converted from
the location frame) and entities are sorted by ID. The internal scene uses the
generator frame; the exporter converts it.

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

Public documents - blueprint, overrides and the scene manifest - share the
**location frame** defined in
[LOCATION_BLUEPRINT.md](LOCATION_BLUEPRINT.md#spatial-conventions):

| Aspect | Convention |
| --- | --- |
| Units | metres, degrees |
| Axes | left-handed, **+X east, +Y up, +Z north** (Unity's axes) |
| Origin | south-west corner of the bounds; the playable area is `[0, widthM] x [0, depthM]` |
| Rotation | `rotationDeg = [x, y, z]`, applied Z, then X, then Y (extrinsic; `Quaternion.Euler`); `y` is the yaw, clockwise from north seen from above |
| Object frame | local +X = width, local +Y = up, local +Z = depth and **front**; at yaw 0 the front faces north |
| Scale | `[width, height, depth]` factors |
| Dimensions | `widthM`, `depthM`, `heightM` world sizes after scaling |
| Geometry | `geometry.points` are world `[x, y, z]` points |
| Heightfield | `heights[row][column]`; row 0 is the southern edge (`z = 0`), column 0 the western edge; `origin` is `[x, z]`; sample spacing `cellSizeM`; bilinear interpolation between samples |
| Key light | `keyLightDirection` is a unit vector in the location frame pointing from the light into the scene; `keyLightAzimuthDeg` and `windDirectionDeg` are compass bearings |

Internally the generators work in a Z-up frame (+X east, +Y north, +Z up,
counter-clockwise yaw, front = local +Y). `core/frames.py` holds the only
conversion (`(x, y, z) <-> (x, z, y)`, `yaw -> -yaw`); the site adapter
converts inputs and the exporter converts outputs. The current generators
only produce yaw rotations; the exporter refuses anything else rather than
guess.

## Entities

```jsonc
{
  "id": "building.b-house-02",              // stable, see table below
  "category": "building",                   // terrain|water|road|building|fence|infrastructure|vegetation|prop
  "kind": "house",                          // blueprint type or generator-chosen kind
  "archetypeId": "building.dacha.wooden_house_small",
  "assetRef": "envgen://building/dacha/wooden_house_small",
  "variant": 0,                             // < archetype.variants
  "placeholder": false,
  "transform": { "position": [62.0, 142.0853, 63.0], "rotationDeg": [0.0, 180.0, 0.0], "scale": [1.0, 1.0, 1.0] },
  "dimensions": { "widthM": 6.0, "depthM": 5.0, "heightM": 5.5 },   // world size after scaling
  "geometry": null,                         // polyline/polygon for roads, cables, water
  "parameters": {
    "abandonment": 0.6, "condition": "damaged", "conditionScore": 0.4, "cover": "full",
    "doors": "closed", "floors": 1, "foundationM": 0.5182, "heightM": 5.5, "plotId": "plot-02",
    "roof": "gable", "roofType": "gable", "wallMaterial": "wood_board", "windows": "boarded"
  },
  "tags": ["damaged"],
  "provenance": {
    "generator": "buildings",
    "implementation": "footprint_buildings@1.1.0",
    "rule": "explicit_footprint",
    "sourceFeature": "buildings/b-house-02",
    "overrides": ["dacha-designer-pass-01#entityOperations[0]"]
  }
}
```

`parameters` combine generator values (`condition`: `intact|damaged|ruined`,
`cover`: `none|partial|half|full` copied from the archetype, `floors`,
`foundationM`, ...) and blueprint values passed through unchanged
(`conditionScore`, `abandonment`, `windows`, `doors`, `roofType`,
`wallMaterial`, `plotId`, `heightM`, `species`, `parentId`, ...). On a key
collision the blueprint value wins. The archetype keeps its designed height
and only the footprint is scaled to fit.

### Entity IDs

| Entity | ID |
| --- | --- |
| Terrain | `terrain` |
| Water body | `water.<waterBody>` |
| Road segment | `road.<segment>` |
| Road junction | `road.junction.<segmentA>.<segmentB>.<n>` |
| Blueprint building | `building.<building>` |
| Infill building | `building.fill.<plot>.<segment>.<l\|r><nnn>` |
| Fence panel | `fence.<fence>.e<edge>p<panel>` |
| Infrastructure point (pole, well, light, ...) | `infrastructure.<point>` |
| Wire between blueprint poles | `infrastructure.<wire>` |
| Street light | `infrastructure.street_light.<segment>.<l\|r><nnn>` |
| Scattered plant | `vegetation.<zone>.<candidate:05d>` |
| Orchard tree | `vegetation.<zone>.r<row>c<column>` |
| Blueprint tree | `vegetation.<tree>` |
| Blueprint prop | `prop.<prop>` |
| Clutter prop | `prop.clutter.<building>.<nn>` |

IDs depend only on blueprint entity IDs and local indices. A scattered plant keeps its
ID and position when other candidates are blocked or freed, because every
candidate draws from its own random stream.

### Provenance

`generator` and `implementation` name the code that created the entity,
`rule` the placement rule (`explicit_footprint`, `zone_infill`,
`area_scatter`, `orchard_grid`, `line_planting`, `panel`, `line_pole`,
`line_cable`, `street_light_spacing`, `building_clutter`, `junction`,
`centerline`, `water_surface`, `heightfield`, `explicit_point`),
`sourceFeature` the blueprint entity (`collection/id`) and `overrides` every
override that shaped the entity: entity operations on its source
(`<overrides-id>#entityOperations[<i>]`) and placement overrides on the entity
itself (`<overrides-id>#placementOverrides[<i>]`).

## Generators

* **Terrain (`heightfield@1.1.0`)** - grid with `cellSizeM` spacing covering
  the bounds. With a blueprint heightmap the grid samples the measured heights
  (bilinear) and adds no noise. Otherwise the base is the middle of
  `terrain.elevation` and fractal value noise (`noiseAmplitudeM`, default from
  the elevation span: flat 0, gentle 1.5, hilly 6, rugged 14 m) adds relief.
  Each water body becomes a flat surface at its lowest shoreline height; the
  terrain beneath is carved `waterDepthM` deeper.
* **Roads (`polyline_roads@1.1.0`)** - one entity per road segment with a
  terrain-following centre line sampled from the segment curve (polyline or
  centripetal Catmull-Rom through the node positions and control points) and
  the blueprint width (times `widthScale`). The road kind used for asset
  selection follows `importance` and `surface`. Junctions are detected
  between all segment pairs and merged when close.
* **Buildings (`footprint_buildings@1.1.0`)** - blueprint buildings are placed
  exactly at their transform, with their yaw (the front faces the stated
  direction) and dimensions; the archetype is requested by the building's
  semantic archetype name first, then its type, and chosen by footprint fit,
  floors, roof and condition (`condition >= 0.6` intact, `>= 0.25` damaged,
  else ruined). `damageRatio` / `ruinFraction` deterministically degrade
  intact buildings. Zone infill (when enabled) fills `vacant_lot` plots: lots
  every `lotSpacingM` along each road, kept with the plot density, a weighted
  random building type facing the road if it lies fully inside the plot and
  keeps `spacingM` from roads, buildings, water, fences and point features.
* **Fences (`panel_fences@1.1.0`)** - each path edge is split into equal
  panels no longer than the archetype panel; missing sections are cut exactly;
  with `gapAtRoads` panels crossing a road are left out. The blueprint height
  is used (times `heightScale`).
* **Infrastructure (`standard_infrastructure@1.1.0`)** - blueprint points
  (poles, lights, wells, signs, containers, ...) are placed as given; a wire
  becomes one cable entity through the tops of its blueprint poles (no poles
  are invented; `supportEntityIds` lists them). Lines without blueprint poles
  (internal use) get poles at most `poleSpacingM` apart. Street lights are
  placed every `spacingM` beside roads whose importance is listed in
  `streetLights.roadImportance`, facing the road, skipping blocked spots.
* **Vegetation (`scatter_vegetation@1.1.0`)** - zones: dart throwing with a
  target of `area/100 x rate x density x densityScale x detailDensity`
  (rate per 100 m^2: forest 4, woodland 1.6, scrub 5, meadow 3), kind-dependent
  spacing and clearance from roads, buildings, water, fences and
  infrastructure. Each candidate draws a species from the zone's species
  weights (the species is requested as an archetype kind first, then the
  generic kind; `unknown` species use generic plants); `understoryDensity`
  sets the share of bushes. Orchards are jittered grids. Individual trees are
  always placed. The entity `kind` is the plant form (`tree`, `bush`, ...) and
  `parameters.species` the species.
* **Props (`clutter_props@1.1.0`)** - blueprint props as given; clutter around
  every building (`perBuilding x detailDensity` on average, kinds from a
  per-building-type table or `kindWeights`), placed beside the walls,
  aligned to the building, avoiding everything already placed.
* **Atmosphere (`preset_atmosphere@1.1.0`)** - for each of time of day,
  weather and season the recipe wins, then the blueprint, then afternoon /
  clear / summer. Presets give key light elevation, azimuth, colour and
  intensity, ambient light, fog (raised to the blueprint `fogDensity`), clouds,
  precipitation (rain turns to snow in winter), wind and foliage state. The
  azimuth is mirrored for the southern hemisphere and rotated by the geo
  reference heading. Ground wetness, saturation, contrast, vegetation
  condition, palette and the resolved abandonment are passed through.

### Asset resolution

`PaletteAssetResolver.resolve(request)`:

1. If the first requested kind is the ID of a palette archetype of that
   category (a blueprint `archetype` may name a registry ID), that archetype
   is used. Otherwise candidates are palette archetypes of the requested
   category supporting the first requested kind that any archetype supports
   (later kinds are fallbacks, e.g. `("wooden_house_small", "house")` or
   `("birch", "tree")`).
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

**Guarantee:** the same blueprint (including its external files), recipe,
overrides, registry, generator version and seeds produce a byte-identical
`scene-manifest.json` (and, with
`--no-timings`, `generation-report.json`) in any process, independent of
`PYTHONHASHSEED`, input file formatting or key order. This is covered by
`tests/integration/test_determinism.py`, which also runs the CLI in separate
processes with different hash seeds.

How:

* **Seeds.** `derive_seed(base, *labels)` = first 8 bytes (big-endian) of
  `SHA-256("base\x1flabel1\x1flabel2...")`, masked to 63 bits.
  * master seed: `--seed` > `recipe.seed` > `blueprint.generation.masterSeed`;
  * generator task seed: the explicit subsystem seed (recipe `subsystemSeeds`
    over blueprint `generation.subsystemSeeds`), else
    `derive_seed(master, "generator", <slot>)`; the plan records the seed
    and its source (`derived`, `blueprint`, `recipe`), the manifest lists
    them in `source.generatorSeeds`;
  * per feature / candidate streams: `derive_seed(task_seed, <labels...>)`,
    e.g. `("scatter", "vz-forest-north", 42)`;
  * asset choices: the `assets` subsystem seed, else
    `derive_seed(master, "assets")`, then per entity ID.
* **PRNG.** xoshiro256**, state initialised with four SplitMix64 outputs of
  the seed; `random()` = `(next_u64 >> 11) * 2^-53`. Reference values are
  pinned in `tests/unit/test_core_primitives.py`.
* **Ordering.** Features are processed sorted by ID, generators in plan
  order, spatial queries return insertion order, entities are sorted by ID,
  set iteration is never used for output.
* **Serialisation.** Manifest floats are rounded to 4 decimals (0.1 mm),
  `-0.0` becomes `0.0`. `contentHash` is the SHA-256 of the canonical JSON
  (sorted keys, compact) of the manifest without the `contentHash` field;
  `envgen verify` recomputes it. Plans and blueprints keep floats exactly.
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

All keys are camelCase.

| Field | Content |
| --- | --- |
| `manifestVersion` | `"1.0"` |
| `generator` | `{name, version}` |
| `coordinateSystem` | the location-frame conventions above, as constants (`upAxis: "+y"`, `northAxis: "+z"`, `handedness: "left"`, `rotationOrder: "zxy"`, `forwardAxis: "+z"`, ...) |
| `source` | `locationId`, `locationName`, `recipeId`, `overridesId`, `registryId`, master `seed`, `generatorSeeds`, resolved `controls` and `inputFingerprint` |
| `extent` | `{widthM, depthM}` |
| `terrain` | heightfield (`origin`, `cellSizeM`, `columns`, `rows`, `heights`, min/max, `groundCover`) or `null` when disabled |
| `atmosphere` | `AtmosphereSettings` or `null` when disabled |
| `entities` | sorted by `id` |
| `annotations` | blueprint `landmarks` and `gameplay`, unchanged |
| `statistics` | counts by category and generator, placeholder count |
| `contentHash` | `sha256:<hex>` |

The file is pretty-printed with short numeric arrays (points, colours,
heightfield rows) on one line, which keeps diffs readable.
