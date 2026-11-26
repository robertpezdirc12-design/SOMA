"""Bill of materials: what has to be bought, and what has to be made (schema `soma.bom/1`, `soma bom`).

Why this exists: `soma export --all` deliberately skips purchased parts, so a screw exists in the model and then
disappears from every output. `soma.fasteners` already knows what it built (`designation`, `part_number`), and the
registry already marks it (`role="hardware"`) — nothing ever read either. This module does, and nothing more.

    soma bom                       two tables in the terminal
    soma bom --json                the document
    soma bom --csv order.csv       a table for a spreadsheet, UTF-8 with BOM (Excel opens it correctly)
    soma bom --density 2.7         mass of the manufactured parts

It runs the model, like `soma export` and `soma inspect`. Nothing is written except the optional CSV.

Two decisions worth knowing:

- **Purchased parts are grouped by designation, not by name.** Four screws called "Screw 1".."Screw 4" are one line
  with count 4, because that is what you order.
- **Manufactured parts are one line per part name.** Identical parts registered under different names stay separate
  unless `--merge-identical` is given: merging by geometry is a guess, and a wrong guess in a BOM is worse than a
  long list.
"""
import csv
import json
import math
from pathlib import Path

SCHEMA = "soma.bom/1"
UNITS = "mm"
CSV_HEADER = ("type", "item", "part_number", "count", "group", "volume_mm3", "mass_g", "names")


class BomError(Exception):
    """Ein Problem, das der Aufrufer beheben kann: kein Modell, ein Modell, das nicht baut."""


def _r(x, digits=4):
    """Zahl fuer JSON: gerundet, ohne -0.0, ohne nan/inf."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    v = round(v, digits)
    return 0.0 if v == 0 else v


def _mass(volume, density):
    return _r(volume * density / 1000.0, 3) if volume is not None and density else None


def _signature(shape):
    """Grobe Formkennung fuer --merge-identical: Volumen, Flaeche, Huellbox. Zwei verschiedene Teile koennen dieselbe
    Kennung haben; deshalb ist das Zusammenfassen eine ausdrueckliche Entscheidung des Aufrufers."""
    try:
        bb = shape.BoundingBox()
        return (round(shape.Volume(), 3), round(shape.Area(), 3),
                round(bb.xlen, 3), round(bb.ylen, 3), round(bb.zlen, 3))
    except Exception:
        return None


def _volume(shape):
    """Volumen nur, wenn das Teil einen Koerper hat: eine Flaeche liefert in OCCT irgendeine Zahl."""
    try:
        return shape.Volume() if shape.Solids() else None
    except Exception:
        return None


def _purchased(parts):
    """Kupljene dele po oznaki (ali imenu, ce oznake ni): ena vrstica na artikel, s seznamom mest uporabe."""
    lines = {}
    for p in parts:
        if p["role"] != "hardware":
            continue
        f = p.get("fastener")
        kind = type(f).__name__ if f is not None else None
        designation = getattr(f, "designation", None) if f is not None else None
        key = (kind, designation or p["name"])
        line = lines.get(key)
        if line is None:
            line = lines[key] = dict(kind=kind, designation=designation, part_number=None, count=0, names=[], group=set())
        line["count"] += 1
        line["names"].append(p["name"])
        if p.get("group"):
            line["group"].add("/".join(p["group"]))
        number = getattr(f, "part_number", None) if f is not None else None
        if number and line["part_number"] is None:
            line["part_number"] = str(number)
    out = []
    for line in lines.values():
        out.append(dict(kind=line["kind"], designation=line["designation"], part_number=line["part_number"],
                        count=line["count"], group=sorted(line["group"]), names=line["names"]))
    out.sort(key=lambda x: (x["kind"] or "", x["designation"] or ""))
    return out


def _manufactured(parts, density, merge_identical):
    """Eigene dele: eine vrstica na ime, ali na obliko z --merge-identical."""
    lines = {}
    for p in parts:
        if p["role"] != "part":
            continue
        volume = _volume(p["shape"])
        sig = _signature(p["shape"]) if merge_identical else None
        key = sig if sig is not None else ("name", p["name"])
        line = lines.get(key)
        if line is None:
            line = lines[key] = dict(name=p["name"], names=[], count=0, group=set(), volume=None, mass_g=None)
        line["count"] += 1
        line["names"].append(p["name"])
        if p.get("group"):
            line["group"].add("/".join(p["group"]))
        if line["volume"] is None:
            line["volume"], line["mass_g"] = _r(volume), _mass(volume, density)
    out = []
    for line in lines.values():
        out.append(dict(name=line["name"], count=line["count"], group=sorted(line["group"]),
                        volume=line["volume"], mass_g=line["mass_g"], names=line["names"]))
    out.sort(key=lambda x: x["name"])
    return out


def build(project, density=None, entry=None, merge_identical=False):
    """Die Kosovnica des Modells. Fuehrt model.py aus, schreibt nichts."""
    from . import build as build_mod
    root = Path(project).resolve()
    try:
        parts = build_mod.run_model(root, entry)
    except build_mod.BuildError as e:
        raise BomError(e.message if getattr(e, "message", None) else str(e)) from e
    purchased = _purchased(parts)
    made = _manufactured(parts, density, merge_identical)
    references = [p["name"] for p in parts if p["role"] == "reference"]
    other = [p for p in parts if p["role"] not in ("part", "hardware", "reference")]
    volume = sum(x["volume"] for x in made if x["volume"] is not None)
    mass = sum(x["mass_g"] for x in made if x["mass_g"] is not None)
    totals = dict(parts=len(parts),
                  purchased=sum(x["count"] for x in purchased),
                  manufactured=sum(x["count"] for x in made),
                  references=len(references),
                  items=len(purchased) + len(made),
                  volume=_r(volume) if volume else None,
                  mass_g=_r(mass, 3) if mass else None)
    if density:
        totals["density_g_cm3"] = density
    if other:
        totals["note"] = ("parts with an unknown role are not in the list: "
                          + ", ".join(f"{p['name']} ({p['role']})" for p in other))
    from . import __version__
    return dict(schema=SCHEMA, soma=__version__, units=UNITS,
                source=dict(project=root.name,
                            entry=str(entry or build_mod.read_project_json(root).get("entry") or build_mod.DEFAULT_ENTRY)),
                totals=totals, purchased=purchased, manufactured=made,
                references=dict(count=len(references), names=references))


def text(doc):
    """Zwei Tabellen fuer das Terminal."""
    t = doc["totals"]
    lines = [f"{t['parts']} part(s): {t['purchased']} purchased, {t['manufactured']} manufactured, "
             f"{t['references']} reference -> {t['items']} line(s) to order and make"]
    if doc["purchased"]:
        lines += ["", "Purchased parts"]
        head = f"{'Count':>5}  {'Designation':<34} {'Part number':<16} Used by"
        lines += [head, "-" * len(head)]
        for x in doc["purchased"]:
            label = x["designation"] or f"{x['names'][0]} (modelled by hand)"
            names = ", ".join(x["names"])
            if len(names) > 46:
                names = names[:44] + "…"
            lines.append(f"{x['count']:>5}  {label[:34]:<34} {(x['part_number'] or '—'):<16} {names}")
    if doc["manufactured"]:
        lines += ["", "Manufactured parts"]
        head = f"{'Count':>5}  {'Name':<28} {'Group':<20} {'Volume mm³':>12} {'Mass g':>9}"
        lines += [head, "-" * len(head)]
        for x in doc["manufactured"]:
            group = ", ".join(x["group"]) or "—"
            vol = "—" if x["volume"] is None else f"{x['volume']:.1f}"
            mass = "—" if x["mass_g"] is None else f"{x['mass_g']:.1f}"
            lines.append(f"{x['count']:>5}  {x['name'][:28]:<28} {group[:20]:<20} {vol:>12} {mass:>9}")
    if doc["references"]["count"]:
        lines += ["", f"Not in the list: {doc['references']['count']} reference part(s) "
                      f"({', '.join(doc['references']['names'][:6])}"
                      f"{' …' if doc['references']['count'] > 6 else ''}). They are brought along, not made or bought."]
    if t.get("note"):
        lines += ["", f"Note: {t['note']}"]
    if t.get("mass_g") is not None:
        lines += ["", f"Manufactured mass: {t['mass_g']:.1f} g at {t['density_g_cm3']:g} g/cm³ "
                      f"(purchased parts are not weighed: their material is not known)."]
    return "\n".join(lines)


def rows(doc):
    """Die Zeilen der CSV: dieselben Angaben wie die Tabellen, flach."""
    out = []
    for x in doc["purchased"]:
        out.append(dict(type="purchased", item=x["designation"] or x["names"][0], part_number=x["part_number"] or "",
                        count=x["count"], group=", ".join(x["group"]), volume_mm3="", mass_g="",
                        names=", ".join(x["names"])))
    for x in doc["manufactured"]:
        out.append(dict(type="manufactured", item=x["name"], part_number="", count=x["count"],
                        group=", ".join(x["group"]),
                        volume_mm3="" if x["volume"] is None else f"{x['volume']:.3f}",
                        mass_g="" if x["mass_g"] is None else f"{x['mass_g']:.3f}",
                        names=", ".join(x["names"])))
    return out


def write_csv(doc, path):
    """CSV schreiben, UTF-8 mit BOM: sonst zeigt Excel auf Windows Umlaute als Fragezeichen."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADER)
        w.writeheader()
        for row in rows(doc):
            w.writerow(row)
    return p


def write(doc, out=None):
    """JSON: nach `out` eingerueckt, sonst eine Zeile fuer die Pipe."""
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return None
    return json.dumps(doc, ensure_ascii=False)
