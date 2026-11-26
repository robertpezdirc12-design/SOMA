# Notes — wall bracket for a 32 inch monitor arm

The worked example of `docs/DRAFTWRIGHT-HANDOFF.md`. The numbers live in `model.py`; this file holds what is not
geometry. It was written the way the handoff describes: read `inputs/draftwright.json`, ask what it leaves open,
answer it here, then build.

## Where each number ended up

| `inputs/draftwright.json` | `model.py` | why |
|---|---|---|
| `plate_w` 120.0, measured | `PLATE_W = param(...)` | the user may want a wider plate |
| `plate_h` 120.0, measured | `PLATE_H = param(...)` | same |
| `plate_t` 6.0, **assumed** | `PLATE_T = param(...)` | assumed, so it is a parameter with the assumption in its `help` |
| `hole_d` 6.6, measured | `HOLE_D = param(...)` | clearance for M6; a different screw is a different hole |
| `corner_r` 8.0, measured | `CORNER_R = param(...)` | visible in the photo, easy to change |
| `hole_pitch` 100.0, standard | `PITCH = 100.0` | **not** a parameter: VESA 100 is the interface, not a preference |
| `chamfer` 0.5, standard | `CHAMFER = 0.5` | **not** a parameter: rule 2 fixes it |

`features[]` became loops, not copy-paste: `rarray(PITCH, PITCH, 2, 2)` is the 2 × 2 rectangular pattern with
`centered: true`, and `.edges("|Z").fillet(CORNER_R)` is the outer-corner fillet.

## Rules, and what was done about each

1. *"Must fit the existing VESA 100 plate without play: clearance hole, not a tapped hole."* — `HOLE_D` is a clearance
   hole, 6.6 mm for M6 (ISO 273 normal). Nothing is tapped; there is no thread in the model, and the handoff says
   threads stay out of the geometry.
2. *"Front face visible when mounted: no sharp edges, chamfer 0.5 mm."* — `.edges(">Z").chamfer(0.5)` on the outer edge
   and on the hole rims. One call, because both are edges of the front face.
3. *"Wall side must not scratch paint: no ribs on the back."* — a decision **not** to add geometry. The back is flat;
   there is nothing in `model.py` to point at, which is why the rule is written down here.

## Open questions, answered

- **Material: aluminium or steel?** Aluminium, 6061-T6, 3 mm minimum wall and no ribs. Steel would halve the thickness
  for the same stiffness and then the 6 mm from the photo would be wrong — so the material had to be settled before
  the thickness meant anything.
- **Is the 6 mm fixed by the customer, or may it change?** Fixed by the customer, who has the same plate on the wall
  already. That is why `PLATE_T` is a parameter with a narrow range (3 to 12 mm) rather than free: it may be changed,
  but it is not the first thing to change.

## What is not in this example

`references[]` names `photo-front.jpg`, `sketch.jpg` and `arm-plate.step`. They are not in the repository: the photo
and the sketch are the agent's eyes and never a feature in `model.py`, and the mating part belongs to the customer.
The field stays in the JSON because a handoff without its references cannot be checked by a person later.

## Checked

`soma build`, then `soma inspect --json`: one closed, valid solid, `bounds.size` 120 × 120 × 6, volume 85180 mm³ —
which is the 86400 mm³ block minus the four corner fillets, the four holes and the chamfer. `npm run test:handoff`
does exactly this, so the example cannot quietly stop matching the JSON it came from.
