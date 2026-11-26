"""Bearing block: a housing with two deep groove ball bearings on one shaft, retained by circlips.

This is the model `npm run test:assembly` builds: it is the smallest example in which every standard part has to
fit a part that was modelled by hand, so the measurements that matter are the ones between parts, not the ones
inside a part.

How it is put together, and why in this order:

- The housing has a stepped through-bore: 30 mm where the bearings sit, 26 mm between them. The step at each end is
  the shoulder that stops an outer ring from moving outwards.
- The shaft carries both inner rings. Each inner ring is held on the shaft by a DIN 471 circlip that sits against
  it on the inside, so bearing A is pushed one way and bearing B the other. That is what locates the shaft.
- Both circlips are `mounted=True`: a ring in its free state is smaller than its groove (d3 < d2), so a free ring
  always overlaps the shaft it is drawn on, and the interference measurement would report that as a collision.
- The key on the output stub is a DIN 6885 form A key. The shaft runs along Z, so the key needs `direction` and
  `angle`: without them it would lie across the shaft instead of along it.
"""
import cadquery as cq
from soma import add_part, param
from soma.fasteners import Bearing, RetainingRing, ShaftKey

# --- chosen for this block --------------------------------------------------------------------------------------
HOUSING_W = param(90.0, "Housing width", min=70.0, max=120.0, step=1.0, unit="mm")
HOUSING_H = param(50.0, "Housing height", min=40.0, max=80.0, step=1.0, unit="mm")
HOUSING_D = param(34.0, "Housing depth", min=30.0, max=60.0, step=1.0, unit="mm")
OVERHANG = param(15.0, "Input overhang", min=5.0, max=60.0, step=1.0, unit="mm",
                 help="Shaft length in front of the housing on the input side.")
STUB = param(30.0, "Output stub", min=20.0, max=80.0, step=1.0, unit="mm",
             help="Shaft length behind the housing on the output side. Has to carry the key.")

# --- fixed by the bearing and by the standard, not a choice -----------------------------------------------------
bearing_a = Bearing("6200", at=(0, 0, 0))     # 10 x 30 x 9, the smallest of the 62 series
BORE, OD, SEAT = bearing_a.bore, bearing_a.diameter, bearing_a.width
MID = HOUSING_D - SEAT                        # 25: the second shoulder, and the middle bore in between
bearing_b = Bearing("6200", at=(0, 0, MID))
KEY_LENGTH = 20.0                             # a design decision: the table does not name lengths
KEY_Z = HOUSING_D + 12.0                      # centre of the key on the stub, clear of bearing B and inside the shaft


def cyl(diameter, z0, z1):
    """Cylinder between two heights, for the bore."""
    return cq.Solid.makeCylinder(diameter / 2, z1 - z0, cq.Vector(0, 0, z0), cq.Vector(0, 0, 1))


# --- housing ----------------------------------------------------------------------------------------------------
housing = cq.Workplane("XY").box(HOUSING_W, HOUSING_H, HOUSING_D, centered=(True, True, False))
housing = housing.cut(cyl(OD, -1.0, HOUSING_D + 1.0))          # through-bore, 1 mm past both faces
housing = housing.cut(cyl(OD - 4.0, SEAT, MID))                # 26 mm between the two seats
add_part("Housing", housing, color=(0.62, 0.64, 0.68))

# --- shaft: two grooves for the circlips, one keyway on the stub -------------------------------------------------
shaft = cq.Workplane("XY").workplane(offset=-OVERHANG).circle(BORE / 2).extrude(OVERHANG + HOUSING_D + STUB)

ring_a = RetainingRing("DIN 471", BORE, at=(0, 0, SEAT), mounted=True)
ring_b = RetainingRing("DIN 471", BORE, at=(0, 0, MID - ring_a.thickness), mounted=True)
for ring in (ring_a, ring_b):
    shaft = shaft.cut(ring.groove())

# The shaft runs along Z and the key lies in the plane of the surface: -Y points into the material, 90 degrees
# turns the key's length from X onto Z.
key = ShaftKey(BORE, KEY_LENGTH, at=(0, BORE / 2, KEY_Z), direction="-Y", angle=90)
shaft = shaft.cut(key.keyway("shaft"))
add_part("Shaft", shaft, color=(0.72, 0.73, 0.75))

# --- purchased parts --------------------------------------------------------------------------------------------
add_part("Bearing A", bearing_a)
add_part("Bearing B", bearing_b)
add_part("Ring A", ring_a)
add_part("Ring B", ring_b)
add_part("Key", key)
