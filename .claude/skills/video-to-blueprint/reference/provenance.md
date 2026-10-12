# Provenance: saying where every fact came from

The contract is in `docs/LOCATION_BLUEPRINT.md#provenance-and-confidence`.
This page is how to apply it to footage.

## Categories

| Category | Use for | Must have |
| --- | --- | --- |
| `observed` | seen in the frames: the thing and its rough geometry are visible | `confidence`, `frameIds` (1-3 best frames) or `observationIds`, `positionAccuracyM` |
| `inferred` | deduced from indirect evidence: hidden continuations, the rear of a building, a buried pipe suggested by a trench | `confidence`, `notes` with the evidence, `frameIds` of the frames the evidence is in |
| `manual` | what the user told you, design decisions, gameplay annotations | `notes` saying who decided (`"per user: well behind the house"`) |
| `procedural` | never from this skill; generators add it | - |

Examples:

* A house fully visible in three frames: `observed`, cite the two clearest
  and the one you measured in.
* The same house, rear wall never seen, footprint completed as a rectangle:
  still `observed`, with `notes: "rear wall not visible; depth from roof ridge"`
  and a lower confidence.
* A fence running into a hedge and reappearing 20 m further: one fence,
  `observed`, with the hidden part as it is (do not invent a gap). If you
  cannot tell whether it continues, end it where it disappears and add an
  `inferred` fence for the hidden part, or nothing.
* Tree species: `observed` when the crown, bark or leaves are recognisable;
  otherwise `species: "unknown"` (zones: an `unknown` share in `species`).
  Guessing "birch" from a dot is not an observation.
* Building `condition`, `abandonment`, `openings`: observed only as far as the
  frames show them (broken windows, missing roof sheets, overgrown paths);
  otherwise leave the default or `unknown`.
* Things the user says: `manual`. Things from a map the user gave you: put
  the map in the package (`media/`), list it in `source.media`, and cite it
  through an observation.

## Citing frames

* `frameIds` must be IDs from `source.frames`, i.e. frames `frames.py`
  extracted. The validator rejects unknown IDs (`REFERENCE_NOT_FOUND`).
* Cite only frames **you have looked at** in which the entity is visible.
  A contact-sheet tile counts only if the entity is clearly recognisable in
  it.
* Need a moment that is not extracted yet? Extract it
  (`frames.py extract ... --method manual --at 47.2`), run `sync-source
  --write`, look at it, then cite it.
* Prefer the frames you measured in; that is what makes the number checkable.

## Observations

`source.observations` holds findings that several entities share or that
justify the calibration:

```json
{
  "id": "obs-scale-overview",
  "kind": "scale_measurement",
  "description": "Overview frame width 94 m: telemetry footprint 94.3 m (60 m AGL, 24 mm) and car reference 91 +- 9 m agree.",
  "frameIds": ["vid-dji_0042-x01-00042000"],
  "confidence": 0.8
}
```

Entities cite them with `observationIds`. Good candidates: scale
measurements, the north direction, "plots 1-8 are 20 x 30 m" (a pattern),
"area west of the road not filmed".

## Calibration

`source.calibration` summarises how the map was scaled and anchored:

| `method` | When |
| --- | --- |
| `none` | scale only from typical sizes or not cross-checked |
| `manual_scale` | scale from reference objects, cross-checked (most videos) |
| `reference_points` | `source.referencePoints` with known positions anchor the map |
| `gps` | telemetry GPS / altitude set the scale and position |
| `photogrammetry` | an orthophoto or model from photogrammetry |
| `survey` | surveyed points |

Also give `scaleConfidence` (0-1), `estimatedErrorM` (typical position error
of the map) and `notes` (north, the overview frame, the references used).
Claim only what you did: `gps` needs telemetry in `source.media`;
`reference_points` needs `referencePoints`.

## Notes

Short, evidence first, with the frame:

* `"measured in ...-00042000: 2.2 car lengths; front faces the road"`
* `"inferred: fence line continues behind lilac between ...-00051000 and ...-00055000"`
* `"height from storeys (2) and door; no side view"`

## Never

* invent GPS coordinates, dates, addresses, sizes or species;
* fill coordinates from memory of a map or satellite image you were not given;
* cite a frame you did not open, or a frame from another location;
* mark design intent (gameplay areas, spawn points) as `observed`;
* raise `confidence` or drop `provenance` to make a warning disappear.
