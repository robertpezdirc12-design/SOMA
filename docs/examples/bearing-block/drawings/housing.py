"""Part sheet for the housing: the block with the stepped through-bore.

The third sheet of the example and the one with the least free space on it. A housing is a hole in a block, so the
section is the sheet: it shows the two bearing seats, the shoulder at each end and the bore between them. The plan is
there for the two numbers the section cannot give - the height of the block, which the section shows only as depth, and
Ø30, which is a circle only from above.

At 1:1 the block is 90 x 50 on the sheet, so both views fit on an A4 one above the other at a scale a workshop does not
have to undo. Every number here is a model number: the seats are `SEAT` deep because that is where `model.py` puts the
bearings, and the bore between them is `MID_BORE` because that is what it cut.
"""
from soma.drawing import Sheet
from model import HOUSING_D, HOUSING_H, HOUSING_W, MID, MID_BORE, OD, SEAT

sh = Sheet("Housing", size="A4", scale="1:1", number="BB-003", material="EN AW-6082 T6",
           tolerance="ISO 2768-m", projection="first", language="en")

# A-A through y = 0: the plane holds the bore axis, so both seats and both shoulders are cut. Sheet (x, y) =
# (110 + x, 200 + z): the block is 65..155 x 200..234 and the bore runs through its middle.
a = sh.section("Housing", "front", through=(0, 0, 0), at=(110, 200), name="A")
# The plan above it, sheet (x, y) = (110 + x, 130 + y): 65..155 x 105..155.
plan = sh.view("Housing", "top", at=(110, 130), hidden=False)

# Outside dimensions, each where nothing else is: the width below the section, the depth to its left, the height to the
# left of the plan so that it lines up with the depth above it.
a.dim((-HOUSING_W / 2, 0, 0), (HOUSING_W / 2, 0, 0), offset=-12)             # 90 wide
a.dim((-HOUSING_W / 2, 0, 0), (-HOUSING_W / 2, 0, HOUSING_D), offset=-12)    # 34 deep
plan.dim((-HOUSING_W / 2, -HOUSING_H / 2, HOUSING_D), (-HOUSING_W / 2, HOUSING_H / 2, HOUSING_D), offset=-12)  # 50

# The seats, chained from the front face. Both dimensions stand outside the block on the right: the shoulders are 30 mm
# inside it, and a line drawn between them would run through the hatching. Their extension lines have to cross it.
a.dim((OD / 2, 0, 0), (OD / 2, 0, SEAT), offset=37)          # 9 to the first shoulder
a.dim((OD / 2, 0, SEAT), (OD / 2, 0, MID), offset=37)        # 16 to the second

# The bores. Ø30 is a circle in the plan and gets a diameter dimension; Ø26 is behind the seat, so it is dimensioned in
# the section between the two lines that are its walls, with the Ø in front of the number (DIN 406).
plan.diameter((0, 0, HOUSING_D), OD / 2, text="Ø<> H7", text_at=(137, 130), angle=0)
a.dim((-MID_BORE / 2, 0, (SEAT + MID) / 2), (MID_BORE / 2, 0, (SEAT + MID) / 2), offset=0, text="Ø<>")

sh.text(f"Notes:\n"
        f"  1. General tolerances ISO 2768-m, all edges deburred 0.2.\n"
        f"  2. Both seats Ø{OD:g} H7, {SEAT:g} deep, coaxial within 0.02.\n"
        f"  3. Middle bore Ø{MID_BORE:g} H11, {MID - SEAT:g} long, no fit.",
        (24, 80))
