# Notes — bearing block

The example `npm run test:assembly` builds. It is not here to be beautiful: it is the smallest model in which every
standard part has to fit a part that was modelled by hand, so the numbers that matter are the ones *between* parts.

## What it is

A housing with a stepped through-bore. Two 6200 deep groove ball bearings (10 × 30 × 9) sit in the 30 mm bores at
either end, the 26 mm bore between them leaves a shoulder at each end. Both bearings are pressed onto one shaft; each
inner ring is held on the shaft by a DIN 471 circlip that sits against it on the inside, so bearing A is pushed one way
and bearing B the other. That is what locates the shaft. The output stub carries a DIN 6885 form A key.

## Why each decision is what it is

| Decision | Why |
|---|---|
| Two circlips, both on the **inside** of their bearing | A circlip can only push one way. Put both on the same side and the shaft is free to slide the other way. |
| Shoulders in the housing, not a cover | The step in the bore is cheaper than a cover and needs no screws. The outer rings are held by the housing, the inner rings by the shaft — the load path is closed without a third part. |
| `mounted=True` on both circlips | A 10 mm ring is 9.3 mm in its free state and its groove is 9.6 mm: a free ring sticks 0.15 mm into the shaft all the way round, and the interference measurement reports exactly that (4.23 mm³ per ring). `mounted=True` builds it at the groove diameter, which is the ring as it sits. |
| The key needs `direction` and `angle` | The key lies in the plane of `at` with its length along local X. The shaft runs along Z, so the key has to be turned onto it: `direction="-Y", angle=90`. Without that it lies *across* the shaft and half of it is inside the shaft (8.87 mm³). |
| `SEAT = bearing.width`, `MID = HOUSING_D - SEAT` | Derived, not typed. Change the bearing and both shoulders move with it; the housing depth stays the only free number. |
| The key is 12 mm behind the housing | Clear of bearing B, and the stub is long enough to carry it. Both are in `model.py` as `KEY_Z` and `STUB`. |

## Checked

`soma build`, then `soma inspect --overlaps`: seven parts, seven solids, all valid and closed, no pair overlapping.
The shaft volume is the proof that the features are really there — a full Ø10 × 79 cylinder is 6205.3 mm³, and the
measured 6090.9 is that minus two ring grooves (13.5 mm³) and one 20 mm keyway (100.2 mm³).

`npm run test:assembly` repeats all of this and then builds two deliberately wrong versions to make sure the
measurement bites: the same model with free-state rings (two overlaps) and with the key unturned (one overlap). It
also measures the exported STEP file, because `inspect --step --overlaps` is a second code path and an export that
merges two bodies is the mistake you only notice in the other program. And it checks the opposite case on a model
built for it: a screw through a washer and a nut, where **nothing** may overlap — SOMA draws no threads, so the nut's
bore is nominal and the screw passes through it. If that ever changed, every bolted assembly would light up.

## The sheet

`drawings/assembly.py` is an A3 sheet at 1:1: a full section A-A along the shaft axis, a plan below it, six
dimensions, five item numbers and the parts list. `soma drawing build assembly` writes `output/drawings/Bearing_block.pdf`
and `.dxf`, and `npm run test:assembly` requires the sheet to build **without a warning** and reads the parts list out of
the DXF to compare it with `soma bom` row for row. A parts list that goes stale now fails a test instead of shipping.

Where the dimensions go was decided by the geometry, not by taste, and the section is the reason:

| Dimension | Why there |
|---|---|
| 90 below the part | The shaft leaves the housing at z = -15, so a line closer than that crosses it. |
| 34 on the left | On the right the item numbers fan out; on the left the housing ends and nothing else is there. |
| 15 between the shaft lines | It measures from the housing face (z = 0) to the shaft end (z = -15), and both points lie on the shaft's silhouette. |
| 50 on the left of the plan | Same reason, and it lines up with the 34 above it. |
| Ø30 in the plan | The bore is a circle there. In the section it is two parallel lines and `diameter()` would find no circle. |
| Ø10 with a leader | 10 mm of shaft are 13 mm of text: it cannot stand between the arrows, so it stands outside with a leader. |

The plan shows the bearing's rings and balls because the top bearing's face is flush with the housing's top face
(`MID = HOUSING_D - SEAT`), so they are not hidden — they are what you see when you look down the bore.

## What this example found

Four gaps, all closed:

- `soma inspect` measured each part and nothing between parts, so an assembly could be wrong and still report
  `ok: true`. It now has `--overlaps`, and the MCP tool `soma_inspect` takes `overlaps: true`.
- The `ShaftKey` example in the skill and in `docs/FASTENERS-INVENTORY.md` left out `direction` and `angle`, which is
  right only for a shaft that lies along X with its keyway facing up. For the usual case — a shaft along Z — it
  produced a key across the shaft. Both are fixed.
- A circlip in its free state is smaller than its groove, so it always overlaps its shaft. That is how the part is
  made, but it made every interference measurement on a shaft report a collision. `RetainingRing(..., mounted=True)`
  is the ring as it sits.
- `view.dim(..., text_at=...)` moved the dimension text and left the dimension line where it was, so the text stood
  beside the dimension with nothing in between — the fix the checker itself suggests ("move the text with
  `text_at=`") produced a broken-looking sheet for any text longer than the distance it measures. There is
  `leader=True` now (`DIMTMOVE=1`), and `app/resources/skills/drawings.md` says when it is needed.

Still open, and deliberately: the ring's lugs are a rectangle, not the teardrop a maker draws. DIN leaves the shape
open, so a drawing of this ring will differ from the model in the lugs and nowhere else.
