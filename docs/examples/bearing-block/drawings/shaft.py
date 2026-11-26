"""Part sheet for the shaft: the turned part with the keyway and the two circlip grooves.

An assembly sheet dimensions what holds the block together; a part sheet dimensions what the workshop has to make. So
this one carries the fits (Ø10 h6 where the bearings sit) and the grooves the circlips sit in, and it leaves out the
item numbers and the parts list. Both sheets come from the same `model.py`: nothing here is typed that the model can
measure.

The main view is a section and not a plain view, and that is the one decision on this sheet. The shaft runs along Z and
the keyway is on +Y, so the front view - which looks from -Y - would show the keyway as a hidden edge, and a dimension
belongs on a visible one (ISO 129). A section along the axis at x = 0 holds the axis and the keyway: its length, its
depth and both grooves become cut faces, and the outline is the same as a plain view's, so nothing is lost. At 2:1 the
shaft is 20 x 158 on the sheet and runs up and down. The keyway is 3 mm wide - 6 mm on the sheet, two lines that nothing
fits between - so it also gets a cross-section of its own at 5:1.

The numbers look arbitrary and are not: 23.95 is 15 (the overhang) + 9 (the bearing) - 0.05, the axial play a circlip
needs in its groove, because the groove is 0.1 wider than the ring it holds. The grooves are chained from the left end
of the shaft and the keyway from the right one, so the two chains do not have to meet on a number nobody would choose.
"""
import math

from soma.drawing import Sheet
from model import BORE, HOUSING_D, KEY_LENGTH, KEY_Z, OVERHANG, STUB, key, ring_a, ring_b

END = STUB + HOUSING_D                                  # 64: the right end, from the housing face
PLAY = (ring_a.groove_width - ring_a.thickness) / 2     # 0.05: how far a circlip may move in its groove
A0 = ring_a.seat[2] - PLAY                              # 8.95: the flank ring A bears on
B0 = ring_b.seat[2] - PLAY                              # 23.95: the same for ring B
KEY0, KEY1 = KEY_Z - KEY_LENGTH / 2, KEY_Z + KEY_LENGTH / 2   # 36 .. 56 along the shaft
HALF = key.width / 2                                    # 1.5: half the keyway width
WALL = math.sqrt((BORE / 2) ** 2 - HALF ** 2)           # 4.77: where the keyway walls meet the shaft

sh = Sheet("Shaft", size="A4", scale="2:1", number="BB-002", material="C45 +QT",
           tolerance="ISO 2768-m", projection="first", language="en")

# C-C through x = 0: the plane holds the axis and the keyway, so the keyway and both grooves are cut lengthwise.
c = sh.section("Shaft", "right", through=(0, 0, 0), at=(60, 180), name="C")
# B-B across the keyway at 5:1: the Ø10 is 50 mm on the sheet and the keyway 15 mm. Its label goes to the top left,
# because the width dimension needs the room directly above the circle.
b = sh.section("Shaft", "top", through=(0, 0, KEY_Z), at=(140, 215), scale="5:1", name="B", label_at=(114, 253))

# In C-C the sheet's x is the model's y, so a point on the side of the shaft is (0, ±5, z) and not (5, 0, z). Every
# point below is a corner of the outline: the end faces, the flanks of the grooves, the ends of the keyway. The short
# dimension sits closer to the part, so the long one's extension lines are the ones that have to cross a dimension line.
c.dim((0, -5, 0), (0, -5, -OVERHANG), offset=-12)        # 15 input overhang, to the face of the housing
c.dim((0, -5, -OVERHANG), (0, -5, END), offset=-24)      # 79 over all
c.dim((0, 5, -OVERHANG), (0, 5, A0), offset=12)          # 23.95 to the first groove
c.dim((0, 5, A0), (0, 5, B0), offset=12)                 # 15 groove to groove
c.dim((0, 5, KEY0), (0, 5, KEY1), offset=12)             # 20 keyway
c.dim((0, 5, KEY1), (0, 5, END), offset=12)              # 8 keyway to the end of the shaft

# In the cross-section: the fit the bearings sit on, and the keyway width with its fit. A diameter dimension puts its
# text on the circle, where it lies on an edge: text_at moves it out, and it has to go on along the dimension line (45
# degrees here) or it hangs beside it with nothing in between.
b.diameter((0, 0, KEY_Z), BORE / 2, text="Ø<> h6", text_at=(166, 241))
b.dim((-HALF, WALL, KEY_Z), (HALF, WALL, KEY_Z), offset=8, text="3 N9")

sh.text(f"Notes:\n"
        f"  1. General tolerances ISO 2768-m, all edges deburred 0.2.\n"
        f"  2. Ø10 h6 only under the bearings; the rest may be turned to h11.\n"
        f"  3. Two circlip grooves DIN 471 {BORE:g}x{ring_a.thickness:g}: Ø{ring_a.groove_diameter:g} +0.1, "
        f"width {ring_a.groove_width:g}.\n"
        f"  4. Keyway DIN 6885 - {key.width:g}x{key.height:g}x{key.length:g}, shaft depth {key.shaft_depth:g}.",
        (24, 80))
