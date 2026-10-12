# Roadmap

## Phase 0.2 - LocationBlueprint contract v1.0 (this release, 0.2.0)

* Engine-independent, versioned LocationBlueprint contract with typed models,
  JSON Schema, canonical serialization, structured diagnostics, external
  heightmaps and masks, provenance, stable IDs with rename aliases,
  migration framework and the dacha reference fixture.
* Recipe and overrides as separate contracts; overrides by stable ID with
  explicit conflict handling.
* One spatial frame (Y up, Z north, clockwise yaw) for blueprint, overrides
  and manifest.

## Phase 0 - standalone MVP (0.1.0)

* Public contracts for blueprint, recipe, overrides, asset registry and scene
  manifest, with generated JSON Schemas and drift checks.
* Contract, semantic and layout validation with structured issues.
* Eight-stage pipeline with dry run, replay from a saved plan and reports.
* Local generators for terrain, water, roads and junctions, buildings with
  zone infill and damage, fence panels, pole lines and street lights,
  vegetation scatter/orchards/lines, clutter props and atmosphere presets.
* Deterministic, portable PRNG and seed derivation; stable entity IDs;
  content-hashed manifests; golden tests.
* CLI, SVG preview, adapter interfaces with honest stubs, Unity coordinate
  helpers, CI on Python 3.11-3.13.

## Phase 1 - Unity integration

* Done: C# Editor importer package for `scene-manifest.json`
  (`integrations/unity`, see [ADAPTERS.md](ADAPTERS.md#unity-integration)):
  terrain, prefab registry with variants and fitting, placeholders, road,
  junction and water meshes, sagging cables, lighting and fog, landmarks and
  gameplay annotations, content-hash check, incremental re-import by stable ID,
  batch-mode and Unity MCP entry points.
* Next: compile and run the importer in a real Unity project in CI (Unity
  licence needed), a round-trip test scene, and a game-side prefab registry
  with real prefab bounds.

## Phase 2 - location analysis

* Frame extraction from drone footage, georeferencing and orthomosaic
  generation.
* Detection/segmentation of roads, building footprints, vegetation, water and
  fences into a `LocationBlueprint` with confidences, behind
  `LocationAnalyzer`.
* A review tool to compare analysis output with imagery and author overrides.

## Phase 3 - Blender processing

* Out-of-process `BlenderProcessor` that builds road meshes, bakes terrain and
  batches static geometry from the manifest.

## Generation improvements (any phase)

* Terrain flattening under roads and building foundations; road banks and
  ditches.
* Rivers and streams as polylines with width; bridges where roads cross water.
* Proper road meshes with intersections instead of junction markers; road
  markings and kerbs by road kind.
* Multi-part buildings from complex footprints; attached structures (porches,
  annexes); interiors for enterable buildings.
* Tactical layer: navigation grid, cover map and line-of-sight hints derived
  from the manifest; tile-based snapping for grid-based tactics.
* Larger maps: chunked generation and tiled manifests; optional NumPy
  acceleration for terrain (kept out of the core dependency set).
* More biomes, seasonal vegetation variants, and recipe presets.

## Next step for the contract

* Generators that use the remaining blueprint data: surface zones and terrain
  masks for ground materials, slope zones, plot boundaries for yard
  vegetation, `structuralSimilarity` / `visualVariation` as real controls,
  abandonment-driven decay of vegetation and props, gameplay annotations
  checked against the generated layout (cover zones, line of sight,
  connectivity).
* A first `LocationAnalyzer` producing v1.0 packages with observed provenance
  and frame references.

## Known limitations

* Terrain generation is pure Python. The examples use about 4 000 samples and
  generate in a fraction of a second; a 1 km x 1 km map at 2 m cells
  (about 250 000 samples) takes roughly 3 s.
* Terrain is not flattened under roads or buildings; buildings sit on the
  lowest corner and report `foundation_m`.
* Water bodies must be polygons; rivers are not yet polylines.
* Blueprint surface zones, slope zones, terrain masks and garden beds are
  validated and kept but not yet used by the built-in generators (reported as
  `NOT_INTERPRETED`). `structuralSimilarity` and `visualVariation` are
  recorded, not yet applied.
* Blueprint data is converted to an internal site description; a few values
  are coarsened for archetype selection (building condition to
  intact/damaged/ruined, wall materials to six families), while the exact
  blueprint values are passed through in entity `parameters`.
* Overlapping explicit (surveyed) features are placed as given and reported
  by validation rather than repaired.
* Building heights come from the archetype; the blueprint `heightM` and
  `floors` select archetypes and are passed on, but do not scale models.
* Only yaw rotations are generated (no terrain-aligned tilt).
