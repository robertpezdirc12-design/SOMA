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

13 of the 48 files in `bd_warehouse/src/bd_warehouse/data/` are present.

| Present | Not present (relevant) |
|---|---|
| `button_head_parameters.csv`, `clearance_hole_sizes.csv`, `countersunk_head_parameters.csv`, `drill_sizes.csv`, `heatset_nut_parameters.csv`, `hex_head_parameters.csv`, `hex_nut_parameters.csv`, `nominal_screw_lengths.csv`, `plain_washer_parameters.csv`, `setscrew_parameters.csv`, `socket_head_cap_parameters.csv`, `square_nut_parameters.csv`, `tap_hole_sizes.csv` | `pan_head_parameters.csv`, `cheese_head_parameters.csv`, `low_profile_parameters.csv`, `shoulder_screw.csv`, `hex_head_with_flange_parameters.csv`, `hex_nut_with_flange_parameters.csv`, `domed_cap_nut_parameters.csv`, `brad_tee_nut_parameters.csv`, `chamfered_washer_parameters.csv`, `internal_tooth_lock_washer_parameters.csv`, `din471.csv`, `din472.csv`, `shaft_key_parameters.csv`, `o-ring_parameters.csv`, `single_row_deep_groove_ball_bearing_parameters.csv` (+3 bearing tables), `imperial_set_screw_parameters.csv`, `metric_set_screw_parameters.csv` |

`drill_sizes.csv` is present but only used to resolve heat-set insert holes (`_drill_mm`).

Checked: all 13 files are read by the module, there is no dead table. The copy is lean, not accidental.

---

## 2. Gaps

Ordered by how often a mechanical design actually needs the part, not by how easy it is to add.

### P1 — blocks ordinary work

**G1. Bearings: nothing at all.** `bd_warehouse.bearing` covers deep-groove, angular-contact, cylindrical-roller
and tapered-roller bearings, plus the four tables. A 608-2RS or a 6001 is the second most common purchased part
after screws, and today the user has to model it by hand or import a STEP. This is the single largest hole.

**G2. No bill of materials.** `HeatSetInsert` stores `part_number` (`fasteners.py:835`), and `registry.py` marks
standard parts with `role="hardware"`. Nothing ever reads either for a BOM: `grep part_number` finds exactly one
hit, the assignment. `soma export --all` deliberately skips hardware, so the purchased parts exist in the model
and then vanish from every output. A `soma bom` command that groups `hardware` parts by designation and count is
a small change with a large effect, and it is the prerequisite for any "order these parts" workflow.

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

### Recommended order

1. **G2 (BOM)** — smallest change, unlocks every purchasing workflow, uses data already in the registry.
2. **G1 (bearings)** — largest missing family, one new module + four tables.
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
