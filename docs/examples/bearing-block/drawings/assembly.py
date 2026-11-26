"""Assembly sheet for the bearing block: a section along the shaft axis, a plan view, item numbers and a parts list.

The part numbers are the ones in the parts list below and nothing else; the test compares that list against
`soma bom`, so the sheet cannot drift away from the model. Only overall, connecting and fitting dimensions are on an
assembly drawing - the parts get their own sheets.

Where the dimensions go is decided by the geometry, not by taste: the section is 90 x 79 on the sheet (x = model x,
y = model z) and the shaft runs through its middle, so the width goes below the shaft end, the housing depth to the
left of the housing and the overhang between the two shaft lines. The shaft itself is dimensioned in the plan, where it
is a circle: 10 mm of shaft are 13 mm of text, which never fits between two lines 10 mm apart.
"""
from soma.drawing import Sheet

sh = Sheet("Bearing block", size="A3", scale="1:1", number="BB-001", material="see parts list",
           tolerance="ISO 2768-m", projection="first", language="en")

# A-A through y = 0: the plane contains the shaft axis, so the bores, both bearings, both circlips and the shaft are cut.
# Sheet (x, y) = (125 + x, 160.5 + z): housing 80..170 x 160.5..194.5, shaft 120..130 x 145.5..224.5.
a = sh.section("*", "front", through=(0, 0, 0), at=(125, 185), name="A",
               unhatched=["Shaft", "Bearing A", "Bearing B", "Ring A", "Ring B", "Key"])
# Sheet (x, y) = (125 + x, 100 + y): housing 80..170 x 75..125, the bore as a circle of r 15 around (125, 100).
plan = sh.view("*", "top", at=(125, 100), hidden=False)

# Overall and fitting dimensions. `a` is a section, so its outline is the cut face - dimension on it.
a.dim((-45, 0, 0), (45, 0, 0), offset=-20)          # 90 housing width, below the shaft end
a.dim((-45, 0, 0), (-45, 0, 34), offset=-12)        # 34 housing depth, left of the housing
a.dim((-5, 0, 0), (-5, 0, -15), offset=-12)         # 15 input overhang, between the two shaft lines
plan.dim((-45, -25, 34), (-45, 25, 34), offset=-12)  # 50 housing height, left of the plan
# A diameter dimension puts its text on the circle, where it lies on an edge: text_at moves it out, and it has to go
# straight on along the dimension line (45 degrees here) or it hangs beside it with nothing in between.
plan.diameter((0, 0, 34), 15, text_at=(143, 116))   # Ø30 bore
# The shaft is 10 mm wide and its text 13 mm: it does not fit between the arrows, so the text goes outside with a
# leader. Between the end of the keyway (z 56) and the end face (z 64) the shaft is free of both.
a.dim((-5, 0, 58), (5, 0, 58), offset=0, text="Ø10", text_at=(152, 218), leader=True)

# Item numbers: the same part always gets the same number, and every number appears in the parts list.
# The leaders fan out to the right at their own height so that none of them runs into a dimension.
a.leader((35, 0, 28), "1", at=(205, 212), end="dot")     # housing
a.leader((5, 0, 40), "2", at=(205, 200), end="arrow")    # shaft
a.leader((10, 0, 4.5), "3", at=(205, 150), end="dot")    # bearing
a.leader((6, 0, 9.5), "4", at=(205, 165), end="dot")     # circlip
plan.leader((0, 6, 46), "5", at=(205, 106), end="dot")   # key

sh.table([
    ["Pos", "Name", "Qty", "Designation / material"],
    ["1", "Housing", "1", "EN AW-6082 T6"],
    ["2", "Shaft", "1", "C45 +QT"],
    ["3", "Deep groove ball bearing", "2", "6200"],
    ["4", "Retaining ring", "2", "DIN 471 10x1"],
    ["5", "Parallel key", "1", "DIN 6885 3x3x20"],
], at=(230, 160))

sh.text("Notes:\n  1. Bearings are a press fit in the housing and on the shaft.\n"
        "  2. Both circlips hold the inner rings; the shaft is located between them.", (230, 105))
