# `soma bom` — the bill of materials

**Schema:** `soma.bom/1` · **Command:** `soma bom` · **Module:** `python/soma/bom.py`

`soma export --all` deliberately skips purchased parts, so a screw exists in the model and then disappears from every
output. `soma.fasteners` already knows what it built and the registry already marks it — this command reads both.

```bash
soma bom                                  # two tables in the terminal
soma bom --json                           # the document, one line
soma bom --density 2.7 --csv order.csv    # mass and a table for a spreadsheet
soma bom --merge-identical                # one line for own parts that repeat
```

It runs `model.py` (like `soma export` and `soma inspect`) and writes nothing except the optional CSV. No build is
needed beforehand.

---

## 1. Document

```json
{
  "schema": "soma.bom/1",
  "soma": "1.0.0",
  "units": "mm",
  "source": { "project": "gearbox", "entry": "model.py" },
  "totals": { "parts": 17, "purchased": 12, "manufactured": 4, "references": 1,
              "items": 10, "volume": 20771.241, "mass_g": 56.083, "density_g_cm3": 2.7 },
  "purchased": [ ... ],
  "manufactured": [ ... ],
  "references": { "count": 1, "names": ["Board"] }
}
```

| `totals` field | Meaning |
|---|---|
| `parts` | Parts in the model, all roles. |
| `purchased` | Instances with `role="hardware"`, **counted**, not lines. |
| `manufactured` | Instances with `role="part"`, counted. |
| `references` | Parts with `role="reference"`. Not in either list. |
| `items` | Lines to order and make: `purchased.length + manufactured.length`. |
| `volume` | Sum of the manufactured volumes in mm³. |
| `mass_g`, `density_g_cm3` | Only with `--density`. Purchased parts are **not** weighed: their material is not in the model. |

## 2. `purchased[]`

```json
{ "kind": "Screw", "designation": "ISO 4762 M3x12", "part_number": null, "count": 4,
  "group": ["Hardware", "Screws"], "names": ["Screw 1", "Screw 2", "Screw 3", "Screw 4"] }
```

| Field | Meaning |
|---|---|
| `kind` | Class of the standard part: `Screw`, `Nut`, `Washer`, `HeatSetInsert`. `null` for a part marked `role="hardware"` that was modelled by hand (a bearing, a motor). |
| `designation` | The full designation, e.g. `ISO 4762 M3x12` or `Heat-set insert ruthex M3x5.7`. `null` for a hand-modelled part. |
| `part_number` | The manufacturer's number, from the table. Only heat-set inserts have one. |
| `count` | How many instances. **This is the number you order.** |
| `group` | Distinct group paths the part appears in, sorted. |
| `names` | The part names in the model, in registration order. |

**Grouping is by `(kind, designation)`**, not by name. Four screws called "Screw 1".."Screw 4" are one line with count
4. A hand-modelled hardware part is its own line, keyed by its name — that is the signal that it should probably have
been a standard part.

## 3. `manufactured[]`

```json
{ "name": "Lid", "count": 1, "group": ["Housing"], "volume": 7091.0496, "mass_g": 19.146, "names": ["Lid"] }
```

One line per part name by default. `--merge-identical` groups by the geometry signature — volume, area and bounding
box, each rounded to 0.001 — and puts the count and the names on one line.

**This is a guess and it is opt-in on purpose.** Two genuinely different parts can share volume, area and box (a
bracket and its mirror image with the same holes, for example). A BOM that merges them is worse than a long list, so
the default never merges.

`volume` is `null` for a part without a solid; `mass_g` is `null` without `--density`.

## 4. CSV

`--csv` writes UTF-8 **with BOM**, because Excel on Windows shows umlauts as `?` without it. One row per list entry:

```
type,item,part_number,count,group,volume_mm3,mass_g,names
purchased,ISO 4762 M3x12,,4,"Hardware, Screws",,,"Screw 1, Screw 2, Screw 3, Screw 4"
manufactured,Lid,,1,Housing,7091.050,19.146,Lid
```

`type` is `purchased` or `manufactured`; `item` is the designation or the part name. The delimiter is a comma, the
decimal point a point — the same convention as every other file in the repository.

## 5. What this does not do

- **No prices.** SOMA has no price list and no supplier. Add a column in the spreadsheet.
- **No materials for purchased parts.** A screw's material is not in the model (`color` is a display colour, not a
  material). Only `--density` for the manufactured parts.
- **No grouping of purchased parts by size across standards.** An M3x12 socket head and an M3x12 button head are two
  lines, correctly: they are two articles.
- **No reading of `NOTES.md`.** A hand-written list stays hand-written; the command is the source of quantities, not
  a merge of both.

## 6. Related

| Need | Command |
|---|---|
| Every part with designation, group, role, volume | `soma inspect --json` |
| Is the geometry sound? | `soma inspect --strict` |
| Files for the shop | `soma export --all --format step` |
| What an agent sees | `soma mcp` exposes the same document as the tool `soma_bom` |
