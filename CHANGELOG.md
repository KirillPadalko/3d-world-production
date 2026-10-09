# Changelog

All notable changes are documented here. Versions follow
[Semantic Versioning](https://semver.org/); any change to generated output
bumps the version (see docs/DEVELOPMENT.md).

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
