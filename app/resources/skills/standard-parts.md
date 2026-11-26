---
title: Standard parts
name: Standard parts
summary: Screws, nuts, washers, threaded inserts and deep-groove ball bearings from soma.fasteners with matching holes, nut traps, seats, dowel pins and aluminium extrusions.
order: 22
category: Design knowledge
default: always
when: the model needs screws, nuts, washers, threaded inserts, bearings, dowel pins or profiles
topics: Screws, nuts, washers and inserts with soma.fasteners; Position and holes; Nut traps; Ball bearings; Pins and profiles; Standard parts in the model
---
# Skill: Standard parts

Nominal sizes in mm. Real parts vary: if the user has the parts, ask them to measure what matters. Other purchased
parts (motors, switches, displays): never guess, ask for a datasheet or a STEP file.

## Screws, nuts, washers, inserts: `soma.fasteners`

Never model them by hand. `soma.fasteners` builds them simplified (no thread) with dimensions from standard tables and
brings the matching holes as tools for `cut()`:

```python
from soma.fasteners import Screw, Nut, Washer, HeatSetInsert, pick_length

s = Screw("ISO 4762", "M3x10", at=(20, 15, LID_TOP))  # head rests on the surface at `at`, shank along -Z
lid = lid.cut(s.clearance_hole())                      # ISO 273 fit="medium", oversize=0.2 for printed holes
ins = HeatSetInsert("M3x5.7", at=(20, 15, BOSS_TOP))   # top flush with `at`
base = base.cut(ins.hole())                            # or base.cut(s.tap_hole()) for a tapped hole
add_part("Screw 1", s, group="Hardware")               # role "hardware" automatically
```

- Position: `at` is the point on the axis where the part rests, `direction` (default `"-Z"`) points from there into
  the material. With `at=(x, y), on=lid` the surface is found along `direction`. `sunk=True` sinks a head, nut or
  washer flush with `at` (the hole gets the counterbore). Countersunk screws, set screws and inserts always sit flush.
- Moving: `s.rotate(p1, p2, angle)`, `s.translate((x, y, z))` and `s.moved(loc)` return a moved copy, like CadQuery
  shapes. Build a moving part with its screws in one place, then move both the same way.
- Other end: `s.point(d)` is the point `d` mm from the seat along the axis, `.outer` the opposite face. Under a plate
  of thickness `T`: `w = Washer("ISO 7089", "M3", at=s.point(T), direction="+Z")`, then
  `Nut("ISO 4032", "M3", at=w.outer, direction="+Z")`.
- Standards: screws ISO 4762 (socket head, the default), ISO 7380 (button head, low), ISO 10642 (countersunk),
  ISO 4017, ISO 4014, DIN 931 (hex head), ISO 4026 (set screw). Nuts ISO 4032, thin ISO 4035, high ISO 4033, square
  DIN 557. Washers ISO 7089, large ISO 7093 on soft material. Inserts by ruthex (default), CNCKitchen, McMaster-Carr,
  Hilitchi. In prints, heat-set inserts instead of nuts where the screw is opened often.
- Read sizes from the objects instead of typing numbers: `s.head_diameter`, `s.head_height`, `s.key`, `s.clearance()`,
  `nut.key`, `nut.height`, `ins.diameter`, `ins.length`.
- Only standard lengths: `pick_length("ISO 4762", "M3", min_length, max_length)` returns the shortest that fits.
  Through a nut at least grip + washers + nut height + 2 × pitch, into an insert between grip + half and grip + the
  whole insert length.
- Cut each hole only from the part it belongs to. All options are in the docstrings of the file
  `python -c "import soma.fasteners as f; print(f.__file__)"` prints.

## Nut traps

`nut.trap(clearance=0.2)` is the pocket for the nut, open to the surface with `sunk=True`. With `slot="+X",
slot_length=…` the nut slides in from the side. At `angle=0` two flats are parallel to X, so a slot along X is exactly
as wide as the nut. For a slot along Y use `angle=30`.

## Bearings: `Bearing(designation, at=...)`

Never model a bearing by hand when the number is in the library:

```python
from soma.fasteners import Bearing

b = Bearing("608", at=(0, 0, SEAT_Z))       # one face rests at `at`, width B goes outward
add_part("Bearing 1", b, group="Hardware")   # role "hardware" automatically
```

- Covers bores from 3 to 10 mm: 604, 607, 608, 609, 623–629, 618/4–618/9, 619/4–619/9, 61800, 61900, 6000, 6200,
  6300, and the capped variants `623-2Z`, `E2.608-2Z`, `630/8-2RS1`, `638-2RZ` and so on. `Bearing(...)` with a
  number that is not there says which ones are.
- **Not** in the library: 6001, 6002, 6201, 688, anything above 10 mm bore, and all roller and angular-contact
  bearings. For those: ask for a STEP file, or model the envelope (two rings, or one ring) and say that it is one.
- `b.bore`, `b.diameter`, `b.width` are the catalogue values; `b.mass_g` is the real mass. The rings and balls in
  between are drawn to a rule, so the volume from `soma inspect` is smaller than the real part — for a parts list use
  `b.mass_g`, not volume × density.
- Capped or sealed (`-2Z`, `-2RS1`) is not a detail to drop: it changes the width and it is what the part is called.
  `b.capped` says which one you have.
- Seats: housing H7, shaft k6 when machined. Printed seats: start with `D` and adjust after a test print. Shoulders:
  on the shaft about `d + 0.2 × (D − d)`, in the housing about `D − 0.2 × (D − d)`.

## Pins and profiles

- Dowel pins ISO 8734 (m6): Ø 2, 3, 4, 5, 6, 8 mm, lengths 6, 8, 10, 12, 16, 20 mm and more. Holes H7.
- Aluminium extrusions, typical: 2020 slot 6 with M5, 3030 slot 8 with M6, 4040 slot 8 with M8. Systems differ: ask
  which one.

## What the library covers, and what it does not

Covered: screws ISO 4762, 7380, 10642, 4017, 4014, DIN 931, 4026; nuts ISO 4032, 4033, 4035, DIN 557; washers ISO
7089, 7091, 7093; heat-set inserts from five makers; deep-groove ball bearings from 3 to 10 mm bore, open and capped;
the clearance holes, tap drills, counterbores, nut traps and insert holes that go with them. Nothing else.

Not covered, model by hand (with `role="hardware"`): roller and angular-contact bearings, dowel pins, retaining rings,
shaft keys, O-rings, gears, sprockets, pulleys, springs, low-profile and shoulder screws, flange and cap nuts, imperial
fasteners. Ask before inventing dimensions; the sizes in this skill are a starting point, not a catalogue.

Three simplifications to know about:

- **No threads anywhere.** The shank is the nominal diameter, the bore of a nut is nominal, the tap drill is real. That
  is deliberate: a modelled thread costs hundreds of thousands of triangles and no slicer resolves it.
- **ISO 4014 and DIN 931 are modelled fully threaded**, although the real bolt has a plain shank below the head. Fine
  for a picture and for a clearance hole; wrong if someone reads a thread length off the model. Say so if it matters.
- **Fine pitches are not supported.** Only coarse threads exist. `Screw("ISO 4762", "M10x1.25x40")` is rejected as
  unreadable, and `"M10x1.25"` is read as M10 with a length of 1.25 mm and rejected as a non-standard length — the
  second message is misleading, it is not about the length. Use the coarse thread, or model the special case yourself.

## Keeping the parts list

`soma bom` writes the list for you, from the model:

```bash
soma bom                                  # two tables: what to buy, what to make
soma bom --density 2.7 --csv order.csv    # plus mass and a table for a spreadsheet
```

Purchased parts are grouped by designation with a count — four screws called "Screw 1".."Screw 4" are one line with
count 4, because that is what you order. Heat-set inserts carry the manufacturer's `part_number`. Own parts are listed
with volume, and mass with `--density`.

- Run it before you tell the user what the model needs. A screw that is not from `soma.fasteners` still appears (as
  "modelled by hand"), but without a designation — which is the sign that it should have been a standard part.
- `--merge-identical` puts own parts with the same volume, area and box on one line with a count. It is a guess: two
  different parts can share those numbers. Use it when you know the parts repeat (a bracket used four times).
- References are not in the list; they are counted separately. `soma inspect --json` shows every part with its
  `designation`, `group` and `role` if you need the details behind a line.

## In the model

Parts from `soma.fasteners` get `role="hardware"` by themselves: opaque, part of `output/model.step`, skipped by
`soma export --all`. Model other purchased parts (bearings, pins) simplified, also with `role="hardware"`. A heat-set
insert is wider than its hole (it is melted in): leave it out of interference checks with its part. List every part
in `NOTES.md` (`s.designation` gives "ISO 4762 M3x10", `ins.part_number` the manufacturer's number).
