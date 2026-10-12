# Mapping footage to blueprint fields

The full field reference, defaults and vocabularies are in
`docs/LOCATION_BLUEPRINT.md#document-reference`; the dacha fixture
(`examples/locations/dacha-forest-edge/location.blueprint.json`) shows every
collection filled in. This page covers what to look for in footage and the
mistakes that are easy to make.

## IDs

One namespace for the whole document. Lower-case ASCII, digits, `-`, `_`;
at most 64 characters; readable and stable.

| Collection | Pattern | Example |
| --- | --- | --- |
| road nodes | `n-<what>` | `n-junction-main`, `n-north-exit` |
| road segments | `rd-<name>` | `rd-main-west`, `rd-lane-02` |
| plots | `plot-<nn>` | `plot-03` |
| buildings | `b-<type>-<nn>` | `b-house-03`, `b-banya-03` |
| fences | `f-<plot or place>-<side>` | `f-plot-03-street` |
| vegetation zones | `vz-<type>-<nn>` | `vz-forest-01`, `vz-yard-03` |
| trees | `t-<species>-<nn>` | `t-oak-01` |
| infrastructure | `pole-<nn>`, `wire-<nn>`, `well-<nn>`, `lamp-<nn>` | `pole-04` |
| props | `pr-<type>-<nn>` | `pr-car-wreck-01` |
| water, zones | `w-<type>-<nn>`, `sz-<surface>-<nn>`, `sl-<class>-<nn>` | `w-pond-01` |
| landmarks | `lm-<what>` | `lm-water-tower` |
| observations | `obs-<what>` | `obs-scale-overview` |

Number in a stable order (south to north, then west to east) once, and never
renumber later.

## Positions and elevation

* Horizontal geometry is `[x, z]`; point entities use
  `transform.position` `[x, y, z]`.
* `y` is the elevation. With `snapToTerrain` (the default) it is only
  advisory: write the terrain elevation if you know it, otherwise `0.0`, and
  leave `terrain.elevation` out unless you have real numbers.
* Polygons: points in order around the outline, the first point **not**
  repeated, no self-intersections.
* Everything inside `coordinateSystem.bounds`.

## Collections

### Roads

Look for: the carriageway (not the verges), junctions, where roads leave the
area, surface, ruts, potholes, grass in the middle.

* A **node** where roads meet (`junction`, three or more segments), end
  (`dead_end`), enter a plot (`entrance`) or cross the bounds (`boundary`,
  exactly on the edge).
* A **segment** between two nodes; a bend gets `curve.type: "catmull_rom"`
  with control points every 10-20 m along the centre line.
* `widthM` is the drivable width; `importance` is relative within the place
  (the main street is `primary` even if it is gravel).
* `condition` (0 destroyed - 1 good) and `vegetationIntrusion` (0 clear -
  1 overgrown) from what the frames show.

### Plots

The parcel outline, usually along its fences. `plotType`: `dacha_plot`,
`yard`, `garden`, `vacant_lot`, `common_area`. `condition` (upkeep) and
`abandonment` from beds, mown grass, paths, overgrowth. Dacha plots are often
regular: measure two or three well, then check the rest against them.

### Buildings

* `buildingType`, and `archetype` from the registry
  (`uv run envgen assets list --category building`: an ID or a kind such as
  `wooden_house_small`, `banya_small`, `metal_garage`). Without a good match,
  leave `archetype` out; the type decides.
* `transform.position`: footprint centre at ground level. `yawDeg`: the
  direction the entrance side faces (often the street).
* `dimensions`: `widthM` across the front, `depthM` front to back, `heightM`
  ground to ridge. Give `footprint` for L-shaped or rotated outlines.
* `floors` from window rows; `roofType`; `wallMaterial`; `openings`.
* `condition` (0 destroyed - 1 sound) and `abandonment` (0 lived in - 1
  abandoned) are independent; judge each from the frames.
* Attached sheds and verandas: part of the building unless clearly separate.

### Fences

`path` along the fence line, `closed: true` for a full ring (do not repeat
the first point). `fenceType` and `heightM` (see the reference table: sheet
fences 1.8-2 m, pickets 1-1.5 m). Gaps where it has fallen or is missing:
`missingSections` with fractions from `scale.py along`. `gameplay` hints only
if the user wants them.

### Vegetation

* **Zones** for areas: `zoneType`, `polygon`, `density` (canopy/plant cover
  0-1), `species` with relative weights (include `unknown` for what you cannot
  identify), `understoryDensity`, `grassDensity`, `heightRange`.
* **Trees** only for notable individuals: landmarks, large solitary trees,
  trees that give cover or block views. `heightM`, `crownDiameterM`,
  `condition` (0 dead).

### Infrastructure

Poles (`utility_pole`, `heightM`), lamps (`light`, `parentId` = the pole),
wells, signs, transformers, containers, water towers. **Wires** list the
`poleIds` in order along the line; count the wires and their direction at
each pole in a close frame. A wire's poles must exist as points.

### Props

Cars, wrecks, woodpiles, barrels, tyres, boats... Only what is visible and
matters at game scale (larger than about 0.5 m or tactically relevant).
`parentId` for things on a plot or against a building.

### Water and terrain

* `terrain.waterBodies`: ponds, ditches, streams (`polygon`; a stream is a
  narrow polygon).
* `terrain.defaultSurface` and `surfaceZones` (dirt yards, gravel areas);
  `slopeZones` with `averageSlopeDeg` and `aspectDeg` where the ground clearly
  slopes. The built-in generator keeps these for later consumers and derives
  relief from `terrain.elevation`.

### Landmarks

What a player would orient by: a water tower, a church, a large tree, a
crossroads, a gate. `linkedEntityId` to the building, tree or node it marks;
`visibility` and `visibilityRadiusM` from how far it is visible in the
footage. Distant landmarks may lie outside the bounds.

### Atmosphere and metadata

From the frames: `weather`, `timeOfDay` (shadows, light colour),
`groundWetness`, `vegetationCondition`, overall `abandonment`, `fogDensity`,
and a few `palette` colours (`#RRGGBB`) sampled by eye from typical surfaces
(roofs, grass, road). `metadata.season` and `metadata.biome` likewise.

### Gameplay

Only on request; always `manual`. Keep the three effects apart: a board fence
blocks movement and vision but stops no bullets.
