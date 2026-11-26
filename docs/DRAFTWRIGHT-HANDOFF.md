# Draftwright → SOMA handoff

**Status:** contract · **Prepared:** 2026-11-26 · **Scope:** no new architecture, no new code path in SOMA

> Draftwright understands a photo, a sketch, measurements and product rules. SOMA turns that understanding into
> parametric 3D geometry. This document fixes the seam between them so neither side has to guess: **what Draftwright
> writes, where it lands, and how the agent turns it into `param()` and a model.**

---

## 1. The seam

Nothing new is needed. SOMA already has the three places a handoff can land, and each has one job:

| Place | Written by | Read by | Holds |
|---|---|---|---|
| `inputs/` | the user, Draftwright | the agent, `model.py` | the originals: photo, sketch, PDF, STEP of a purchased part, `draftwright.json` |
| `NOTES.md` | the agent, the user | the agent | the rules that are not geometry: material, process, "the customer wants it to look like the old one" |
| `model.py` | the agent | `soma build` | the numbers as `param()`, the geometry |

**The rule that keeps this from becoming an architecture:** Draftwright writes **files**, the agent reads them with
plain Python. SOMA gets no Draftwright client, no API key, no background sync, no new dependency. `inputs/` is already
the folder for "files the user brought, never modified" (`AGENTS.md`).

## 2. What Draftwright writes

One JSON file, `inputs/draftwright.json`, plus the images it refers to. The schema is deliberately small: anything that
is not a number with a unit is a sentence for the agent, not a field.

```json
{
  "schema": "draftwright.handoff/1",
  "product": "Wall bracket for a 32 inch monitor arm",
  "unit": "mm",
  "dimensions": [
    { "id": "plate_w",  "label": "Plate width",   "value": 120.0, "source": "measured", "confidence": "high" },
    { "id": "plate_h",  "label": "Plate height",  "value": 80.0,  "source": "measured", "confidence": "high" },
    { "id": "plate_t",  "label": "Plate thickness","value": 6.0,  "source": "assumed",  "confidence": "low",
      "note": "not visible in the photo; M6 screws and a 5 kg load suggest 6 mm aluminium" },
    { "id": "hole_d",   "label": "Hole diameter", "value": 6.6,   "source": "measured", "confidence": "high" },
    { "id": "hole_pitch","label": "Hole pitch VESA 100", "value": 100.0, "source": "standard", "confidence": "high" }
  ],
  "features": [
    { "kind": "hole", "count": 4, "diameter": "hole_d", "pattern": "rectangular",
      "pitch": ["hole_pitch", "hole_pitch"], "centered": true },
    { "kind": "fillet", "where": "outer corners", "radius": 8.0, "note": "visible in the photo, radius estimated" }
  ],
  "rules": [
    "Must fit the existing VESA 100 plate without play: clearance hole, not a tapped hole.",
    "Front face visible when mounted: no sharp edges, chamfer 0.5 mm.",
    "Wall side must not scratch paint: no ribs on the back."
  ],
  "references": [
    { "file": "inputs/photo-front.jpg", "shows": "front view, four holes, rounded corners" },
    { "file": "inputs/sketch.jpg", "shows": "hand sketch with 120 x 80 and the hole spacing" },
    { "file": "inputs/arm-plate.step", "shows": "the mating part, from the customer" }
  ],
  "open_questions": [
    "Material: aluminium or steel? The photo cannot tell.",
    "Is the 6 mm thickness fixed by the customer, or may it change?"
  ]
}
```

### Field rules

| Field | Meaning | What the agent does with it |
|---|---|---|
| `dimensions[].value` + `unit` | A number in millimetres | Becomes a `param()` when the user would want to change it, otherwise a named constant |
| `dimensions[].source` | `measured`, `assumed`, `standard`, `calculated` | `assumed` and `low` confidence go into `NOTES.md` and are named to the user, never silently used |
| `dimensions[].id` | Short key | The constant name, upper-cased: `plate_w` → `PLATE_W` |
| `features[]` | What repeats | Loops and patterns in the code, not copy-paste |
| `rules[]` | Sentences, not numbers | `NOTES.md`, and the skill that owns the topic (tolerances, 3D printing, CNC) |
| `open_questions[]` | What Draftwright could not decide | **Ask the user before building.** A guessed dimension that nobody questions is the most expensive mistake in the whole chain |

`confidence` is not decoration: `low` means "the model may be wrong and the user must know". A bracket that is 4 mm
instead of 6 mm is a return.

## 3. What the agent does

1. **Read `NOTES.md` first**, then `inputs/draftwright.json`. If `open_questions` is not empty, ask them in one
   message with proposed answers, and wait.
2. **Choose the parameters.** 3 to 15 values the user would change themselves (`AGENTS.md` rule 7): the main
   dimensions, counts, options. `PLATE_W = param(120.0, "Plate width", min=60, max=200, step=1, unit="mm")`.
   Derived values (`HOLE_PITCH / 2`) stay constants.
3. **Load the references, do not re-measure them.** `import_assembly("inputs/arm-plate.step")` for a mating part,
   `role="reference"`. The photo is for the agent's eyes, not for a feature in `model.py`.
4. **Write the rules into `NOTES.md`**, one line each, with where they came from.
5. **Build and measure.** `soma build`, then `soma inspect --json`. The numbers in `dimensions` must appear in
   `source.parameters` with `source: "code"`, and `bounds.size` must match the measured width and height. A mismatch is
   a bug in the model, not in the handoff.
6. **Report back in the user's words**: what was measured, what was assumed, what is still open.

```python
# model.py, the part Draftwright described
from soma import add_part, param, import_assembly

PLATE_W = param(120.0, "Plate width", min=60, max=200, step=1, unit="mm")
PLATE_H = param(80.0, "Plate height", min=40, max=150, step=1, unit="mm")
PLATE_T = param(6.0, "Plate thickness", min=3, max=12, step=0.5, unit="mm")   # assumed, see NOTES.md
HOLE_D = param(6.6, "Hole diameter", min=3, max=12, step=0.1, unit="mm")      # VESA 100, clearance
PITCH = 100.0                                                                  # VESA 100, fixed by the standard
CORNER_R = param(8.0, "Corner radius", min=0, max=25, step=1, unit="mm")

plate = (
    cq.Workplane("XY").box(PLATE_W, PLATE_H, PLATE_T)
    .edges("|Z").fillet(CORNER_R)
    .faces(">Z").workplane()
    .rarray(PITCH, PITCH, 2, 2).hole(HOLE_D)
)
add_part("Plate", plate)
add_part("Arm plate", import_assembly("inputs/arm-plate.step"), role="reference")
```

## 4. Verification

```bash
soma build
soma inspect --json | python -c "import json,sys; d=json.load(sys.stdin); print([p for p in d['source']['parameters']])"
soma inspect --json | python -c "import json,sys; print(json.load(sys.stdin)['bounds']['size'])"
```

- Every `dimensions[].id` appears as a parameter (or is a constant with a comment saying why).
- `bounds.size` equals `[PLATE_W, PLATE_H, PLATE_T]` for the part, within a fillet.
- `checks.ok` is true: one closed, valid solid, no duplicate bodies.
- The `open_questions` are answered in `NOTES.md`, not just in the chat.

## 5. What this deliberately does not do

- **No image processing in SOMA.** The photo is understood once, by Draftwright, and its conclusion is a number. A
  second interpretation inside SOMA would disagree with the first.
- **No Draftwright API call from the agent.** The agent reads a file. A network call would make the model depend on a
  service being up and on a key being present.
- **No schema for geometry.** `features[]` names what repeats; how it is built stays the agent's decision, because
  the right CadQuery expression depends on the model around it.
- **No automatic parameter import.** Writing `parameters.json` directly would look like the user set those values in
  the app, and the app would then protect them from later code changes. The defaults belong in `model.py`.
