# Roadmap

## Phase 0 - standalone MVP (this release, 0.1.0)

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

* C# editor importer for `scene-manifest.json` following
  [ADAPTERS.md](ADAPTERS.md#unity-integration-guide-for-the-future-importer):
  terrain, prefab instantiation by archetype, road/water meshes, cables,
  lighting, incremental re-import by stable ID.
* An engine asset registry (real prefab bounds and keys) checked in alongside
  the game project.
* Import-side validation and a round-trip test scene.

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

## Known limitations

* Terrain generation is pure Python. The examples use about 4 000 samples and
  generate in a fraction of a second; a 1 km x 1 km map at 2 m cells
  (about 250 000 samples) takes roughly 3 s.
* Terrain is not flattened under roads or buildings; buildings sit on the
  lowest corner and report `foundation_m`.
* Water bodies must be polygons; rivers are not yet polylines.
* Overlapping explicit (surveyed) features are placed as given and reported
  by validation rather than repaired.
* Building heights come from the archetype; `floors` selects archetypes and is
  passed on, but does not scale models.
* Only yaw rotations are generated (no terrain-aligned tilt).
