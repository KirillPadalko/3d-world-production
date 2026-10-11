# dacha-forest-edge

Reference location package for LocationBlueprint v1.0: a small, synthetic
Russian dacha settlement on a gravel road at the edge of a mixed forest. It is
hand-authored for tests and documentation and is not derived from footage, so
all entities carry `manual` provenance and `source.type` is `synthetic`.

| File | Content |
| --- | --- |
| `location.blueprint.json` | the blueprint (canonical form; `envgen blueprint format --check` passes) |
| `terrain/heightmap.r16` | 65 x 65 `raw_u16_le`, rows south to north, `elevation = 140.0 + value * 0.001` m |
| `terrain/wetness.u8` | 33 x 33 `raw_u8` ground-wetness mask (`value / 255`), wet around the pond |

Both rasters are corner-aligned over the 160 m x 120 m bounds. They were
computed from these formulas (x east, z north, metres):

```text
smoothstep(t) = t*t*(3 - 2t) for t clamped to [0, 1]
height(x, z)  = 141 + 5 * smoothstep((z - 30) / 90)
              + 0.5 * sin(x / 23) * cos(z / 17)
              - 1.6 * exp(-((x - 20)^2 + (z - 100)^2) / 72)
value         = round((height - 140.0) / 0.001)
wetness(x, z) = round(255 * max(0, 1 - distance((x, z), (20, 100)) / 22))
```

The recipe `examples/recipes/dacha-overgrown.recipe.json` and the overrides
`examples/overrides/dacha-forest-edge.designer-pass.overrides.json` belong to
this location but are separate documents. See
[docs/LOCATION_BLUEPRINT.md](../../../docs/LOCATION_BLUEPRINT.md#the-dacha-fixture).
