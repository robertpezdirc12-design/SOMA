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

### 1.3 Data tables

15 of the 42 files in `bd_warehouse/src/bd_warehouse/data/` are present.

| Present | Not present (relevant) |
|---|---|
| `button_head_parameters.csv`, `clearance_hole_sizes.csv`, `countersunk_head_parameters.csv`, `drill_sizes.csv`, `heatset_nut_parameters.csv`, `hex_head_parameters.csv`, `hex_nut_parameters.csv`, `nominal_screw_lengths.csv`, `plain_washer_parameters.csv`, `setscrew_parameters.csv`, `socket_head_cap_parameters.csv`, `square_nut_parameters.csv`, `tap_hole_sizes.csv`, `single_row_deep_groove_ball_bearing_parameters.csv`, `single_row_capped_deep_groove_ball_bearing_parameters.csv` | `pan_head_parameters.csv`, `cheese_head_parameters.csv`, `low_profile_parameters.csv`, `shoulder_screw.csv`, `hex_head_with_flange_parameters.csv`, `hex_nut_with_flange_parameters.csv`, `domed_cap_nut_parameters.csv`, `brad_tee_nut_parameters.csv`, `chamfered_washer_parameters.csv`, `internal_tooth_lock_washer_parameters.csv`, `din471.csv`, `din472.csv`, `shaft_key_parameters.csv`, `o-ring_parameters.csv`, `single_row_angular_contact_ball_bearing_parameters.csv`, `single_row_cylindrical_roller_bearing_parameters.csv`, `single_row_tapered_roller_bearing_parameters.csv`, `imperial_set_screw_parameters.csv`, `metric_set_screw_parameters.csv` |

`drill_sizes.csv` is present but only used to resolve heat-set insert holes (`_drill_mm`).

Checked: all 13 files are read by the module, there is no dead table. The copy is lean, not accidental.

---

## 2. Gaps

Ordered by how often a mechanical design actually needs the part, not by how easy it is to add.

### P1 — blocks ordinary work

**G1. Bearings: nothing at all.** ✅ **Done** — `Bearing` in `soma.fasteners` (see §5). A 608-2RS or a 6001 is the
second most common purchased part after screws, and it had to be modelled by hand or imported as STEP. Now:
`Bearing("608", at=(0, 0, 6))`, 56 catalogue numbers, one body each, bore and outside diameter exact, catalogue mass.
What it does not do: bores above 10 mm (the tables stop at the 6000/6200/6300 sizes), angular-contact and roller
bearings (tables not copied — see G1a), and chamfers.

**G1a. Roller and angular-contact bearings.** `single_row_cylindrical_roller_bearing_parameters.csv`,
`single_row_tapered_roller_bearing_parameters.csv` and `single_row_angular_contact_ball_bearing_parameters.csv` exist
upstream and were deliberately **not** copied: no code reads them, and a CSV in `data/` that nothing reads is the exact
failure this inventory warns about in §4. Adding them means rollers (cylinders and cones) instead of balls and, for the
tapered ones, a cone angle from `SKT:a`. Do it when a model needs one, not before.

**G2. No bill of materials.** ✅ **Done** — `soma bom` (see `docs/BOM.md`). `HeatSetInsert` stores `part_number`
(`fasteners.py:835`), and `registry.py` marks standard parts with `role="hardware"`; nothing read either, and
`soma export --all` deliberately skips hardware, so a purchased part existed in the model and then vanished from
every output. The command now groups purchased parts by designation with a count, lists own parts with volume and
mass, and writes CSV for a spreadsheet. What it still cannot do: prices, and the material of a purchased part (the
model has a display colour, not a material).

**G3. Head shapes that fixtures use daily are missing.** No low-profile socket head (DIN 7984), no shoulder screw
(ISO 7379), no pan head, no cheese head. Shoulder screws in particular are the standard locating element in jigs,
and modelling one by hand is exactly the kind of work a standard-parts library exists to remove.

**G4. `ISO 4014` / `DIN 931` are modelled as fully threaded.** Both are partially threaded in reality: the shank
below the head is plain, the thread starts after a defined length. `SCREWS` maps all three hex standards to the
same `head="hex"` cylinder path (`_screw_local`), so `Screw.lengths` and the clamping length are right but the
thread length is not represented. For a viewer this is invisible; for a BOM, a drawing note or a FEM bolt it is
wrong. Either add `thread_length` from `hex_head_parameters.csv` and expose it, or document the simplification
explicitly in the `standard-parts` skill.

### P2 — needed regularly, cheap to add

**G5. Retaining rings (DIN 471 / DIN 472).** Tables are in bd_warehouse, geometry is a swept profile. Common on
any shaft with a bearing.

**G6. Shaft keys and keyways (DIN 6885).** `shaft_key_parameters.csv` is present in bd_warehouse and unused here.
A key without a matching keyway tool is half a feature, so this needs both the part and a `keyway()` cut tool —
the same pattern `Nut.trap()` already establishes.

**G7. O-rings.** Four tables (sizes, static gland, dynamic gland). The gland dimensions are the valuable part: a
correct O-ring groove is hard to get right by hand, and SOMA already has the cut-tool pattern to express it.

**G8. Nut and washer variants.** Flange nut, domed cap nut, T-nut (woodworking), unchamfered hex nut, chamfered
washer, internal-tooth lock washer. Each is one table row set plus a small geometry branch; `NUTS` and `WASHERS`
are dictionaries built for exactly this.

**G9. `Washer` has no `trap()`.** `Nut` and `HeatSetInsert` both provide the pocket for their own part;
`Washer` does not, so a recessed washer has to be cut by hand. Inconsistent with the rest of the API.

**G10. `tap_hole()` only reads the `Soft` column.** `_tap_drill()` hardcodes `("Soft",)` from
`tap_hole_sizes.csv`. Tapping steel needs the harder-material drill, which is a different value. A `material=`
argument (`"soft"` default, `"hard"`) closes this without touching the tables.

**G11. Fine pitches cannot be expressed, and the error misleads.** `COARSE_PITCH` (`fasteners.py:53`) has one pitch
per diameter, and `_SIZE` accepts only `M<d>` or `M<d>x<length>` — a second `x` group does not parse. So
`Screw("ISO 4762", "M10x1.25x40")` fails with "cannot read the size", while `Screw("ISO 4762", "M10x1.25")` is read
as **M10 with length 1.25 mm** and rejected with "1.25 mm is not a standard length". Verified against the module.
The limitation is acceptable (SOMA models no threads), but the message sends the user looking for a length that was
never meant. Detect a pitch-shaped second group and say "fine pitches are not supported, use the coarse thread or
model it yourself".

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

Status: G2 and G1 are implemented (`soma bom`, `Bearing`). The rest are open, in the order above.

### Recommended order

1. ~~**G2 (BOM)**~~ — **done** (`soma bom`). It was the smallest change and it unlocked every purchasing workflow.
2. ~~**G1 (bearings)**~~ — **done** (`Bearing`). It was **not** "one new module + four tables" as written here first:
   it became one class in `fasteners.py` and **two** tables. Reasons in §5 — the export path and the data itself both
   decided that, not taste.
3. **G3, G5, G6** — fixture and shaft work; each is one table plus one geometry branch.
4. **G7, G8, G9, G10, G11** — consistency and correctness of what already exists.
5. **G12–G14** — only against a concrete model that needs them.

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

**Two tables, not four.** Angular-contact and roller bearings were dropped from the copy (G1a) because nothing reads
them yet. The two that stayed are the ones `Bearing` reads, which is the rule §4 states.

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
