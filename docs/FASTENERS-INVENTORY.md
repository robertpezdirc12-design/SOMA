# Fasteners inventory — SOMA vs bd_warehouse

**Status:** Phase A of the SOMA extension plan · **Prepared:** 2026-11-26 · **Scope:** inventory only, no code changes

> This document answers one question: **what does SOMA's standard-parts library cover today, and what is
> actually missing?** It exists so that the following phases do not add a second, duplicate fastener library.
> Every claim below was checked against the files in this repository, not against the plan document.

---

## 1. What SOMA has

`python/soma/fasteners.py` (858 lines) is **own code**, not a wrapper. It does not import `bd_warehouse` or
`cq_warehouse`. What it does take from `bd_warehouse` is the **dimension tables**, copied verbatim into
`python/soma/data/fasteners/` (see `QUELLE.md`: bd_warehouse 0.3.0, commit `eed2da1`, 2026-09-21).

This distinction matters for the plan: **there is nothing to "integrate" from `cq_warehouse`.** The library is
already there in the only form SOMA wants — tables plus own geometry code. Adding `cq_warehouse` as a dependency
would duplicate `Screw`, `Nut`, `Washer` and `HeatSetInsert` and pull a second, incompatible API into the runtime.

### 1.1 Public API

| Class / function | Covers | Placement helpers |
|---|---|---|
| `Screw(standard, size, length, ...)` | 7 standards, 5 head shapes | `at`, `direction`, `on` (seat search), `sunk`, `angle`, `check_length` |
| `Nut(standard, size, ...)` | 4 standards, hex + square | `at`, `direction`, `on`, `sunk`, `angle` |
| `Washer(standard, size, ...)` | 3 standards | `at`, `direction`, `on`, `sunk`, `angle` |
| `HeatSetInsert(size, length, brand=...)` | 5 brands | `at`, `direction`, `on`, `sunk`, `angle` |
| `lengths()`, `pick_length()` | standard length series | — |
| `standards()` | self-description of what exists | — |
| `_Part.clearance_hole()`, `.tap_hole()` | matching cut tools | `fit`, `depth`, `oversize`, `recess` |
| `Nut.trap()`, `HeatSetInsert.hole()` | matching cut tools | `clearance`, `slot`, `slot_length` |

Cut tools are the strongest part of the design and the main reason not to replace this module: a screw and the
hole it needs come from the same table row, so they cannot drift apart.

### 1.2 Standards covered

| Kind | Standards |
|---|---|
| Socket head cap | ISO 4762 |
| Button head | ISO 7380-1 |
| Countersunk | ISO 10642 |
| Hex head | ISO 4017, ISO 4014, DIN 931 |
| Set screw | ISO 4026 |
| Hex nut | ISO 4032, ISO 4033, ISO 4035 |
| Square nut | DIN 557 |
| Washer | ISO 7089, ISO 7091, ISO 7093 |
| Heat-set insert | ruthex, CNCKitchen, McMaster-Carr, Hilitchi, AE-SamZhihui |
| Shoulder screw | ISO 7379 |
| Low profile socket head | OpenBuilds series (not DIN 7984 — see G3) |
| Pan head, cheese head | ISO 1580, ISO 1207, ISO 7045 (cross recess) |
| Heads with a collar | DIN 967, ISO 7380-2, DIN 1662 (hex with flange) |
| Flange nut, domed cap nut | DIN 1665, DIN 1587 |
| Hex nut, unchamfered | ISO 4036 |
| Chamfered washer, internal-tooth lock washer, small washer | ISO 7090, DIN 6797, ISO 7092 |
| Rolling bearings | 100 catalogue numbers in five families: deep groove (open and capped), angular contact, cylindrical roller, tapered roller — bore 3–15 mm |
| Retaining ring | DIN 471 (shaft), DIN 472 (bore) |
| Parallel key | DIN 6885 form A |
| O-ring | ISO 3601, 349 sizes, eight cords, with the groove for shaft, bore and face seals |

### 1.3 Data tables

38 of the 48 files in `bd_warehouse/src/bd_warehouse/data/` are present, and every one of them is read by the
module. The copy is lean, not accidental: what is missing falls into two groups.

| Missing | Why |
|---|---|
| `raised_countersunk_oval_head_parameters.csv`, `imperial_set_screw_parameters.csv`, `metric_set_screw_parameters.csv`, `brad_tee_nut_parameters.csv` | No part needs them yet; the T-nut table is unusable (see G8) |
| `iso10664def.csv`, `iso_228_1.csv`, four plastic-bottle thread tables | Thread profiles and bottle threads — nothing in SOMA models a thread |

`drill_sizes.csv` is present but only used to resolve heat-set insert holes (`_drill_mm`).

One row was **corrected**, the only deviation from "copied unchanged": in `nominal_screw_lengths.csv` the ISO 1580
series read `2,2.5,3,4,5,68,10,…` — `68` for `6,8`. M3x6 and M3x8, two of the most common pan head screws there are,
were rejected as non-standard lengths. The series now reads `…,4,5,6,8,10,…`, and every other row was checked for
ascending values (only the two imperial rows repeat 6.25, and nothing reads them).

---

## 2. Gaps

Ordered by how often a mechanical design actually needs the part, not by how easy it is to add.

### P1 — blocks ordinary work

**G1. Bearings: nothing at all.** ✅ **Done** — `Bearing` in `soma.fasteners` (see §5). A 608-2RS or a 6001 is the
second most common purchased part after screws, and it had to be modelled by hand or imported as STEP. Now:
`Bearing("608", at=(0, 0, 6))`, 100 catalogue numbers in five families, one body each, bore and outside diameter
exact, catalogue mass. What it does not do: bores above 15 mm (the tables stop at the 6000/6200/6300 sizes), and
chamfers.

**G1a. Roller and angular-contact bearings.** ✅ **Done.** `single_row_angular_contact_ball_bearing_parameters.csv`,
`single_row_cylindrical_roller_bearing_parameters.csv` and `single_row_tapered_roller_bearing_parameters.csv` were
copied and are read: `Bearing("7200 BECBP")`, `Bearing("NJ 202 ECP")`, `Bearing("30302 J2")`. `kind` says what rolls
(`"ball"` or `"roller"`) and `family_key` which table the number came from.

Two things the tables decided, not taste:

- **The tapered width is `T`, not `B`.** Those rows carry both; `B` is the inner ring only, so a bearing built on `B`
  would be 1.25 mm too thin at 30302 and would not fit its housing. `BEARINGS["tapered"]` therefore declares
  `width_col="T"`, and the same entry declares `mass_col="kg"` because that table weighs in kilograms where the others
  weigh in `mass`.
- **A cone angle cannot be drawn, so it is not guessed.** The tapered table gives `a`, the distance from the bearing
  face to the cone apex — not an angle. The rollers are therefore cylinders, exactly as in the cylindrical family, and
  the docstring says so. What is exact is the envelope, which is what decides whether the part fits.

The angular-contact table has one placeholder row whose designation is an en-dash, and the roller table one that is
empty. Both are skipped by `_NOT_A_NAME`, the same rule the index uses.

**G2. No bill of materials.** ✅ **Done** — `soma bom` (see `docs/BOM.md`). `HeatSetInsert` stores `part_number`
(`fasteners.py:835`), and `registry.py` marks standard parts with `role="hardware"`; nothing read either, and
`soma export --all` deliberately skips hardware, so a purchased part existed in the model and then vanished from
every output. The command now groups purchased parts by designation with a count, lists own parts with volume and
mass, and writes CSV for a spreadsheet. What it still cannot do: prices, and the material of a purchased part (the
model has a display colour, not a material).

**G3. Head shapes that fixtures use daily are missing.** ✅ **Done.** `Screw` gains `"ISO 7379"`, `"OpenBuilds"`,
`"ISO 1580"` and `"ISO 1207"`. A shoulder screw is built as one revolve (head, shoulder, undercut, threaded end)
because the undercut is narrower than the thread and a fuse of cylinders would leave a bore there instead of a
groove; its length is the shoulder length as the standard defines it, so `shank_length` is longer and
`shoulder_hole()` cuts the pivot hole at the shoulder diameter, not the thread clearance.

The low profile series in the table is **OpenBuilds, not DIN 7984**: the head is lower (M3: 1.5 vs 2.0 mm) and wider
(5.68 vs 5.5 mm). It is registered under the name it really is, and asking for "DIN 7984" answers with that sentence
instead of quietly handing out different dimensions.

Pan head (ISO 1580), cheese head (ISO 1207) and the cross-recess pan head (ISO 7045) share one `head="pan"` branch —
a flat cylinder with a chamfered rim, which is what all three are. The slot is not modelled, so `Screw.key` returns
`None` for them instead of inventing a width across flats; the pan head is visibly the flat one (M3: 1.8 mm high
against 3.0 mm for a socket head).

**Heads with a collar** — `DIN 967` (pan with collar), `ISO 7380-2` (button with collar) and `DIN 1662` (hex with
flange) — are the same idea three times: the bearing surface is widened by a disc of `dc` and height `c`, and `k` is
the height over all, so the collar is the *lower part* of the head and not an addition to `k`. Getting that wrong
would make every one of them too tall by `c`. The collar is drawn as a cylinder: the 25° underside and the c/2 rim
rounding change neither the envelope nor the bearing face.

`head_diameter` now prefers `dc` when the table has one, because for these three the widest point is the collar, not
`dk` — for DIN 1662 M6 that is 13.6 mm against 6.93 mm across the hexagon corners.

`Washer("ISO 7092")` came in with the same batch: a small plain washer whose table is called
`cheese_head_washer_parameters.csv`, after its first user. ISO 7092 goes down to M1, which the rest of the washer
family does not.

**G4. `ISO 4014` / `DIN 931` are modelled as fully threaded.** ✅ **Done, as the second option.** The table has no
thread-length column, so there was nothing to read: `Screw.thread_length` now computes the standard value
(2d + 6 up to 125 mm, 2d + 12 up to 200 mm, 2d + 25 above) for those two standards and returns the full length for the
rest. The geometry is unchanged and always was a plain cylinder — SOMA models no threads — so this closes the gap for a
drawing note, a FEM bolt and a parts list, which is where the missing number actually hurt. Documented in the skill:
use `thread_length`, not `shank_length`.

### P2 — needed regularly, cheap to add

**G5. Retaining rings (DIN 471 / DIN 472).** ✅ **Done** — `RetainingRing("DIN 471", 20, at=...)`, both tables, all
86 + 88 sizes. The ring body, its width, the thickness and the gap are the table values, so it fits the groove it is
meant for; the lugs are rectangles with a plier hole, which is a drawing rather than a measurement (DIN leaves their
shape to the maker). `groove()` cuts the matching groove: floor at `d2`, width `m`, centred on the ring. `d4` is not
used — the column means different things in the two tables and is not guessed at.

`mounted=True` builds the ring at the groove diameter instead of the free one. The tables always have `d3 < d2` (a
10 mm ring: 9.3 free against a 9.6 groove), so a free-state ring overlaps the shaft by `(d2 - d3) / 2` all the way
round — how a circlip is made, but an assembly that measures interference sees a collision. Found while building
`docs/examples/bearing-block`; the default is unchanged, so nothing that was modelled before moves.

**G6. Shaft keys and keyways (DIN 6885).** ✅ **Done** — `ShaftKey("DIN 6885", 20, 40, at=...)` or `ShaftKey(20, 40)`,
form A with rounded ends, all 31 shaft sizes. The key sits in the shaft keyway: `at` is the point on the shaft
surface, it reaches `shaft_depth` in and `height - shaft_depth` out. `keyway("shaft")` cuts the milled groove with
rounded ends and `keyway("hub")` the broached one with square ends, each at the depth of the table.

The table's two depth columns were the open question: `t4` is the shaft groove and `t2` the hub groove. Verified
against all 31 rows — `t2 + t4` is always `h` plus 0.2 to 0.3 mm of clearance, and the assignment matches DIN 6885 for
the 2×2, 3×3 and 8×7 keys.

The key lies in the plane of `at` with its length along local X, so the placement has to turn it onto the shaft. For
the usual case — a shaft along Z, keyway on the +Y side — that is `direction="-Y", angle=90`. The example in this file
and in the skill used to leave both out, which is only right for a shaft along X with the keyway facing up; for a Z
shaft it produced a key lying across the shaft, half of it inside (8.87 mm³). Both examples are fixed.

**G7. O-rings.** ✅ **Done.** `ORing("025", at=...)`, 349 sizes from 001 to 475 and eight cord thicknesses, plus
`gland()` for the groove. Three tables, not four: a size table and two gland tables (static and dynamic), which is what
upstream has.

The size is the ISO 3601 dash number, **not a diameter** — 025 is 29.87 mm inside, 020 is 21.95 — so
`for_inner_diameter(30, 1.78)` answers the question a designer actually asks, and a size that does not exist is
rejected with that sentence rather than silently becoming another ring. The part is a torus at its nominal dimensions;
the 1–5 % stretch of a real installation is not modelled, and the docstring says so.

`gland(kind="shaft"|"bore"|"face", application="static"|"dynamic", backing_rings=0)` cuts the groove so that it and the
ring cannot disagree: for a shaft seal the groove floor *is* the ring's inner diameter, for a bore seal the bore *is*
its outer diameter, and for a face seal the groove floor is the ring's underside. Width and depth come from the gland
tables by cord thickness, the depth as the average of the table's min and max, and the groove floor is rounded with the
table's corner radius — a sharp corner cuts the ring. `gland_spec()` returns the numbers behind the tool (width, depth
range, radius, clearance, squeeze in mm and %) for a drawing or a check.

Two honest limits, both stated in `QUELLE.md`: the gland dimensions are the Apple Rubber design guide, not ISO 3601-2 —
bd_warehouse says so itself — and `backing_rings=1|2` is refused for cords under 1.78 mm, where the table has no width
for them.

**G8. Nut and washer variants.** ✅ **Done, except the T-nut.** `Nut` gains `"DIN 1665"` (hex with flange) and
`"DIN 1587"` (domed cap nut), `Washer` gains `"ISO 7090"` (chamfered) and `"DIN 6797"` (internal-tooth lock washer).
Two geometry branches each: the flange nut is the hexagon plus a disc at its seat, the cap nut a hemisphere on top of
the hexagon with the bore stopping at the dome — so it is genuinely closed, and a probe above the hexagon finds
material. The toothed washer is the ring plus `n` radial teeth reaching 30 % of the radial width into the bore; the
table's `n` column is used as the count.

`Nut.trap()` had to learn the shapes too, or the pocket would be wrong in a way that is only visible after cutting:
the flange gets a round pocket with the hexagon above it, the cap nut a round pocket up over the dome. A side slot is
refused for both with a sentence instead of silently cutting a slot a flange cannot pass through.

The **T-nut is not implemented on purpose.** `brad_tee_nut_parameters.csv` has three rows, one brand, identical
values for M6/M8/M10 and a 36 mm flange diameter on an M6 nut — a scraped product listing, not a standard. Upstream
keeps `BradTeeNut` commented out for the same reason. The file was deleted again rather than shipped unread.

The **unchamfered hex nut** is `Nut("ISO 4036")` — a table of its own, not ISO 4032 with the chamfer filed off, and
the nut is lower (M6: 3.2 against 5.2 mm). `Nut.chamfer` says which one you have.

**G9. `Washer` has no `trap()`.** ✅ **Done** — `washer.trap(clearance=0.2, depth=None)`, a round pocket of
`outer_diameter + 2 × clearance` and `thickness + clearance` deep, open to the surface when the washer is `sunk`.
Same pattern as `Nut.trap()`.

**G10. `tap_hole()` only reads the `Soft` column.** ✅ **Done** — `tap_hole(material="hard")` and
`tap_drill_for("hard")`; `tap_drill` still means soft, so nothing that already worked changed. M6 is 5.0 mm in
aluminium and 5.4 mm in steel, and a wrong drill in steel tears the tap.

**G11. Fine pitches cannot be expressed, and the error misleads.** ✅ **Done.** The limitation stays — SOMA models no
threads — but the message no longer lies. `"M10x1.25x40"` (pitch *and* length) is recognised as such, and
`"M10x1.25"` is no longer read as M10 with a 1.25 mm length: a second number below `min(3, d/2)` is treated as a
pitch. Both say that fine pitches are not supported and give the coarse designation to use instead.

### P3 — domain-specific, only on demand

**G12. Gears, sprockets, pulleys, chains.** `bd_warehouse` has `gear.py`, `sprocket.py`; the plan also lists
`cq_gears`. All of these are large, and `cq_gears` is explicitly unstable against the CadQuery version. Do not add
before there is a real model that needs it.

**G13. Flanges, pipes, bushings.** `flange.py`, `pipe.py`, `bushing.py`. Piping is a different engineering domain
from the parts SOMA is used for; adding it would be inventory without demand.

**G14. Imperial fasteners.** `imperial_set_screw_parameters.csv` plus the inch drill table. SOMA's unit system is
millimetres throughout (`AGENTS.md` rule 6); imperial parts would be the first exception. Only if users ask.

### Deliberately not a gap

**Threads are not modelled, and should stay that way.** `bd_warehouse.thread` has `IsoThread`, trapezoidal and
acme threads, and a helical thread on a 3D-printed part costs hundreds of thousands of triangles for a feature
that no slicer resolves. The current simplification (nominal-diameter shank, real tap drill) is the right trade.
This is worth stating once in the `standard-parts` skill so agents stop "improving" it.

---

## 3. What this means for the plan

| Plan item | Verdict after inventory |
|---|---|
| "`cq_warehouse` — first candidate for the parts library" | **Replace.** The tables are already in the repo and the geometry is own code. The remaining work is *adding missing part families*, not integrating a library. |
| "Compare what SOMA already covers, then test in an isolated project" | **Done by this document.** The comparison is Section 2; no isolated install is needed. |
| "Do not duplicate functionality" | Confirmed: importing `cq_warehouse` would duplicate all four classes. |
| Runtime change | **None needed.** New families are new modules in `python/soma/`, reading new CSVs from the same `data/fasteners/` folder under the same Apache-2.0 notice. No new pip dependency. |

Status: G1, G1a, G2, G3, G4, G5, G6, G7, G8, G9, G10 and G11 are implemented. G12 to G14 are open — the rest of the
list is done. G12 to G14 are the three that need a concrete model before they are worth the tables, which is why they
are still open on purpose.

### Recommended order

1. ~~**G2 (BOM)**~~ — **done** (`soma bom`). It was the smallest change and it unlocked every purchasing workflow.
2. ~~**G1 (bearings)**~~ — **done** (`Bearing`). It was **not** "one new module + four tables" as written here first:
   it became one class in `fasteners.py` and **two** tables. Reasons in §5 — the export path and the data itself both
   decided that, not taste.
3. ~~**G5, G6**~~ — **done** (`RetainingRing`, `ShaftKey`). Two tables plus two geometry branches, as estimated;
   the only surprise was which of the two key depth columns belongs to the shaft.
4. ~~**G3 (shoulder screw, low profile, pan head, cheese head)**~~ — **done**.
5. ~~**G9, G10, G11**~~ — **done**. Small, and each one removed a way to get a wrong number or a misleading error.
   **G4** went the documentation route: the table has no thread length to read.
6. ~~**G8 (nut and washer variants)**~~ — **done**, except the T-nut, which has no usable table (§G8).
7. ~~**G7 (O-rings)**~~ — **done** (`ORing`, `gland()`). Three tables, not four: a size table and two gland tables.
8. ~~**Check the rows, not the standards**~~ — **done** (`npm run test:tables`). Not on the list when this document was
   written, and it should have been: counting standards said "covered" while single rows were broken. It found three
   heat-set insert bugs on its first run.
9. ~~**G1a (roller and angular-contact bearings)**~~ — **done**. It was held back because "no code reads them"; once
   `Bearing` existed, the code did, and the tables were worth copying. The two things that mattered were `T` versus `B`
   for the tapered width and the fact that `a` is not an angle — both in §G1a.
10. ~~**An assembly, not a part**~~ — **done** (`docs/examples/bearing-block`, `npm run test:assembly`). Every suite up
   to here measured one part at a time, and a standard part is only right or wrong against the part it goes into. Two
   things fell out of it: `soma inspect` had no way to see two parts sharing space, and the documented `ShaftKey`
   example was only correct for a shaft along X.
11. **G12–G14** — only against a concrete model that needs them.

### Licensing note

Every table in `bd_warehouse/src/bd_warehouse/data/` is Apache-2.0 (Copyright 2024 Gumyr). Copying further
tables keeps the existing pattern: the CSV unchanged, the licence text beside it, and an entry in
`THIRD_PARTY_NOTICES.md` and `QUELLE.md`. No new licence obligation is created.

---

## 4. How to re-run this inventory

```bash
# what SOMA ships
ls python/soma/data/fasteners/

# what bd_warehouse has
curl -s https://api.github.com/repos/gumyr/bd_warehouse/contents/src/bd_warehouse/data | grep '"name"'

# what the code exposes
python -c "from soma.fasteners import standards; import json; print(json.dumps(standards(), indent=1))"

# the tables SOMA actually reads
grep -o '"[a-z_0-9]*\.csv"' python/soma/fasteners.py | sort -u
```

The last command is the one to trust: a CSV can sit in `data/` and be read by nothing.

### Does every row work, or only the ones someone tried?

Coverage counted in standards is not the same as coverage of rows. A table can be present, registered, documented and
still contain a row that the geometry cannot build — the ISO 1580 length series read `68` instead of `6,8` for as long
as nobody asked for an M3x8. `npm run test:tables` (`app/test/tables.mjs`) closes that gap: it builds **every row of
every table** and checks that each one gives exactly one valid solid with the dimensions the table itself claims.

| Class | Rows built |
|---|---|
| `Screw` | 211 |
| `Nut` | 113 |
| `Washer` | 158 |
| `RetainingRing` | 174 |
| `ShaftKey` | 31 |
| `ORing` | 349 |
| `Bearing` | 100 |
| `HeatSetInsert` | 143 |
| **Total** | **1279** |

Rows it skips are skipped for a stated reason: a row in a shared table that belongs to a different standard (the
`socket_head_cap_parameters.csv` row is ISO 4762 *or* ASME B18.3, never both), and the imperial rows, which SOMA does
not offer at all (§G14). Three rows are **refused on purpose** because they contradict themselves — the drill they name
is larger than the insert's outer diameter — and the suite pins them so a data fix upstream shows up as a failing check
instead of passing unnoticed.

The same suite also checks the three lists nobody tests while nobody uses them: `standards()` against the registries,
every `HINTS` entry against the names that really exist (a hint for a name that resolves can never fire), and every
`ALIASES` target.

### And do they fit the part they go into?

A part can be a perfect solid with exactly the table's dimensions and still be wrong, because the question a standard
part answers is "does it fit". `npm run test:assembly` (`app/test/assembly.mjs`) is that level: it builds
`docs/examples/bearing-block` — a housing, two 6200 bearings, two circlips, a shaft and a key — and measures the
**pairs**, not the parts, with `soma inspect --overlaps`. Two deliberately wrong copies of the same model prove the
measurement bites: free-state circlips and an unturned key are both caught with the volume and the depth.

That example is also where the two open items of this document were found, which is the argument for having it: rows
were covered and standards were covered, and a key could still be modelled lying across its shaft.

---

## 5. Bearings: what was decided

**No new module.** `Bearing` lives in `fasteners.py`, although a bearing is not a fastener. The reason is
"Export as CadQuery": `cqexport.py` embeds exactly **one** module — it reads `fasteners.py` as text, executes it into a
synthetic module, and copies every CSV from `data/fasteners/` into `_EMBEDDED`. That mechanism assumes a single
self-contained file with no relative imports. A separate `bearings.py` would have forced the export path to generalise
to two modules, which is a rewrite of a working feature and a much bigger change than the part family itself. One
class in `fasteners.py` reuses `_Part`, `_table`, `_cyl` and `_ring_local` unchanged and needed a single entry in
`cqexport.FASTENERS`.

The cost is a naming wart: `from soma.fasteners import Bearing`. It is recorded here rather than hidden, and renaming
`soma.fasteners` is not an option — it is public API in every model already written.

**Five tables, one class.** The three tables G1a left out were added once there was code to read them (G1a, done).
`BEARINGS` declares per family what differs — `kind` (`"ball"` or `"roller"`), `width_col` (`T` for the tapered
family) and `mass_col` (`kg` there, `mass` elsewhere) — so the class stays one branch of geometry and three columns
of table metadata, not five near-copies of the same code.

**What is exact and what is derived.** The data forced this split: `d1`/`D1` mean different things in the two tables,
so the ball diameter cannot be derived from them (details in `QUELLE.md` next to the tables).

| Value | Source |
|---|---|
| Bore `d`, outside diameter `D`, width `B` | table, exact — this is what a shaft and a housing touch |
| Chamfer `r12` | table, reported as `chamfer`, **not** modelled |
| Mass | table (`SKT:mass`, kg), exposed as `mass_g` |
| Ring wall thickness | derived from the radial space |
| Ball diameter and count | derived from the width (0.55 × B) and the pitch circle |

So the envelope is a catalogue part and the inside is a drawing of one. Two consequences worth knowing: the modelled
volume is smaller than the real part (the balls do not fill the raceway), and the catalogue mass is therefore the only
correct weight — which is why `mass_g` comes from the table and not from volume × density. A parts list should show
that number.

**One body per bearing.** The balls overlap both rings by 2 %, so the part is a single solid and `soma inspect` does not
report `multiple_bodies` for a purchased part that is fine.

**Test:** `app/test/bearings.mjs` — 15 checks, including all 56 designations against their table rows, one body and a
free bore for ten of them, the capped variants, the error that suggests `E2.608-2Z`, and that a model with two 608s
gives one BOM line with count 2.
