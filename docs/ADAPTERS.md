# Adapters and integration

## Principles

* The core (`core`, `models`, `blueprint`, `validation`, `assets`, `generators`,
  `planning`, `pipeline`, `exporters`, `reporting`) never imports engine,
  DCC, network, MCP or AI SDKs. A test enforces this.
* Every external system sits behind an interface in
  `src/environment_generator/adapters/`.
* An adapter is either **local** (works today, no external system) or a
  **stub** (interface only). Stubs raise `AdapterUnavailableError`
  (exit code 7) with a pointer to this document. Nothing simulates success.
* Future adapters that need third-party packages import them lazily inside
  the adapter module and declare them as an optional dependency group, so the
  core stays installable with `pydantic` only.
* No credentials are needed or stored. Future configuration goes through
  environment variables (see `.env.example`), never through committed files.

`envgen adapters list` prints the current status:

| Adapter | Status | Interface | Workflow step |
| --- | --- | --- | --- |
| `location-analysis` | stub | `adapters.LocationAnalyzer` | drone footage -> LocationBlueprint |
| `asset-registry-json` | local | `assets.AssetResolver` | asset selection |
| `scene-manifest-json` | local | `exporters.SceneExporter` | portable scene export |
| `blender` | stub | `adapters.BlenderProcessor` | Blender processing |
| `unity` | stub (+ real coordinate helpers) | `adapters.UnitySceneIntegrator` | Unity scene integration |

## Location analysis (footage -> blueprint)

```python
class LocationAnalyzer(ABC):
    def analyze(self, footage: Sequence[FootageReference]) -> LocationBlueprint: ...
```

A real implementation (photogrammetry, segmentation, a remote service or an
MCP tool) must write a location package whose blueprint passes
`envgen blueprint validate` (the full
[LocationBlueprint v1.0 contract](LOCATION_BLUEPRINT.md)). Guidance for
producers:

* Use the location frame: metres, `+X` east, `+Y` up, `+Z` north, origin at
  the south-west corner of the area to play, yaw clockwise from north. Keep
  entities inside the bounds (partially outside is a warning, fully outside an
  error).
* Assign every entity a stable ID once and keep it across re-analyses of the
  same site (renames go to `previousIds`); designer overrides and
  engine-side references key on them.
* Record provenance honestly: `observed` vs `inferred` (with `confidence`,
  `method`, `positionAccuracyM`, and the frames and observations that support
  it), `procedural` for tool-added content. Describe the footage, frame
  extraction, analysis reports and calibration in `source`; never invent
  references. Recipes can ignore weak detections with
  `filters.minConfidence`.
* Write measured terrain as an external heightmap (`raw_u16_le` or
  `raw_f32_le`, corner-aligned) with `sha256` and `sizeBytes`; never put large
  arrays into the JSON.
* Give buildings a transform (footprint centre, yaw of the front), dimensions,
  and optionally the traced `footprint`; use `unknown` where a value cannot
  be determined (species, materials, opening states).

## Asset registry (archetypes -> engine assets)

The built-in registry (`src/environment_generator/assets/data/builtin-registry.json`,
118 archetypes, including wooden dacha houses, a bathhouse, sheds, a metal
garage and plant species such as birch, aspen, lilac and nettle) uses logical
keys such as `envgen://building/dacha/wooden_house_small`. Blueprint
`archetype` names (`wooden_house_small`) are matched against archetype
`kinds`; a blueprint may also name a registry ID directly. An engine
integration has two options:

1. **Keep the archetype IDs, map `assetRef` on the engine side** - e.g. a
   Unity ScriptableObject table `archetypeId -> prefab`. Nothing changes in
   the generator.
2. **Ship an engine registry** - a JSON file with the same schema
   (`schemas/asset-registry.schema.json`) whose `assetRef` values are prefab
   paths or Addressables keys and whose `dimensions` are the real prefab
   bounds. Use it with `--registry` or `ENVGEN_ASSET_REGISTRY`. Prefab paths
   belong here, never in a blueprint.

Archetype rules: IDs are dotted lower-case (`category.family.name`);
`dimensions` are width (side to side), depth (front to back) and height, with
`width >= depth` for buildings; `variants` is the number of interchangeable
models; `cover` is a tactical hint; `scalable: false` keeps vehicles and
similar props at their modelled size.

## Coordinate conversion

The manifest uses the location frame of the blueprint, which is Unity's own
frame: metres, left-handed, `+X` east, `+Y` up, `+Z` north (forward), yaw =
rotation about `+Y` in degrees clockwise seen from above, an object's front is
local `+Z`, and `rotationDeg` is applied Z, then X, then Y (extrinsic), exactly
like `Quaternion.Euler`.

| Quantity | Manifest | Unity |
| --- | --- | --- |
| Position | `[x, y, z]` | `new Vector3(x, y, z)` |
| Scale | `[sx, sy, sz]` (width, height, depth) | `new Vector3(sx, sy, sz)` |
| Rotation | `rotationDeg = [rx, ry, rz]` (all current entities: `[0, yaw, 0]`) | `Quaternion.Euler(rx, ry, rz)` |
| Direction vector | `[dx, dy, dz]` | `new Vector3(dx, dy, dz)` |

No component is swapped or negated. To orient the location in a larger
world, parent the imported objects under one root transform. The Python
reference (`adapters/unity.py`: `to_unity_position`, `to_unity_scale`,
`to_unity_yaw`, `to_unity_rotation`, `entity_to_unity_transform`) is tested
against `Quaternion.Euler` semantics (a yaw of 90 turns the front from north to
east; general rotations apply Z, then X, then Y).

```csharp
// Minimal C# port for a Unity importer.
static Vector3 ToUnity(float[] v) => new Vector3(v[0], v[1], v[2]);
static Quaternion ToUnityRotation(float[] r) => Quaternion.Euler(r[0], r[1], r[2]);
```

For Z-up tools (Blender) use `(x, z, y)` for positions and scales and a
rotation of `-yaw` about `+Z`.

## Unity integration guide (for the future importer)

The importer is a Unity-side (C#) editor tool that reads
`scene-manifest.json`. Suggested approach:

1. **Validate first.** Run `envgen verify scene-manifest.json` in the build
   pipeline (or recompute the hash: SHA-256 of the compact, key-sorted JSON
   without `contentHash`, floats as written). Check `manifestVersion` and
   `coordinateSystem` before importing.
2. **Terrain.** Create a `TerrainData` with `size = (widthM, max - min,
   depthM)` placed at `(0, minElevationM, 0)`. Unity heightmaps need a
   `2^n + 1` resolution, so resample the manifest grid bilinearly;
   `heights[row][column]` maps to Unity `heights[z, x]` (rows run south to
   north = +Z), normalised to `(h - min) / (max - min)`. Pick the terrain
   layer from `terrain.groundCover` / the `terrain` entity's archetype.
3. **Entities.** Instantiate the prefab mapped from `archetypeId` (or
   `assetRef`), choose model `variant`, apply the transform as it is and
   name the GameObject after `id`. Because IDs are stable, re-imports can
   update existing objects instead of rebuilding the scene. For
   `placeholder: true` spawn a visible stand-in box sized by `dimensions`.
4. **Geometry entities.** Roads (`geometry.type = polyline`, `widthM`) become
   spline or ribbon meshes along world-space points; junction entities mark
   where to blend them. Water (`polygon`) becomes a flat mesh at the given
   height. Cables are line renderers through the pole tops
   (`parameters.supportEntityIds` names the poles).
5. **Fences and walls** are individual panels (transform at the panel centre,
   local X along the fence, `scale.x` stretched to the exact length), so they
   can be destroyed or used as cover individually.
6. **Atmosphere.** Point the directional light along `keyLightDirection`
   (`Quaternion.LookRotation`), use the colours and intensities as starting
   values, map `fogDensity` to exponential fog, `precipitation` / `wind*` to
   effects, and `groundWetness`, `saturation`, `contrast`, `palette` to
   materials and post-processing.
7. **Gameplay data.** `annotations.landmarks` and `annotations.gameplay`
   (navigation areas, cover zones with separate movement / projectile /
   vision effects, combat zones, spawn clearances, line-of-sight
   expectations) are copied from the blueprint in the same frame.
   `parameters.cover`, `parameters.condition`, `parameters.conditionScore`,
   `parameters.abandonment` and building `floors` are hints for the tactical
   layer. The engine owns the actual gameplay rules.
8. **Validate after import.** Compare instantiated counts with
   `statistics.byCategory`, and report missing prefab mappings.

## Blender processing

```python
class BlenderProcessor(ABC):
    def process(self, manifest: SceneManifest, output_dir: Path) -> BlenderProcessingResult: ...
```

Intended design: run Blender **out of process**
(`blender --background --python <script> -- scene-manifest.json <out>`), with
the script reading the manifest and producing processed meshes (road meshes,
merged static batches, baked terrain). The adapter only builds the command,
runs it and collects outputs, so `bpy` never enters this package. Blender is
right-handed and Z-up: convert positions and scales with `(x, z, y)` and
rotate by `-yaw` about `+Z` (see [Coordinate conversion](#coordinate-conversion)).

## MCP and AI services

None are used. If a later phase adds an MCP-based analysis tool or exposes
the generator as an MCP server, it belongs in a separate adapter module (or a
separate package depending on this one), imports its SDK lazily, reads
endpoints and keys from environment variables, and must still return
contract-valid documents. The generator itself stays a pure, offline
function of its inputs.
