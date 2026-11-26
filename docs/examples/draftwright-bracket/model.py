"""Wall bracket for a 32 inch monitor arm — the part `inputs/draftwright.json` describes.

This is the worked example of `docs/DRAFTWRIGHT-HANDOFF.md`: the numbers below are the ones Draftwright measured, and
the model is the only place they live. Nothing is read from the JSON at build time — Draftwright writes the file once,
the agent decides which numbers are a `param()`, and `parameters.json` belongs to the user (handoff §5).
"""
import cadquery as cq
from soma import add_part, param

# --- measured on the part, or on the mating plate ---------------------------------------
PLATE_W = param(120.0, "Plate width", min=60.0, max=200.0, step=1.0, unit="mm")
PLATE_H = param(120.0, "Plate height", min=60.0, max=200.0, step=1.0, unit="mm")
HOLE_D = param(6.6, "Hole diameter", min=4.0, max=10.0, step=0.1, unit="mm",
               help="Clearance for M6 (ISO 273 normal). A tapped hole would fight the existing arm plate.")
CORNER_R = param(8.0, "Corner radius", min=0.0, max=25.0, step=1.0, unit="mm")

# --- assumed: the photo cannot show it, the answer is in NOTES.md -------------------------
PLATE_T = param(6.0, "Plate thickness", min=3.0, max=12.0, step=0.5, unit="mm",
                help="Assumed from the load, not measured. Aluminium, see NOTES.md.")

# --- fixed by a standard or by the rule, not the user's choice ---------------------------
PITCH = 100.0        # VESA 100, the hole spacing of the arm. Not a param: it is the interface.
CHAMFER = 0.5        # rule 2: no sharp edge on the front face. Not a param: 0.5 mm is what the rule says.

plate = (
    cq.Workplane("XY")
    .box(PLATE_W, PLATE_H, PLATE_T, centered=(True, True, False))
    .edges("|Z").fillet(CORNER_R)
    .faces(">Z").workplane()
    .rarray(PITCH, PITCH, 2, 2).hole(HOLE_D)          # 2 x 2 = the four VESA holes, centred
    .edges(">Z").chamfer(CHAMFER)                    # outer edge and hole rims, as rule 2 asks
)

# rule 3 ("no ribs on the back") is a decision not to add geometry, not geometry. It is in NOTES.md.
add_part("Bracket", plate, color=(0.62, 0.64, 0.68))
