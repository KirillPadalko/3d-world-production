# Changelog

All notable changes are documented here. Versions follow
[Semantic Versioning](https://semver.org/); any change to generated output
bumps the version (see docs/DEVELOPMENT.md).

## Unreleased

Generated output is unchanged (generator and package versions stay 0.2.0).

* Unity Editor importer package `com.environment-generator.importer`
  (`integrations/unity`): imports `scene-manifest.json` into a scene with a
  terrain asset, prefabs bound by archetype or category/kind in a prefab
  registry (placeholders of the right size otherwise, three fit modes),
  generated meshes for roads, junctions and water, sagging cables, sun and
  fog, and landmarks and gameplay annotations as marker objects with gizmos.
  Re-import matches entities by stable ID and is one undo step. Entry points
  for the editor window, `-batchmode` (`BatchImport.Run`) and Unity MCP
  (`BatchImport.ImportIntoScene`). The importer recomputes the content hash
  exactly as the generator does.
* The engine-free part of the importer (manifest reader, content hash,
  terrain resampling, mesh builders, prefab lookup, re-import planning) is
  unit-tested with .NET in CI; `scripts/unity_package_meta.py` creates and
  checks the package's `.meta` files.

## 0.2.0 - 2026-10-11

**LocationBlueprint contract v1.0** (`docs/LOCATION_BLUEPRINT.md`). The
unreleased 0.1 blueprint, recipe, overrides, registry and manifest formats are
replaced; there is no migration from them (they were never published).

* New LocationBlueprint v1.0: camelCase JSON, explicit coordinate system
  (metres, +X east, +Y up, +Z north, yaw clockwise from north), location
  packages with external heightmaps and masks (relative paths, size, SHA-256),
  road graph with centripetal Catmull-Rom curves, plots, buildings with
  condition and abandonment, vegetation zones with species weights, trees,
  fences with missing sections, infrastructure points and wires, props with
  parents, landmarks, gameplay annotations (movement, projectile cover and
  vision separated), atmosphere, generation controls and subsystem seeds,
  source provenance (media, frames, reports, calibration, observations) and
  per-entity provenance (`observed`, `inferred`, `manual`, `procedural`),
  namespaced extensions.
* Blueprint services (`environment_generator.blueprint`): version checks and
  a migration registry (future majors rejected, originals never overwritten
  without `--in-place`, backups), phased validation with structured
  diagnostics (code, severity, category, path, entity IDs, suggestion),
  document-wide ID namespace with `previousIds`, external file checks,
  canonical deterministic serialization.
* LocationOverrides v1.0: `update` (JSON merge patch), `replaceArchetype`,
  `delete`, `add`, placement overrides of generated entities; conflict policy
  `fail` / `report`; the blueprint is never modified; generated entities list
  the operations that shaped them.
* LocationRecipe v1.0: no geometry; `appliesTo` on `locationId`, optional
  seeds and controls falling back to the blueprint, `detailDensity`,
  `allowedArchetypes`, subsystem seeds.
* The scene manifest uses the blueprint's frame (Unity's axes) and camelCase;
  it carries resolved controls, landmarks and gameplay annotations. Unity
  conversion is now the identity.
* CLI: `envgen blueprint validate | format | migrate`, `--package-root`.
* Examples are location packages (`examples/locations/`), including the
  `dacha-forest-edge` reference fixture with its own recipe and overrides.
* Built-in registry: dacha archetypes (wooden houses, banya, greenhouse,
  outhouse, metal garage, sheds, metal-sheet fence, wooden well, signs,
  containers), plant species kinds and new prop kinds.
* Generators 1.1.0: measured heightmaps, road importance, blueprint yaw for
  buildings, species-weighted vegetation, supported wires, detail density,
  extended atmosphere. Requires pydantic >= 2.11.

## 0.1.0 - 2026-10-09

First standalone release.

* Public contracts (schema version 1.0): LocationBlueprint, LocationRecipe,
  LocationOverrides, asset registry and scene manifest, with JSON Schemas.
* Eight-stage pipeline (load, resolve, assets, plan, generate, validate,
  export, report) with dry run and replay from a saved plan.
* Built-in generators: heightfield terrain with water, polyline roads and
  junctions, footprint buildings with zone infill and damage, fence panels,
  pole lines and street lights, vegetation scatter/orchards/lines, building
  clutter, atmosphere presets.
* Deterministic xoshiro256** PRNG with hash-derived seeds, stable entity IDs,
  content-hashed manifests.
* `envgen` CLI, SVG preview, adapter interfaces (location analysis, Blender,
  Unity) as explicit stubs, Unity coordinate conversion helpers.
