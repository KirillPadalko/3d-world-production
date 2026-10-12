# Environment Generator Importer (Unity)

Imports a `scene-manifest.json` produced by the Environment Generator
(`envgen generate`) into a Unity scene:

* **Terrain** from the manifest heightfield (saved as a `TerrainData` asset), with a
  terrain layer chosen by ground cover.
* **Objects** (buildings, fence panels, poles, trees, props) as your prefabs, bound by
  archetype in a **Prefab Registry**; unbound archetypes become placeholder boxes of the
  right size, so a location is usable before any art exists.
* **Generated meshes** for roads (ribbons), junctions (discs) and water (polygons), and
  sagging **cables** between poles.
* **Lighting and fog** (sun direction, colours, ambient, exponential fog).
* **Landmarks and gameplay annotations** (navigation, cover with separate
  movement / projectile / vision effects, combat zones, spawn clearances, sight
  lines) as marker objects with gizmos.

Requires Unity 2021.3 or newer. It depends on `com.unity.nuget.newtonsoft-json`,
which the Package Manager installs automatically.

## Install

Package Manager > **+** > *Add package from git URL*:

```text
https://github.com/KirillPadalko/3d-world-production.git?path=/integrations/unity/com.environment-generator.importer
```

or, with a local clone, *Add package from disk* and pick this folder's `package.json`.

## Use

1. Generate a manifest: `uv run envgen generate -b <location>/location.blueprint.json -r <recipe> -d out/<location>`.
2. In Unity: **Tools > Environment Generator > Create Prefab Registry** (optional, but
   without it everything is a placeholder).
3. **Tools > Environment Generator > Import Scene Manifest...**: choose
   `out/<location>/scene-manifest.json` and the registry, then **Check manifest**,
   **Add missing bindings to registry** (creates one empty entry per archetype the
   manifest uses), drag your prefabs into the registry, and **Import into the active
   scene**.

Re-run the import after regenerating: objects are matched by their stable entity
ID (`building.b-house-02`), their transform and the child named `visual` are
rebuilt, entities that disappeared are removed, and anything else you added to an
entity object is kept. Everything is one undo step.

### Coordinates

The manifest uses Unity's axes: metres, +X east, +Y up, +Z north, rotations as
`Quaternion.Euler(rotationDeg)`. Nothing is swapped or negated. Everything sits
under the root object `EnvGen <locationId>` with the location's south-west corner at
the root's origin; move the root to place the location in a larger world (Unity
terrains cannot be rotated, so keep the root unrotated).

### Prefab registry

Lookup order for an object: its exact `archetypeId`
(`building.dacha.wooden_house_small`), then `category` + `kind` (`building` / `house`),
else a placeholder. Several prefabs in one binding are variants; the manifest
`variant` picks one deterministically. Per binding, **fit** decides the size:

| Fit | Use for |
| --- | --- |
| `FitDimensions` (default) | buildings, fences, crates: each axis is scaled to the entity's width / height / depth and the bounds' bottom centre is put on the entity position, whatever the prefab's pivot |
| `FitHeightUniform` | trees, people-sized props: proportions kept, height matched |
| `ManifestScale` | prefabs modelled exactly at the registry archetype size with the pivot at the bottom centre and the front facing +Z |

Materials for generated meshes are bound by `archetypeId` or `category/kind`
(`road/dirt_track`, `water/pond`), with defaults for roads, water and cables. Terrain
layers are bound by ground cover (`grass`, `dirt`, ...).

### What you get

```text
EnvGen dacha-forest-edge          EnvGenSceneRoot (location, recipe, seed, content hash)
  Terrain                         Terrain + TerrainCollider
  Sun                             directional light
  Entities/building/building.b-house-02    EnvGenEntity (id, archetype, parameters, provenance)
    visual                        your prefab, fitted
  Entities/road/road.s-lane       generated road mesh (+ MeshCollider)
  Annotations/Landmarks/lm-old-oak         EnvGenLandmark
  Annotations/Gameplay/cz-fence-04         EnvGenGameplayArea (movement block, projectiles none, vision full)
```

`EnvGenEntity.parameters` keeps every manifest parameter (`conditionScore`,
`abandonment`, `windows`, `wallMaterial`, `cover`, ...) for gameplay code;
`EnvGenEntity.overrides` lists the designer overrides that shaped the entity.

The importer recomputes the manifest's `contentHash` exactly as the generator does
and warns when the file was edited after generation (or refuses, with *Require valid
content hash*).

## Automation and Unity MCP

Command line (Unity closed):

```bash
Unity -batchmode -quit -projectPath <project> \
  -executeMethod EnvGen.Importer.Editor.BatchImport.Run \
  -envgenManifest /path/to/scene-manifest.json \
  -envgenRegistry Assets/EnvGenPrefabRegistry.asset \
  -envgenScene Assets/Scenes/Dacha.unity
```

From an editor script or a Unity MCP tool that executes C# in the editor:

```csharp
string summary = EnvGen.Importer.Editor.BatchImport.ImportIntoScene(
    "/path/to/scene-manifest.json",
    "Assets/EnvGenPrefabRegistry.asset",   // or null for placeholders
    "Assets/Scenes/Dacha.unity");          // or null for the active scene (not saved)
```

or `EnvGen.Importer.Editor.ManifestSceneImporter.Import(path, registry, settings)` for
the full `ImportReport` (created / updated / removed counts, placeholders, unbound
archetypes, warnings). A Unity MCP server that can only run menu items can open the
window via **Tools/Environment Generator/Import Scene Manifest...**.

## Development

The engine-free part (`Runtime/Core`: manifest model and reader, content hash,
terrain resampling, mesh builders, prefab lookup, re-import planning) is unit-tested
with .NET outside Unity:

```bash
dotnet test integrations/unity/tests/EnvGen.Importer.Core.Tests
```

These tests include the content hash of every committed example manifest. After
adding or moving files in this package, run
`uv run python scripts/unity_package_meta.py` to create their `.meta` files.
