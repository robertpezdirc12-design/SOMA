---
title: Tolerances and fits
name: Tolerances and fits
summary: Clearances as named constants, interference checks in code, clearance holes and tap drills, counterbores for socket head screws, ISO fits.
order: 20
category: Design knowledge
default: on-demand
when: parts must fit together: clearances, holes for screws, sliding or press fits
topics: Manufacturing: {{process}}; Clearances as named constants; Checking interference and gaps in code; Clearance holes ({{hole_fit}}) and tap drills; Counterbores for socket head screws; ISO fits for machined parts
var process: unknown | | Manufacturing | unknown=not decided yet (agent asks), 3D printing=3D printing, CNC milling=CNC milling, laser cutting=Laser cutting, plasma cutting=Plasma cutting, sheet metal=Sheet metal
var hole_fit: medium | | Clearance holes to ISO 273 | fine=fine, medium=medium, coarse=coarse
var min_gap: 0.2 | mm | Minimum gap between parts | 0..5
---
# Skill: Tolerances and fits

Every real part deviates from its nominal size. Design so that parts still fit when they do.

## General rules

- Manufacturing process from the app: **{{process}}**. If it is "unknown" and `NOTES.md` does not say how the parts
  are made, ask: the clearances depend on it. The skill for the process (if you follow one) has more specific values,
  they take precedence over this one.
- Every clearance, fit and allowance is a named constant at the top of `model.py` or in `parts/params.py`
  (`SCREW_CLEARANCE`, `LID_GAP`), never hidden in expressions.
- Mating faces never share the exact same coordinate: a defined gap, or a defined overlap for a press fit.
- Parts that must not touch keep at least {{min_gap}} mm distance (`MIN_GAP = {{min_gap}}`).
- Dimension from the functional faces: a hole follows the part it has to meet, not an arbitrary outer edge.
- Tight tolerances only where they matter. Everything else: general tolerance ISO 2768-m.

## Checking clearances in code

- Interference: `a.intersect(b).val().Volume()` is (close to) 0 for parts that must not touch, also for a part and a
  reference (`role="reference"`).
- Smallest gap in mm: `a.val().distance(b.val())`, at least {{min_gap}} mm.
- Tell the user the critical gaps. Remove the debug output afterwards.

## Holes for metric screws

Clearance holes after ISO 273 and tap drills for coarse threads, in mm. The user chose the **{{hole_fit}}** column.

| Thread | Fine | Medium | Coarse | Tap drill |
|---|---|---|---|---|
| M2 | 2.2 | 2.4 | 2.6 | 1.6 |
| M2.5 | 2.7 | 2.9 | 3.1 | 2.05 |
| M3 | 3.2 | 3.4 | 3.6 | 2.5 |
| M4 | 4.3 | 4.5 | 4.8 | 3.3 |
| M5 | 5.3 | 5.5 | 5.8 | 4.2 |
| M6 | 6.4 | 6.6 | 7.0 | 5.0 |
| M8 | 8.4 | 9.0 | 10.0 | 6.8 |

## Counterbores for socket head screws

ISO 4762 (DIN 912), head flush, with some room around it:

| Thread | M2 | M2.5 | M3 | M4 | M5 | M6 | M8 |
|---|---|---|---|---|---|---|---|
| Counterbore Ø | 4.4 | 5.5 | 6.5 | 8.0 | 10.0 | 11.0 | 15.0 |
| Depth | 2.4 | 2.9 | 3.4 | 4.4 | 5.4 | 6.4 | 8.6 |

In CadQuery: `.cboreHole(diameter, cboreDiameter, cboreDepth)`. Countersunk screws (ISO 10642, 90°):
`.cskHole(diameter, cskDiameter, 90)`.

## Measure instead of looking

A picture shows that a model looks right, not that it is right. `soma inspect` measures it and needs no app:

```bash
soma inspect --json                                  # the whole model, one document
soma inspect --parts Lid --json                      # one part
soma inspect --strict                                # exit code 1 on a geometric error
```

It gives volume, surface area, bounding box, centre of mass and the number of solids, shells, faces, edges and
vertices — per part and in total — plus a list of problems. The document has a fixed schema (`soma.inspect/1`), so a
number can be compared between two builds.

- **A part with `topology.solids` 0 has no volume.** It is a shell or a bare face; a cut on it silently does nothing.
  Fix that before anything else.
- **`valid: false`** means OCCT found a broken face or edge, usually after a cut or a fillet. Do not export it.
- **`multiple_bodies`**: two solids in one part. Either two parts that should be separate, or a boolean that missed.
- Write the expected volume into the code as an assertion while you work out a fit; delete it afterwards. Two numbers
  that should match (a bore that must take a shaft, a pocket that must hold a nut) are worth checking numerically, not
  by eye.

`soma analyze clearance` finds tight gaps and `soma analyze thickness` thin walls; `soma inspect` is the cheap summary
in front of them.

## Mesh tolerance follows the part size

The mesh for the viewer is not fixed: SOMA uses about 0.0004 × the diagonal of the part, clamped to 0.01–0.2 mm. The
same rule applies to `soma export --tolerance`: a fixed 0.01 mm is pointless on a 300 mm part and makes the file
enormous, while 0.05 mm on a 20 mm part throws away the shape.

| Largest dimension of the part | Reasonable `--tolerance` |
|---|---|
| up to 50 mm | 0.02 mm |
| 50 to 200 mm | 0.05 mm |
| 200 to 500 mm | 0.1 mm |
| over 500 mm | 0.2 mm or coarser |

STEP, IGES and BREP are exact and take no tolerance at all. Only mesh formats (STL, 3MF, AMF, OBJ, GLB, GLTF) do.

## Fits for machined parts (ISO 286)

- Shaft turning or sliding in a hole: H7/g6. Located, assembled by hand: H7/h6. Press fit: H7/p6.
- Model the nominal size and write the fit as a comment and in `NOTES.md` (`BORE = 8  # H7`). Do not build the
  tolerance band into the geometry.
