---
title: Assemblies and motion
name: Assemblies and motion
summary: Parts in assembled position from shared references, interfaces defined only once, ease of assembly, moving parts checked over their whole travel ({{motion_gap}} mm gap), parts list.
order: 24
category: Design knowledge
default: on-demand
when: several parts are assembled or move against each other
topics: References and assembled position; Interfaces; Ease of assembly; Moving parts; Parts list
var motion_gap: 1 | mm | Minimum gap between moving parts | 0..20
---
# Skill: Assemblies and motion

Minimum gap between moving parts, from the app: `MOTION_GAP = {{motion_gap}}`. It applies unless the user says
otherwise in the chat or in `NOTES.md`.

## Positions

- One coordinate system for the whole model, origin at the main mounting face or axis.
- Each part is built in its own frame by a function, then placed with `.translate()` and `.rotate()`.
- Positions come from other parts, not from typed numbers: `LID_Z = BASE_H`, `shaft.translate((0, 0, BEARING_Z))`.
- Register parts in their assembled position, one group per sub-assembly (`group="Drive"`).

## Interfaces

Define every interface once and use it for both sides: one list `HOLES = [(x, y), ...]` for the bracket and the plate,
one constant for a shaft diameter, used for the shaft and (plus clearance) for the bore. Then both sides change
together.

## Assembly

- Every part goes in along a free path, in an order you can name. For more than three parts, write the order into
  `NOTES.md`.
- Every screw is reachable with its tool when the parts around it are in place.
- No part is trapped: nothing is enclosed that has to go in later.

## Moving parts

- The position of a moving part is a constant (`LID_ANGLE = 0`, `SLIDE_TRAVEL = 0`) with its range in a comment. The
  model shows the normal position.
- Check the whole range, at least both end positions and the middle:

```python
for a in (0, 45, 90):  # range of LID_ANGLE
    moved = lid.rotate((0, HINGE_Y, HINGE_Z), (1, HINGE_Y, HINGE_Z), a)
    print(a, base.intersect(moved).val().Volume(), base.val().distance(moved.val()))
```

The volume must be 0, the distance at least `MOTION_GAP`, except where parts are meant to touch (pin, guide). Remove
the output afterwards. For motions with several steps or parts, write an animation (skill for animation) and run
`soma anim check "Name" --gap {{motion_gap}}`: it checks every moment. `soma analyze clearance` shows tight gaps in
the model position.

## STEP files and other programs

`output/model.step` and `soma export --assembly --format step` write the groups as sub-assemblies, with part names and
colours. Three rules follow from the format, not from taste:

- **Names in the STEP file are ASCII and unique.** `add_part("Gehäuse")` becomes `Gehaeuse` in the file; `step_name`
  holds that name. Umlauts, `ß` and CJK cannot be written correctly (OCCT writes them double-encoded), so SOMA
  transliterates. The name in the app stays as the user wrote it. Two names that transliterate to the same string are
  rejected, and rightly so: `Größe` and `Groesse` would collide.
- **Groups become sub-assemblies.** The nesting is the point of the export: `group="Housing/Screws"` is two levels.
  A flat model arrives in the other program as a flat list.
- **References go under "Reference"**, purchased parts keep their group. References are in the file (so the model is
  complete) but not in `soma export --all`.

Check the result with the same tool that measured the model, not by opening the file somewhere else:

```bash
soma inspect --json --out model.json
soma export --assembly --format step
soma inspect --step exports/<name>.step --json --out export.json
```

`totals.solids`, `totals.volume` and `bounds.size` must match. If they do not, bodies were lost or merged on the way
out — usually a part that was a shell instead of a solid (`topology.solids` 0).

**A part that is valid on its own can still be in the wrong place.** `soma inspect` measures each part; add
`--overlaps` and it also measures every pair:

```bash
soma inspect --overlaps            # Overlaps: none
soma inspect --overlaps --strict   # exit code 1 when two parts share space
```

A reported pair is a part that was placed where another part already is, or a pocket that was never cut. Both are the
usual mistakes in an assembly, and neither shows up in a picture. Two overlaps are not defects: a press fit is nominal
in the model (so it overlaps by nothing) and a circlip in its free state is smaller than its own groove — for that one
use `RetainingRing(..., mounted=True)`.

## Foreign STEP files

`import_assembly("inputs/board.step")` keeps the parts with their names and colours, sub-assemblies as groups. Things
that catch people out:

- **The origin is often a corner, not the centre.** Look at the bounding box first, then move it deliberately with
  `asm.loc = cq.Location((x, y, z))`.
- **Colours sit on the bodies, not on the compound.** A board with several bodies shows one colour per body; a single
  colour for the whole thing is a simplification, not a bug in the file.
- **A reference has no volume.** Give it `role="reference"`: semi-transparent, not in `soma export --all`, and
  `soma inspect` reports it as a warning instead of an error. Cut clearances around it, do not export it.
- Do not modify files in `inputs/`. Load them, and put the modifications in your own parts.

## Parts list

`soma bom` writes it from the model: purchased parts grouped by designation with a count, own parts with volume and,
with `--density`, mass. `--csv order.csv` gives a table for a spreadsheet. Details in the skill for standard parts.

`NOTES.md` keeps what the model cannot say: material, process, surface finish, and anything the user asked for that is
not geometry. Write those there, one line each, with where they came from. The quantities come from `soma bom`, not
from memory — the same screw written twice in different words is the most common mistake in a hand-written list.
