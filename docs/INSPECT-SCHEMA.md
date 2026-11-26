# `soma inspect` — the JSON document

**Schema:** `soma.inspect/1` · **Command:** `soma inspect` · **Module:** `python/soma/inspection.py`

A picture shows that a model *looks* right. This document is how a test, a CI job or an agent finds out whether it
*is* right — without opening the viewer and without parsing human-readable text.

```bash
soma inspect                      # table in the terminal
soma inspect --json               # the document, one line
soma inspect --out report.json    # the document, indented, for a diff
soma inspect --step exports/x.step
soma inspect --density 1.24       # mass estimate for PLA
soma inspect --overlaps           # also measure which parts cut into each other
soma inspect --strict             # exit code 1 when the geometry has an error
```

The same command measures the model (`model.py` is executed, nothing is written) and a finished file. That is what
makes a round-trip check possible: inspect the model, inspect the export, compare `totals.volume` and
`totals.bounds`. The two numbers come from different code paths — OCC's BRep directly, and a STEP file that went
through the writer — so a match is evidence, not a tautology.

---

## 1. Document

```json
{
  "schema": "soma.inspect/1",
  "soma": "1.0.0",
  "units": "mm",
  "source": { ... },
  "bounds": { ... },
  "totals": { ... },
  "parts": [ ... ],
  "overlaps": [ ... ],
  "checks": { "ok": true, "issues": [] },
  "ok": true
}
```

| Field | Type | Meaning |
|---|---|---|
| `schema` | string | `soma.inspect/1`. Additive changes bump the minor part, renaming or removing a field the major part. |
| `soma` | string | Version of SOMA that produced the document. |
| `units` | string | Always `"mm"`. SOMA models in millimetres, Z up. |
| `source` | object | Where the geometry came from (Section 2). |
| `bounds` | object \| null | Box around everything (Section 3). |
| `totals` | object | Sums over all parts (Section 4). |
| `parts` | array | One entry per part (Section 5). |
| `overlaps` | array | Only with `--overlaps`: pairs that cut into each other (Section 6). |
| `checks` | object | Measured problems (Section 6). |
| `ok` | bool | `checks.ok`. The only field a caller has to read for a pass/fail gate. |

Numbers are rounded to 6 decimals (4 for volume and area), `-0.0` is normalised to `0.0`, and `nan`/`inf` never
appear: an unmeasurable value is `null`. There is no timestamp and no absolute path in the document, so two runs on
the same geometry produce identical output.

---

## 2. `source`

```json
{ "kind": "model", "project": "gearbox", "entry": "model.py",
  "parameters": [ { "name": "BORE", "value": 38.0, "source": "user", "unit": "mm", "group": "Crank train" } ] }
```

```json
{ "kind": "file", "file": "gearbox.step", "format": "step" }
```

| Field | Kind | Meaning |
|---|---|---|
| `kind` | both | `"model"` or `"file"`. |
| `project` | model | Folder name of the project (not the path). |
| `entry` | model | Entry point that was executed. |
| `parameters` | model | Every `param()` of the model: `name`, effective `value`, `source` (`"code"` or `"user"`), `unit`, `group`. |
| `file` | file | File name without the folder. |
| `format` | file | `step` or `brep`. |

`parameters[].source == "user"` means the value came from `parameters.json`, not from the code — worth knowing when
a number does not match the source.

---

## 3. `bounds`

```json
{ "min": [-20.0, -15.0, -2.5], "max": [20.0, 15.0, 9.5],
  "size": [40.0, 30.0, 12.0], "center": [0.0, 0.0, 3.5] }
```

`null` when nothing in the document has geometry. `size` is `max - min` per axis. A part that sticks out shows up
here before any export is written.

---

## 4. `totals`

| Field | Meaning |
|---|---|
| `parts` | Number of entries in `parts`. |
| `solids` | Sum of `parts[].topology.solids`. The number that must match the number of bodies in a STEP file. |
| `faces`, `edges` | Sums. Useful as a cheap regression signal: a change in topology moves them. |
| `volume` | Sum of the part volumes in mm³, or `null` if no part has volume. |
| `area` | Sum of the surface areas in mm². |
| `mass_g`, `density_g_cm3` | Only with `--density`. `volume / 1000 × density`. |
| `note` | Present when `parts > 1`: the sums add up overlapping parts twice. |

---

## 5. `parts[]`

```json
{ "name": "Lid", "step_name": "Lid", "role": "part", "group": ["Housing"],
  "bounds": { ... },
  "topology": { "solids": 1, "shells": 1, "faces": 6, "edges": 12, "vertices": 8 },
  "volume": 3600.0, "area": 1560.0, "center_of_mass": [0.0, 0.0, 8.0],
  "valid": true, "closed": true,
  "designation": "ISO 4762 M3x10" }
```

| Field | Meaning |
|---|---|
| `name` | Name as registered with `add_part` (or the assembly node for a STEP file). |
| `step_name` | ASCII name used inside STEP files (umlauts transliterated). |
| `role` | `part`, `reference` or `hardware`. Purchased parts are `hardware`; they are not in `export --all`. |
| `group` | Group path as a list, e.g. `["Housing", "Screws"]`. Empty for a part at the top. |
| `bounds` | Box of this part, same shape as the document's `bounds`, or `null`. |
| `topology.solids` | Closed bodies. **0 means the part has no volume.** More than 1 in one part is usually a mistake. |
| `topology.shells`, `.faces`, `.edges`, `.vertices` | Counts. |
| `volume` | mm³, `null` when `solids == 0` (a face has no volume; OCCT would return a meaningless number). |
| `area` | mm² of the whole surface. |
| `center_of_mass` | Centroid of the volume, `null` when there is none. |
| `valid` | `isValid()` — OCCT's BRepCheck. `false` means a broken face or edge, usually after a bad cut or fillet. `null` with `--fast`. |
| `closed` | Every shell of the part is closed. `null` for a bare face (no shell) and with `--fast`. |
| `designation` | Only for standard parts from `soma.fasteners`: the full designation, e.g. `ISO 4762 M3x10`. |

For a STEP or BREP file the entries are solids, not parts: `role` is always `part`, `group` is empty, and the name
comes from the assembly node when it can be matched to a body. If the names cannot be matched one to one, the
entries are `Solid 1`, `Solid 2`, … — a wrong name is worse than a generic one.

---

## 6. `overlaps` and `checks`

### `overlaps` (only with `--overlaps`)

```json
"overlaps": [ { "a": "Shaft", "b": "Ring A", "volume": 4.2273, "thickness": 0.1298 } ]
```

One entry per pair of parts whose solids really occupy the same space, sorted by name. `thickness` is `2 V / A` of
the common volume, which turns a volume into a depth: a flat sliver along a contact face has plenty of volume and no
depth, a needle has depth and no volume. A pair is only reported when **both** are above the noise floor
(`volume > 1e-3 mm³` **and** `thickness > 0.01 mm`), so parts that merely touch in a face are not reported.

Each pair also becomes an `error` in `checks.issues` (code `overlap`), so `--overlaps --strict` is a gate in CI. The
measurement costs one boolean intersection per candidate pair, which is why it is opt-in: a bounding-box test throws
away most pairs first, but a model with a hundred parts that all share a box is still a hundred intersections.
Reference parts (`role="reference"`) are left out — they are brought along to measure against, so overlapping them is
intended.

Two overlaps are not defects and both have a reason:

- **A press fit** is nominal in the model, so it overlaps by nothing. If it shows up here, the bore is drawn at the
  nominal size and the shaft at its upper limit, which is a drawing error, not a fit.
- **A circlip in its free state** is smaller than its own groove (`d3 < d2`), so it always overlaps the shaft by
  `(d2 - d3) / 2`. Use `RetainingRing(..., mounted=True)` in an assembly that measures interference.

### `checks`

```json
{ "ok": false,
  "issues": [ { "level": "error", "code": "no_solid", "part": "Surface", "message": "..." },
              { "level": "warning", "code": "duplicate_bounds", "part": "Dup2", "message": "..." } ] }
```

`ok` is `false` only for `level: "error"`. Warnings are hints, not failures.

| Code | Level | Meaning |
|---|---|---|
| `invalid_shape` | error | `isValid()` is false: a broken face or edge. |
| `no_solid` | error | No closed body. Error for a part, **warning for a reference** (a reference surface is legitimate). |
| `zero_volume` | error | Has a solid but the volume is 0. |
| `overlap` | error | Only with `--overlaps`: this part cuts into another one. |
| `multiple_bodies` | warning | More than one solid in one part. Intentional, or two parts that should be two entries? |
| `open_shell` | warning | A shell is not closed. Booleans on it are unreliable. |
| `no_geometry` | warning | The part carries no geometry at all. |
| `duplicate_bounds` | warning | Identical bounding box as another part: a copy nobody wanted, or a part placed twice. |

The checks are deliberately cheap and deterministic. Interference between parts is measured only when asked for
(`--overlaps`), because it is the one check whose cost grows with the square of the part count. A comparison against
an expected value is not here either: that belongs to the caller, which is exactly what `totals` is for.

---

## 7. Recipes

**Guard a pull request against a broken model.**

```bash
soma build && soma inspect --strict
```

**Check that an export is complete.**

```bash
soma export --assembly --format step
soma inspect --json --out model.json
soma inspect --step exports/model.step --json --out export.json
python - <<'PY'
import json
a, b = (json.load(open(f)) for f in ("model.json", "export.json"))
assert a["totals"]["solids"] == b["totals"]["solids"], "bodies lost in the export"
for k in ("volume",):
    assert abs(a["totals"][k] - b["totals"][k]) < 1e-3 * a["totals"][k], f"{k} changed"
print("export matches the model")
PY
```

**Regression test on geometry.**

```bash
soma inspect --json > before.json     # before the change
soma inspect --json > after.json
diff <(python -m json.tool before.json) <(python -m json.tool after.json)
```

**Mass and material cost.**

```bash
soma inspect --density 1.24 --json | python -c "import json,sys; print(json.load(sys.stdin)['totals']['mass_g'], 'g')"
```

**Gate an assembly on nothing cutting into anything else.**

```bash
soma inspect --overlaps --strict          # exit code 1 when two parts share space
soma inspect --overlaps --json | python -c "import json,sys; [print(o) for o in json.load(sys.stdin)['overlaps']]"
```

---

## 8. What is not measured (yet)

- **Interference between parts** by default: it needs pairwise booleans, so it is behind `--overlaps` (Section 6).
  `soma analyze clearance` gives the sampled version, as a map over the surfaces.
- **Wall thickness.** `soma analyze thickness`.
- **Minimum radius, draft angle, overhang.** `soma analyze overhang` covers overhang only.
- **Thread length of partially threaded screws.** Not modelled at all; see `docs/FASTENERS-INVENTORY.md`, gap G4.

These belong to `soma analyze`, which already has a result format of its own. `inspect` stays the cheap, exact,
whole-model summary.
