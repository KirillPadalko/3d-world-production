# Adapters and integration

## Principles

* The core (`core`, `models`, `validation`, `assets`, `generators`,
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
MCP tool) must return a blueprint that validates against
`schemas/location-blueprint.schema.json` **and** passes `envgen validate`.
Guidance for producers:

* Use local metres with the origin at the south-west corner of the area you
  want to play; clip features to the extent (partially outside is a warning,
  fully outside is an error).
* Give every feature a stable ID across re-analyses of the same site; designer
  overrides and engine-side references key on them.
* Fill `confidence` (0-1) from the model's certainty; recipes can ignore weak
  detections with `filters.min_confidence`.
* Prefer polygons for traced building footprints; the generator fits the
  minimum-area rectangle. Spot heights (`terrain.elevation_points`) are
  honoured exactly.
* Record the producing tool in `source.analyzer` and the footage in
  `source.reference`.

## Asset registry (archetypes -> engine assets)

The built-in registry (`src/environment_generator/assets/data/builtin-registry.json`,
84 archetypes) uses logical keys such as
`envgen://building/house/small_gable`. An engine integration has two options:

1. **Keep the archetype IDs, map `asset_ref` on the engine side** - e.g. a
   Unity ScriptableObject table `archetype_id -> prefab`. Nothing changes in
   the generator.
2. **Ship an engine registry** - a JSON file with the same schema
   (`schemas/asset-registry.schema.json`) whose `asset_ref` values are prefab
   paths or Addressables keys and whose `dimensions` are the real prefab
   bounds. Use it with `--registry` or `ENVGEN_ASSET_REGISTRY`.

Archetype rules: IDs are dotted lower-case (`category.family.name`);
`dimensions` follow the object frame (front = local +Y, `width >= depth` for
buildings); `variants` is the number of interchangeable models; `cover` is a
tactical hint; `scalable: false` keeps vehicles and similar props at their
modelled size.

## Coordinate conversion

Manifest: right-handed, +X east, +Y north, +Z up; yaw counter-clockwise from
above; an object's front is local +Y. Unity: left-handed, +Y up, +Z forward.

| Quantity | Manifest | Unity |
| --- | --- | --- |
| Position | `(x, y, z)` | `new Vector3(x, z, y)` |
| Scale | `(sx, sy, sz)` | `new Vector3(sx, sz, sy)` |
| Yaw only (all current entities) | `rotation_deg = (0, 0, yaw)` | `Quaternion.Euler(0, -yaw, 0)` |
| General rotation | `(rx, ry, rz)`, extrinsic X-Y-Z | `AngleAxis(-rz, up) * AngleAxis(-ry, forward) * AngleAxis(-rx, right)` |
| Direction vector | `(dx, dy, dz)` | `new Vector3(dx, dz, dy)` |

Python reference implementations with tests live in `adapters/unity.py`
(`to_unity_position`, `to_unity_scale`, `to_unity_yaw`, `to_unity_rotation`,
`entity_to_unity_transform`). The tests check that an object's front points
the same way in both frames and that general rotations commute with the axis
swap.

```csharp
// Minimal C# port for a Unity importer.
static Vector3 ToUnity(float[] v) => new Vector3(v[0], v[2], v[1]);

static Quaternion ToUnityRotation(float[] r) =>
    Quaternion.AngleAxis(-r[2], Vector3.up) *
    Quaternion.AngleAxis(-r[1], Vector3.forward) *
    Quaternion.AngleAxis(-r[0], Vector3.right);
```

## Unity integration guide (for the future importer)

The importer is a Unity-side (C#) editor tool that reads
`scene-manifest.json`. Suggested approach:

1. **Validate first.** Run `envgen verify scene-manifest.json` in the build
   pipeline (or recompute the hash: SHA-256 of the compact, key-sorted JSON
   without `content_hash`, floats as written). Check `manifest_version` and
   `coordinate_system` before importing.
2. **Terrain.** Create a `TerrainData` with `size = (width_m, max - min,
   depth_m)` placed at `(0, min_elevation_m, 0)`. Unity heightmaps need a
   `2^n + 1` resolution, so resample the manifest grid bilinearly;
   `heights[row][column]` maps to Unity `heights[z, x]` (rows run south to
   north = +Z), normalised to `(h - min) / (max - min)`. Pick the terrain
   layer from `terrain.ground_cover` / the `terrain` entity's archetype.
3. **Entities.** Instantiate the prefab mapped from `archetype_id` (or
   `asset_ref`), choose model `variant`, apply the converted transform and
   name the GameObject after `id`. Because IDs are stable, re-imports can
   update existing objects instead of rebuilding the scene. For
   `placeholder: true` spawn a visible stand-in box sized by `dimensions`.
4. **Geometry entities.** Roads (`geometry.type = polyline`, `width_m`) become
   spline or ribbon meshes along world-space points; junction entities mark
   where to blend them. Water (`polygon`) becomes a flat mesh at the given
   height. Cables are line renderers through the pole tops; poles list
   neighbours in `parameters.connects_to`. Pipelines have a diameter in
   `width_m`.
5. **Fences and walls** are individual panels (transform at the panel centre,
   local X along the fence, `scale.x` stretched to the exact length), so they
   can be destroyed or used as cover individually.
6. **Atmosphere.** Point the directional light along
   `ToUnity(key_light_direction)` (`Quaternion.LookRotation`), use the colours
   and intensities as starting values, map `fog_density` to exponential fog
   and `precipitation` / `wind_*` to effects.
7. **Gameplay data.** `parameters.cover`, `parameters.condition` and
   building `floors` are hints for the tactical layer (cover, destructibility,
   line of sight). The engine owns the actual gameplay rules.
8. **Validate after import.** Compare instantiated counts with
   `statistics.by_category`, and report missing prefab mappings.

## Blender processing

```python
class BlenderProcessor(ABC):
    def process(self, manifest: SceneManifest, output_dir: Path) -> BlenderProcessingResult: ...
```

Intended design: run Blender **out of process**
(`blender --background --python <script> -- scene-manifest.json <out>`), with
the script reading the manifest and producing processed meshes (road meshes,
merged static batches, baked terrain). The adapter only builds the command,
runs it and collects outputs, so `bpy` never enters this package. The
Blender frame (right-handed, Z up) matches the manifest frame; no conversion
is needed.

## MCP and AI services

None are used. If a later phase adds an MCP-based analysis tool or exposes
the generator as an MCP server, it belongs in a separate adapter module (or a
separate package depending on this one), imports its SDK lazily, reads
endpoints and keys from environment variables, and must still return
contract-valid documents. The generator itself stays a pure, offline
function of its inputs.
