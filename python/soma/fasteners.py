# SPDX-License-Identifier: GPL-3.0-or-later OR Apache-2.0
# Zusaetzlich Apache 2.0 (E101): "Export as CadQuery" kopiert dieses Modul in das Skript des Nutzers.
"""Standard parts: screws, nuts, washers, heat-set inserts and rolling bearings, simplified without threads, with
matching holes.

    from soma import add_part
    from soma.fasteners import Screw

    s = Screw("ISO 4762", "M3x10", at=(20, 15, 8))   # the head rests at z = 8, the shank points down
    lid = lid.cut(s.clearance_hole())                 # clearance hole, with a counterbore for a sunk head
    add_part("Screw 1", s)                            # role "hardware" (purchased part), not in export --all

Placement, the same for all parts: `at` is the point on the axis where the part rests. `direction` points from there
into the material (default "-Z": from top to bottom). A screw rests with the underside of its head, a nut, washer or
bearing with one of its faces. Countersunk screws, set screws and heat-set inserts end flush with their top at `at`.
`sunk=True` sinks the head, nut or washer flush (its outer side is then at `at`), `sunk=0.5` 0.5 mm deeper.
`on=part` finds the seat itself: the line through `at` in direction `direction` hits the part, the first hit counts
(with "-Z" only x and y of `at` matter). `rotate()`, `translate()` and `moved()` work as on CadQuery shapes and
return a moved copy, for example so that a screw moves with its part into another position.

Dimensions come from the tables of bd_warehouse (Apache 2.0, see data/fasteners/QUELLE.md), partly nominal, partly
maximum values. Threads are not modelled: the shank and the bore of the nut have the nominal diameter.

A bearing is the one part here whose inside is not measured: bore, outside diameter and width come from the table, the
rings and balls in between are drawn to a rule (see `Bearing`). It is a purchased part that has to sit in a hole and on
a shaft, not a bearing to be manufactured, so the envelope is what counts and the catalogue mass is what a parts list
should show.
"""
import copy
import csv
import difflib
import functools
import io
import math
import numbers
import re
from pathlib import Path

import cadquery as cq
from OCP.BRepIntCurveSurface import BRepIntCurveSurface_Inter
from OCP.gp import gp_Ax1, gp_Dir, gp_Lin, gp_Pnt, gp_Trsf

__all__ = ["Screw", "Nut", "Washer", "HeatSetInsert", "Bearing", "RetainingRing", "ShaftKey", "ORing",
           "lengths", "pick_length", "standards"]

_DATA = Path(__file__).parent / "data" / "fasteners"
# Tabellen als Text (Dateiname -> CSV). Fuellt nur der Block von "Export as CadQuery" (cqexport.py), dann laeuft dieses
# Modul ohne soma und ohne data/
_EMBEDDED = {}
INCH = 25.4
# Bohrwerkzeuge ragen so weit ueber die Oberflaeche hinaus: Deckungsgleiche Flaechen machen cut() unzuverlaessig
MARGIN = 1.0
# Durchgangsloecher nach ISO 273, wie im Skill "Toleranzen" benannt, mit den Spalten der Tabelle
FITS = {"fine": "Close", "medium": "Normal", "coarse": "Loose"}
STEEL = (0.45, 0.46, 0.49)
BRASS = (0.80, 0.63, 0.32)
COS30 = math.cos(math.radians(30))

# Regelgewinde nach ISO 261. Manche Tabellen fuehren dasselbe Mass mit mehreren Steigungen, ohne Gewinde zaehlt nur
# der Durchmesser, die Steigung waehlt bei Kernloechern die richtige Zeile.
COARSE_PITCH = {
    1: 0.25, 1.2: 0.25, 1.4: 0.3, 1.6: 0.35, 1.8: 0.35, 2: 0.4, 2.5: 0.45, 3: 0.5, 3.5: 0.6, 4: 0.7, 5: 0.8, 6: 1.0,
    7: 1.0, 8: 1.25, 10: 1.5, 12: 1.75, 14: 2.0, 16: 2.0, 18: 2.5, 20: 2.5, 22: 2.5, 24: 3.0, 27: 3.0, 30: 3.5, 33: 3.5,
    36: 4.0, 39: 4.0, 42: 4.5, 45: 4.5, 48: 5.0, 52: 5.0, 56: 5.5, 60: 5.5, 64: 6.0,
}

# Kopf: socket (Zylinderkopf), button (Linsenkopf), countersunk (Senkkopf), hex (Sechskant), set (Gewindestift)
# Teilgewinde: ISO 4014 und DIN 931 sind nur bis zur Haelfte Gewinde, der Rest ist glatter Schaft
PARTIAL_THREAD = ("iso4014", "din931")

SCREWS = {
    "iso4762": dict(name="ISO 4762", title="Socket head cap screw", table="socket_head_cap_parameters.csv",
                    col="iso4762", head="socket", cols=("dk", "k", "s", "t")),
    "iso7380": dict(name="ISO 7380", title="Button head socket screw", table="button_head_parameters.csv",
                    col="iso7380_1", head="button", cols=("dk", "dl", "k", "rf", "s", "t")),
    "iso10642": dict(name="ISO 10642", title="Countersunk socket screw", table="countersunk_head_parameters.csv",
                     col="iso10642", head="countersunk", cols=("a", "dk", "k", "s", "t")),
    "iso4017": dict(name="ISO 4017", title="Hex head screw, fully threaded", table="hex_head_parameters.csv",
                    col="iso4017", head="hex", cols=("k", "s")),
    "iso4014": dict(name="ISO 4014", title="Hex head bolt with shank", table="hex_head_parameters.csv",
                    col="iso4014", head="hex", cols=("k", "s")),
    "din931": dict(name="DIN 931", title="Hex head bolt with shank", table="hex_head_parameters.csv",
                   col="din931", head="hex", cols=("k", "s")),
    "iso4026": dict(name="ISO 4026", title="Socket set screw with flat point", table="setscrew_parameters.csv",
                    col="iso4026", head="set", cols=("s", "t")),
    # Schulter: die Laenge ist die Schulterlaenge, das Gewindeende kommt zusaetzlich dazu
    "iso7379": dict(name="ISO 7379", title="Hexagon socket head shoulder screw", table="shoulder_screw.csv",
                    col="iso7379", head="shoulder", cols=("ds", "dk", "k", "b", "s", "t", "g2", "dg2")),
    "iso1580": dict(name="ISO 1580", title="Pan head screw, slotted", table="pan_head_parameters.csv",
                    col="iso1580", head="pan", cols=("dk", "k")),
    "iso1207": dict(name="ISO 1207", title="Cheese head screw, slotted", table="cheese_head_parameters.csv",
                    col="iso1207", head="pan", cols=("dk", "k")),
    # Der Kopf ist niedriger als bei DIN 7984 und der Durchmesser groesser: eigene Reihe, kein DIN-7984-Ersatz
    "openbuilds": dict(name="OpenBuilds", title="Low profile socket head screw (OpenBuilds)",
                       table="low_profile_parameters.csv", col="OpenBuilds", head="socket",
                       cols=("dk", "k", "s", "t")),
}
NUTS = {
    "iso4032": dict(name="ISO 4032", title="Hex nut", table="hex_nut_parameters.csv", col="iso4032", shape="hex"),
    "iso4033": dict(name="ISO 4033", title="Hex nut, high", table="hex_nut_parameters.csv", col="iso4033", shape="hex"),
    "iso4035": dict(name="ISO 4035", title="Hex nut, thin", table="hex_nut_parameters.csv", col="iso4035", shape="hex"),
    "din557": dict(name="DIN 557", title="Square nut", table="square_nut_parameters.csv", col="din557", shape="square"),
    "din1665": dict(name="DIN 1665", title="Hex nut with flange", table="hex_nut_with_flange_parameters.csv",
                    col="din1665", shape="flange", cols=("m", "s", "dc", "c")),
    "din1587": dict(name="DIN 1587", title="Domed cap nut", table="domed_cap_nut_parameters.csv",
                    col="din1587", shape="cap", cols=("m", "s", "dk")),
}
WASHERS = {
    "iso7089": dict(name="ISO 7089", title="Washer", table="plain_washer_parameters.csv", col="iso7089"),
    "iso7091": dict(name="ISO 7091", title="Washer, coarse", table="plain_washer_parameters.csv", col="iso7091"),
    "iso7093": dict(name="ISO 7093", title="Washer, large", table="plain_washer_parameters.csv", col="iso7093"),
    "iso7090": dict(name="ISO 7090", title="Washer, chamfered", table="chamfered_washer_parameters.csv", col="iso7090"),
    "din6797": dict(name="DIN 6797", title="Lock washer, internal teeth",
                    table="internal_tooth_lock_washer_parameters.csv", col="din6797", shape="toothed",
                    cols=("d1", "d2", "h", "n")),
}
INSERT_BRANDS = {"ruthex": "ruthex", "cnckitchen": "CNCKitchen", "mcmaster": "McMaster-Carr", "mcmastercarr": "McMaster-Carr",
                 "hilitchi": "Hilitchi", "aesamzhihui": "AE-SamZhihui"}
BEARINGS = {
    "deepgroove": dict(name="Deep groove ball bearing", title="Deep groove ball bearing, open",
                       table="single_row_deep_groove_ball_bearing_parameters.csv"),
    "capped": dict(name="Capped deep groove ball bearing", title="Deep groove ball bearing, capped or sealed",
                   table="single_row_capped_deep_groove_ball_bearing_parameters.csv"),
}
BEARING_FAMILIES = {"open": "deepgroove", "deepgrooveballbearing": "deepgroove", "2z": "capped", "2rz": "capped",
                    "2rs": "capped", "2rs1": "capped", "sealed": "capped", "shielded": "capped", "capped": "capped"}
ALIASES = {"iso73801": "iso7380"}
# Alte DIN-Bezeichnungen: melden statt still umdeuten, weil manche Masse abweichen
HINTS = {
    "din912": "ISO 4762", "din7380": "ISO 7380", "din7991": "ISO 10642 (head height differs slightly)",
    "din933": "ISO 4017 (M10, M12, M14 and M22 have a different width across flats than DIN 933)", "din913": "ISO 4026 (different point)",
    "din916": "ISO 4026 (different point)", "din934": "ISO 4032 (M10, M12, M14 and M22 have a different width across flats than DIN 934)",
    "din439": "ISO 4035", "din125": "ISO 7089", "din9021": "ISO 7093",
    "din7984": "OpenBuilds (the low profile here is the OpenBuilds series: lower head than DIN 7984, "
               "larger head diameter; model DIN 7984 by hand if its height matters)",
}


# --- Tabellen ----------------------------------------------------------------------------------------------------------

def _open(name):
    """Tabelle zum Lesen: eingebettet (Export als CadQuery) oder aus data/fasteners."""
    if name in _EMBEDDED:
        return io.StringIO(_EMBEDDED[name].lstrip("﻿"), newline="")
    return open(_DATA / name, encoding="utf-8-sig", newline="")


@functools.cache
def _table(name):
    """CSV als Liste von (Schluessel, {Spalte: Wert}). Kopfzeilen haben teils Leerzeichen am Rand, die fallen weg."""
    with _open(name) as f:
        rows = list(csv.reader(f))
    head = [h.strip() for h in rows[0]]
    return [(r[0].strip(), {h: v.strip() for h, v in zip(head[1:], r[1:])}) for r in rows[1:] if r and r[0].strip()]


_KEY = re.compile(r"^M(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?(?:-(.*))?$")


def _key(key):
    """"M3-0.5" -> (3.0, 0.5, ""), "M3-0.5-5.7" -> (3.0, 0.5, "5.7"), "M3" -> (3.0, None, ""). Zoll-Zeilen: None."""
    m = _KEY.match(key)
    if not m:
        return None, None, ""
    return float(m.group(1)), float(m.group(2)) if m.group(2) else None, m.group(3) or ""


def _num(text):
    return float(text.replace(",", "."))


def _rows(table, col, cols):
    """Alle metrischen Zeilen mit Werten fuer jede Spalte in `cols`: [(d, steigung, rest, {spalte: zahl})]."""
    out = []
    for key, row in _table(table):
        d, pitch, rest = _key(key)
        if d is None:
            continue
        vals = {c: row.get(f"{col}:{c}", "") if col else row.get(c, "") for c in cols}
        if all(vals.values()):
            try:
                out.append((d, pitch, rest, {c: v if c in ("drill", "part") else _num(v) for c, v in vals.items()}))
            except ValueError:
                continue
    return out


def _lookup(table, col, cols, d, what):
    """Werte fuer M<d>. Bevorzugt die Zeile mit Regelgewinde, sonst die erste Zeile mit Werten."""
    rows = [r for r in _rows(table, col, cols) if abs(r[0] - d) < 1e-9]
    if not rows:
        sizes = sorted({r[0] for r in _rows(table, col, cols)})
        raise ValueError(f"{what}: size M{_fmt(d)} is not in the table. Available: "
                         + ", ".join(f"M{_fmt(x)}" for x in sizes))
    coarse = [r for r in rows if r[1] is None or abs(r[1] - COARSE_PITCH.get(d, -1)) < 1e-9]
    return (coarse or rows)[0][3]


def _fmt(x):
    """3.0 -> "3", 2.5 -> "2.5": Zahlen so, wie man sie in Bezeichnungen schreibt."""
    return f"{x:g}"


def _norm_standard(standard, table, kind):
    if not isinstance(standard, str) or not standard.strip():
        raise ValueError(f"{kind}: give the standard as text, e.g. {next(iter(table.values()))['name']!r}")
    key = re.sub(r"[\s_.-]", "", standard.lower())
    key = ALIASES.get(key, key)
    if key in table:
        return key
    known = ", ".join(v["name"] for v in table.values())
    if key in HINTS:
        raise ValueError(f"{kind}: {standard!r} is now called {HINTS[key]}. Available: {known}")
    raise ValueError(f"{kind}: there is no standard {standard!r} here. Available: {known}")


_SIZE = re.compile(r"^\s*M\s*(\d+(?:[.,]\d+)?)\s*(?:[xX×*]\s*(\d+(?:[.,]\d+)?)\s*(?:mm)?)?\s*$", re.IGNORECASE)


_PITCHED = re.compile(r"^\s*M\s*(\d+(?:[.,]\d+)?)\s*[xX×*]\s*(\d+(?:[.,]\d+)?)\s*[xX×*]\s*(\d+(?:[.,]\d+)?)\s*(?:mm)?\s*$")


def _parse_size(size, length, kind):
    """"M3" oder "M3x10" (auch "M3 x 10", "M3×10") -> (3.0, Laenge oder None)."""
    if not isinstance(size, str):
        raise ValueError(f"{kind}: give the size as text, e.g. \"M3\" or \"M3x10\", not {size!r}")
    pitched = _PITCHED.match(size)
    if pitched:  # M10x1,25x40: Steigung und Laenge. Feinheiten gibt es hier nicht, also klar sagen
        raise ValueError(f"{kind}: {size.strip()!r} has a pitch and a length, and fine pitches are not supported "
                         f"(no thread is modelled). Use the coarse thread, e.g. \"M{_fmt(_num(pitched.group(1)))}x"
                         f"{_fmt(_num(pitched.group(3)))}\", or model the special part yourself")
    m = _SIZE.match(size)
    if not m:
        raise ValueError(f"{kind}: cannot read the size {size!r}. Expected e.g. \"M3\" or \"M3x10\"")
    d = _num(m.group(1))
    if m.group(2):
        from_size = _num(m.group(2))
        if length is not None and abs(float(length) - from_size) > 1e-9:
            raise ValueError(f"{kind}: length given twice with different values ({size!r} and length={length})")
        # M10x1,25 ist keine 1,25 mm lange Schraube: das ist die Steigung
        if length is None and from_size < min(3.0, 0.5 * d):
            raise ValueError(f"{kind}: in {size.strip()!r} the {_fmt(from_size)} mm looks like a pitch, not a length. "
                             f"Fine pitches are not supported (no thread is modelled). Use the coarse thread, e.g. "
                             f"\"M{_fmt(d)}x10\", or model the special part yourself")
        length = from_size
    return d, (float(length) if length is not None else None)


def _split_designation(standard, size):
    """"ISO 4762 M3x10" als ein Text -> ("ISO 4762", "M3x10")."""
    if size is None and isinstance(standard, str):
        m = re.match(r"^\s*(.*?)\s+(M\s*\d.*)$", standard, re.IGNORECASE)
        if m:
            return m.group(1), m.group(2)
    return standard, size


@functools.cache
def _nominal_lengths():
    out = {}
    with _open("nominal_screw_lengths.csv") as f:
        for row in csv.DictReader(f):
            if row["Unit"].strip() == "mm":
                out[row["Screw_Type"].strip()] = [_num(x) for x in row["Nominal_Sizes"].split(",") if x.strip()]
    return out


def _length_range(spec, d):
    """Kleinste und groesste Laenge der Tabelle fuer diese Groesse."""
    vals = _lookup(spec["table"], spec["col"], ("short", "long"), d, spec["name"])
    return vals["short"], vals["long"]


def lengths(standard, size):
    """Standard lengths of a screw in mm, e.g. lengths("ISO 4762", "M3") -> [5, 6, 8, 10, 12, 16, 20, 25, 30]."""
    key = _norm_standard(standard, SCREWS, "Screw")
    spec = SCREWS[key]
    d, _ = _parse_size(size, None, spec["name"])
    short, long_ = _length_range(spec, d)
    series = _nominal_lengths().get(spec["col"], [])
    return [x for x in series if short - 1e-9 <= x <= long_ + 1e-9]


def pick_length(standard, size, min_length, max_length=None):
    """Shortest standard length that is at least `min_length` (and at most `max_length`, if given)."""
    options = lengths(standard, size)
    fitting = [x for x in options if x >= min_length - 1e-9 and (max_length is None or x <= max_length + 1e-9)]
    if not fitting:
        span = f"{_fmt(min_length)} to {_fmt(max_length)}" if max_length is not None else f"of at least {_fmt(min_length)}"
        raise ValueError(f"{standard} {size}: no standard length {span} mm. Standard lengths: "
                         + ", ".join(_fmt(x) for x in options))
    return fitting[0]


def standards():
    """What is available: {"screws": {"ISO 4762": "Socket head cap screw", ...}, "nuts": ..., "washers": ...,
    "heat_set_inserts": [brands], "bearings": {"Deep groove ball bearing": ..., ...},
    "retaining_rings": {"DIN 471": "Retaining ring for shafts", ...}, "shaft_keys": {"DIN 6885": ...},
    "o_rings": {"ISO 3601": "O-ring, class A"}}."""
    return {
        "screws": {v["name"]: v["title"] for v in SCREWS.values()},
        "nuts": {v["name"]: v["title"] for v in NUTS.values()},
        "washers": {v["name"]: v["title"] for v in WASHERS.values()},
        "heat_set_inserts": sorted(set(INSERT_BRANDS.values())),
        "bearings": {v["name"]: v["title"] for v in BEARINGS.values()},
        "retaining_rings": {v["name"]: v["title"] for v in RETAINING_RINGS.values()},
        "shaft_keys": {v["name"]: v["title"] for v in SHAFT_KEYS.values()},
        "o_rings": {v["name"]: v["title"] for v in O_RINGS.values()},
    }


def _clearance(d, fit):
    if fit not in FITS:
        raise ValueError(f"fit must be one of {tuple(FITS)} (ISO 273 fine, medium, coarse), not {fit!r}")
    rows = [r for r in _rows("clearance_hole_sizes.csv", None, (FITS[fit],)) if abs(r[0] - d) < 1e-9]
    if not rows:
        raise ValueError(f"The table has no clearance hole for M{_fmt(d)}")
    return rows[0][3][FITS[fit]]


TAP_MATERIALS = {"soft": "Soft", "hard": "Hard"}


def _tap_drill(d, material="soft"):
    """Kernloch: "soft" fuer Aluminium, Kunststoff und Messing, "hard" fuer Stahl. Die Tabelle fuehrt beide."""
    col = TAP_MATERIALS.get(str(material).lower())
    if col is None:
        raise ValueError(f"tap drill: material is \"soft\" or \"hard\", not {material!r}")
    return _lookup("tap_hole_sizes.csv", None, (col,), d, "Tap drill hole")[col]


@functools.cache
def _drills():
    with _open("drill_sizes.csv") as f:
        return {r[0].strip(): _num(r[1].strip()) * INCH for r in list(csv.reader(f))[1:] if len(r) > 1}


def _drill_mm(code):
    """Bohrergroesse der Tabelle in mm: Nummern ("#21") und Buchstaben ("F") sind Zollbohrer. Anderes (die Tabelle
    nennt bei M10 "M14", groesser als der Einsatz) gilt als unbekannt."""
    return _drills().get(code.strip())


# --- Lage --------------------------------------------------------------------------------------------------------------

def _vec(v, what):
    if isinstance(v, cq.Vector):
        return v
    if isinstance(v, cq.Vertex):
        return cq.Vector(*v.toTuple())
    if isinstance(v, (tuple, list)) and len(v) == 3 and all(isinstance(x, numbers.Real) for x in v):
        return cq.Vector(*map(float, v))
    raise ValueError(f"{what}: expected (x, y, z), not {v!r}")


def _direction(spec):
    if isinstance(spec, str):
        m = re.match(r"^\s*([+-]?)\s*([xyz])\s*$", spec, re.IGNORECASE)
        if not m:
            raise ValueError(f"direction: expected \"-Z\", \"+X\" etc. or (x, y, z), not {spec!r}")
        v = cq.Vector(*[(-1.0 if m.group(1) == "-" else 1.0) if a == m.group(2).lower() else 0.0 for a in "xyz"])
    else:
        v = _vec(spec, "direction")
    if v.Length < 1e-9:
        raise ValueError("direction must not be (0, 0, 0)")
    return v.normalized()


def _at(at, on):
    """Punkt und (falls ableitbar) Richtung aus `at`: Tupel, Vector, Vertex, Location oder Workplane."""
    if at is None:
        raise ValueError("at is missing: the point where the part rests, e.g. at=(10, 5, 8)")
    if isinstance(at, cq.Location):
        pos = cq.Vector(*at.toTuple()[0])
        z = gp_Dir(0, 0, 1).Transformed(at.wrapped.Transformation())
        return pos, -cq.Vector(z.X(), z.Y(), z.Z())
    if isinstance(at, cq.Workplane):
        objs = at.objects
        if not objs:  # Workplane auf einer Flaeche: Ursprung der Ebene, ins Material gegen die Normale
            return at.plane.origin, -at.plane.zDir
        if len(objs) == 1:
            return _at(objs[0], on)[0], -at.plane.zDir
        raise ValueError(f"at: the Workplane holds {len(objs)} points. Pass one point per part (loop over .vals())")
    if isinstance(at, (tuple, list)) and len(at) == 2:
        if on is None:
            raise ValueError("at needs x, y and z. Only (x, y) works with on=part, then the seat is searched for")
        return cq.Vector(float(at[0]), float(at[1]), 0.0), None
    return _vec(at, "at"), None


def _shape_of(obj, what="on"):
    if hasattr(obj, "__soma_shape__"):
        return obj.__soma_shape__()
    if isinstance(obj, cq.Workplane):
        vals = [v for v in obj.vals() if isinstance(v, cq.Shape)]
        if not vals:
            raise ValueError(f"{what}: the Workplane contains no geometry")
        return vals[0] if len(vals) == 1 else cq.Compound.makeCompound(vals)
    if isinstance(obj, cq.Assembly):
        return obj.toCompound()
    if isinstance(obj, cq.Shape):
        return obj
    raise ValueError(f"{what}: expected a part (cq.Workplane or cq.Shape), not {type(obj).__name__}")


def _surface_hit(on, point, d):
    """Erster Schnittpunkt der Geraden durch `point` in Richtung `d` mit `on`, von aussen her gesehen."""
    shape = _shape_of(on)
    inter = BRepIntCurveSurface_Inter()
    inter.Init(shape.wrapped, gp_Lin(gp_Pnt(*point.toTuple()), gp_Dir(*d.toTuple())), 1e-7)
    best = None
    while inter.More():
        if best is None or inter.W() < best[0]:
            p = inter.Pnt()
            best = (inter.W(), cq.Vector(p.X(), p.Y(), p.Z()))
        inter.Next()
    if best is None:
        raise ValueError(f"on: the line through {_pt(point)} in direction {_pt(d)} does not hit the part. "
                         "Check at and direction")
    return best[1]


def _pt(v):
    return "(" + ", ".join(_fmt(round(c, 4)) for c in v.toTuple()) + ")"


def _sink(sunk, kind):
    """None: nicht versenkt, sonst die Tiefe unter `at` (0 bei sunk=True)."""
    if sunk is False or sunk is None:
        return None
    if sunk is True:
        return 0.0
    if isinstance(sunk, numbers.Real) and sunk >= 0:
        return float(sunk)
    raise ValueError(f"{kind}: sunk is True, False or a depth in mm (>= 0), not {sunk!r}")


class _Part:
    """Gemeinsame Lage. Lokal: Auflage bei z = 0, +Z zeigt aus dem Material, die Oberflaeche (`at`) liegt bei z = _zs."""

    role = "hardware"
    color = STEEL

    def _place(self, at, direction, on, angle, zs):
        point, derived = _at(at, on)
        d = _direction(direction) if direction is not None else (derived.normalized() if derived is not None else _direction("-Z"))
        if on is not None:
            point = _surface_hit(on, point, d)
        if not isinstance(angle, numbers.Real):
            raise ValueError(f"angle: rotation about the axis in degrees, not {angle!r}")
        ref = cq.Vector(1, 0, 0) if abs(d.x) < 0.99 else cq.Vector(0, 1, 0)
        x = (ref - d * ref.dot(d)).normalized()
        n = -d  # lokale Z-Achse
        a = math.radians(angle)
        x = x * math.cos(a) + n.cross(x) * math.sin(a)
        self._dir, self._zs = d, zs
        self._surface = point
        self._plane = cq.Plane(origin=point + d * zs, xDir=x, normal=n)
        self._loc = cq.Location(self._plane)

    def _world(self, local):
        return local.moved(self._loc)

    def _local_point(self, z):
        return (self._plane.origin + self._plane.zDir * z).toTuple()

    @property
    def direction(self):
        """Unit vector from the seat into the material."""
        return self._dir.toTuple()

    @property
    def seat(self):
        """Point on the axis at the seat (underside of the head, face of the nut)."""
        return self._local_point(0.0)

    @property
    def surface(self):
        """Point on the axis on the surface the part sits on (`at`, with on= the point found)."""
        return self._surface.toTuple()

    def point(self, distance):
        """Point on the axis, `distance` mm from the seat into the material (e.g. for the nut at the other end)."""
        return self._local_point(-float(distance))

    @property
    def shape(self):
        """The part as a cq.Solid in its position."""
        return self._world(self._local())

    def __soma_shape__(self):
        return self.shape

    # Lage aendern wie bei CadQuery-Formen: liefert eine Kopie, Bezeichnung, Masse und Bohrungen bleiben. So wandert eine
    # Schraube mit ihrem Teil (etwa in eine andere Stellung), ohne sie dort neu anzulegen.

    def moved(self, loc):
        """Copy moved by loc (cq.Location), like cq.Shape.moved()."""
        if not isinstance(loc, cq.Location):
            raise ValueError(f"moved() expects a cq.Location, not {loc!r}")
        t = loc.wrapped.Transformation()

        def pnt(v):
            p = gp_Pnt(*v.toTuple()).Transformed(t)
            return cq.Vector(p.X(), p.Y(), p.Z())

        def dirn(v):
            d = gp_Dir(*v.toTuple()).Transformed(t)
            return cq.Vector(d.X(), d.Y(), d.Z())

        new = copy.copy(self)
        new._plane = cq.Plane(origin=pnt(self._plane.origin), xDir=dirn(self._plane.xDir), normal=dirn(self._plane.zDir))
        new._loc = cq.Location(new._plane)
        new._dir, new._surface = dirn(self._dir), pnt(self._surface)
        return new

    def translate(self, vector):
        """Copy shifted by vector (x, y, z), like cq.Shape.translate()."""
        return self.moved(cq.Location(_vec(vector, "translate")))

    def rotate(self, startVector, endVector, angleDegrees):
        """Copy rotated about the axis from startVector to endVector (degrees), like cq.Shape.rotate()."""
        p1, p2 = _vec(startVector, "rotate: startVector"), _vec(endVector, "rotate: endVector")
        if (p2 - p1).Length < 1e-9:
            raise ValueError("rotate: startVector and endVector must differ (they define the axis)")
        if not isinstance(angleDegrees, numbers.Real):
            raise ValueError(f"rotate: angle in degrees, not {angleDegrees!r}")
        t = gp_Trsf()
        t.SetRotation(gp_Ax1(gp_Pnt(*p1.toTuple()), gp_Dir(*(p2 - p1).toTuple())), math.radians(angleDegrees))
        return self.moved(cq.Location(t))

    def __repr__(self):
        return f"<{self.designation} at {_pt(cq.Vector(*self.seat))}, direction {_pt(self._dir)}>"


def _cyl(d, z0, z1):
    """Zylinder entlang Z von z0 bis z1."""
    lo, hi = min(z0, z1), max(z0, z1)
    return cq.Solid.makeCylinder(d / 2, hi - lo, cq.Vector(0, 0, lo), cq.Vector(0, 0, 1))


def _hex_prism(s, z0, z1):
    """Sechskant mit Schluesselweite s, zwei Flaechen parallel zur lokalen X-Achse."""
    return cq.Workplane().workplane(offset=z0).polygon(6, s / COS30).extrude(z1 - z0).val()


def _chamfered_hex(s, h, both):
    """Sechskant mit 30-Grad-Fase an den Ecken (oben, bei Muttern auch unten), wie bei Kopf und Mutter ueblich."""
    e = s / COS30
    c = (e - s) / 2 * math.tan(math.radians(30))
    pts = [(0, 0), (s / 2, 0), (e / 2, c), (e / 2, h - c), (s / 2, h), (0, h)] if both else \
        [(0, 0), (e / 2, 0), (e / 2, h - c), (s / 2, h), (0, h)]
    body = cq.Workplane("XZ").polyline(pts).close().revolve(360, (0, 0, 0), (0, 1, 0)).val()
    return _hex_prism(s, 0, h).intersect(body)


def _socket(solid, s, t, z_top):
    """Innensechskant mit Schluesselweite s und Tiefe t von der Oberseite z_top aus."""
    return solid.cut(_hex_prism(s, z_top - t, z_top + 0.01))


def _one(shape):
    """Boolesche Operationen liefern teils einen Compound mit einem Koerper: dann den Koerper selbst."""
    shape = shape.clean()
    solids = shape.Solids()
    return solids[0] if len(solids) == 1 else shape


def _arc_mid(p1, p2, r):
    """Mittelpunkt des Bogens mit Radius r von p1 nach p2, nach aussen gewoelbt (Linsenkopf)."""
    (x1, z1), (x2, z2) = p1, p2
    vx, vz = x2 - x1, z2 - z1
    c = math.hypot(vx, vz)
    h = math.sqrt(max(r * r - c * c / 4, 0.0))
    nx, nz = -vz / c, vx / c  # Normale zur Achse hin und nach unten
    if nx > 0:
        nx, nz = -nx, -nz
    mx, mz = (x1 + x2) / 2, (z1 + z2) / 2
    return mx - (r - h) * nx, mz - (r - h) * nz


# --- Schrauben ---------------------------------------------------------------------------------------------------------

@functools.cache
def _screw_local(head, d, length, pitch, dims):
    p = dict(dims)
    tip = min(0.6 * pitch, 0.2 * d)
    if head == "set":  # ganz im Material: Oberseite bei z = 0, Kegelstumpf an beiden Enden
        body = cq.Workplane().circle(d / 2).extrude(-length).faces("<Z or >Z").chamfer(tip).val()
        return _one(_socket(body, p["s"], p["t"], 0.0))
    shank = cq.Workplane().circle(d / 2).extrude(-length).faces("<Z").chamfer(tip).val()
    if head == "socket":
        cap = cq.Workplane().circle(p["dk"] / 2).extrude(p["k"]).faces(">Z").chamfer(0.06 * p["dk"]).val()
        cap = _socket(cap, p["s"], p["t"], p["k"])
    elif head == "button":
        mid = _arc_mid((p["dk"] / 2, 0), (p["dl"] / 2, p["k"]), p["rf"])
        cap = (cq.Workplane("XZ").moveTo(0, 0).lineTo(p["dk"] / 2, 0).threePointArc(mid, (p["dl"] / 2, p["k"]))
               .lineTo(0, p["k"]).close().revolve(360, (0, 0, 0), (0, 1, 0)).val())
        cap = _socket(cap, p["s"], p["t"], p["k"])
    elif head == "countersunk":  # Kegel unter der Oberseite, die Laenge zaehlt ab der Oberseite
        hc = (p["dk"] - d) / 2 / math.tan(math.radians(p["a"] / 2))
        cap = cq.Solid.makeCone(d / 2, p["dk"] / 2, hc, cq.Vector(0, 0, -hc), cq.Vector(0, 0, 1))
        cap = _socket(cap, p["s"], p["t"], 0.0)
    elif head == "pan":  # flacher Zylinder mit gerundetem Rand; Schlitz und Kreuzschlitz sind nicht modelliert
        cap = cq.Workplane().circle(p["dk"] / 2).extrude(p["k"]).faces(">Z").chamfer(0.08 * p["k"]).val()
    elif head == "hex":
        cap = _chamfered_hex(p["s"], p["k"], both=False)
    elif head == "shoulder":
        # Kopf, Schulter, Freistich und Gewindeende in einem Rotationsprofil. Der Freistich ist enger
        # als das Gewinde; aus Zylindern zusammengesetzt entstuende dort eine Bohrung statt einer Nut.
        ds, dk, k, b, g2, dg2 = p["ds"], p["dk"], p["k"], p["b"], p["g2"], p["dg2"]
        prof = [(0.0, k), (dk / 2, k), (dk / 2, 0.0), (ds / 2, 0.0), (ds / 2, -length),
                (dg2 / 2, -length), (dg2 / 2, -(length + g2)), (d / 2, -(length + g2)),
                (d / 2, -(length + b)), (0.0, -(length + b))]
        body = cq.Workplane("XZ").polyline(prof).close().revolve(360, (0, 0, 0), (0, 1, 0))
        body = body.faces(">Z").chamfer(0.06 * dk).faces("<Z").chamfer(tip)
        return _one(_socket(body.val(), p["s"], p["t"], k))
    else:
        raise ValueError(f"Unknown head shape {head!r}")
    return _one(cap.fuse(shank))


class Screw(_Part):
    """Screw without thread. Screw("ISO 4762", "M3x10", at=(x, y, z)) or Screw("ISO 4762", "M3", 10, at=...).

    standard      "ISO 4762" (socket head), "ISO 7380" (button head), "ISO 10642" (countersunk), "ISO 4017", "ISO 4014",
                  "DIN 931" (hex head), "ISO 4026" (set screw), "ISO 7379" (shoulder screw),
                  "OpenBuilds" (low profile socket head), "ISO 1580" (pan head), "ISO 1207" (cheese head)
    at            seat of the underside of the head (countersunk screw, set screw: the top), (x, y, z) or cq.Location
    direction     from the seat into the material, default "-Z"
    on            part the screw sits on: the seat is searched for along `direction`
    sunk          True: head flush in a counterbore, 0.5: 0.5 mm deeper. Countersunk screws always sit flush
    angle         rotation about the axis in degrees (orientation of the hex)
    check_length  False allows lengths that are not standard lengths

    A shoulder screw counts its length as the shoulder length, as the standard does: the threaded end comes on
    top of it, so `shank_length` is longer than `length`. Its pivot hole is `shoulder_hole()`, not `clearance_hole()`.
    """

    def __init__(self, standard, size=None, length=None, *, at=None, direction=None, on=None, sunk=False, angle=0.0,
                 check_length=True):
        standard, size = _split_designation(standard, size)
        self.standard_key = _norm_standard(standard, SCREWS, "Screw")
        spec = SCREWS[self.standard_key]
        self.standard = spec["name"]
        self.d, length = _parse_size(size, length, spec["name"])
        if length is None:
            raise ValueError(f"{spec['name']} M{_fmt(self.d)}: the length is missing, e.g. \"M{_fmt(self.d)}x10\". "
                             f"Standard lengths: {', '.join(_fmt(x) for x in lengths(standard, size))}")
        if length <= 0:
            raise ValueError(f"{spec['name']}: the length must be greater than 0")
        self.dims = _lookup(spec["table"], spec["col"], spec["cols"], self.d, spec["name"])
        self.length = length
        self.head = spec["head"]
        self.pitch = COARSE_PITCH.get(self.d, 0.1 * self.d)
        if check_length:
            options = lengths(standard, f"M{_fmt(self.d)}")
            if options and not any(abs(length - x) < 1e-9 for x in options):
                raise ValueError(f"{self.designation}: {_fmt(length)} mm is not a standard length. Standard lengths: "
                                 f"{', '.join(_fmt(x) for x in options)}. Non-standard length: check_length=False")
        if self.head == "set" and length < self.dims["t"]:
            raise ValueError(f"{self.designation}: shorter than the depth of the hex socket ({_fmt(self.dims['t'])} mm)")
        sink = _sink(sunk, spec["name"])
        self.sunk = sink is not None
        if self.head in ("countersunk", "set"):  # sitzen ohnehin im Material, `sunk` legt sie nur tiefer
            zs = sink or 0.0
        else:
            zs = self.head_height + sink if sink is not None else 0.0
        self._place(at, direction, on, angle, zs)

    @property
    def designation(self):
        return f"{self.standard} M{_fmt(self.d)}x{_fmt(self.length)}"

    @property
    def head_diameter(self):
        """Head diameter, for a hex head the width across corners."""
        if self.head == "hex":
            return self.dims["s"] / COS30
        return self.dims["dk"] if "dk" in self.dims else self.d

    @property
    def head_height(self):
        if self.head == "countersunk":
            return (self.dims["dk"] - self.d) / 2 / math.tan(math.radians(self.dims["a"] / 2))
        return self.dims.get("k", 0.0)

    @property
    def key(self):
        """Width across flats of the hex socket or the hex head, None for a slotted head (pan, cheese)."""
        return self.dims.get("s")

    @property
    def thread_length(self):
        """Length of the thread. Fully threaded screws: the whole shank. ISO 4014 and DIN 931 are partially threaded,
        and the standard gives the thread as 2d + 6 up to 125 mm length, 2d + 12 up to 200 mm, 2d + 25 above that.

        The shape is a plain cylinder either way — SOMA models no threads — so this number is for a drawing note, a
        FEM bolt or a parts list, not for the geometry.
        """
        if self.standard_key not in PARTIAL_THREAD:
            return self.length
        extra = 6 if self.length <= 125 else 12 if self.length <= 200 else 25
        return min(self.length, 2 * self.d + extra)

    @property
    def shank_length(self):
        """Length from the seat to the end of the shank. For a shoulder screw the threaded end comes on top of
        the shoulder length, so this is longer than `length`."""
        return self.length + self.dims["b"] if self.head == "shoulder" else self.length

    @property
    def shoulder(self):
        """Diameter of the precision shoulder of a shoulder screw, otherwise None. This, not `d`, is the
        diameter a pivot or locating hole has to match."""
        return self.dims.get("ds")

    @property
    def tip(self):
        """Point on the axis at the end of the shank."""
        return self.point(self.shank_length)

    @property
    def outer(self):
        """Point on the axis at the top of the head."""
        return self._local_point(0.0 if self.head in ("countersunk", "set") else self.head_height)

    @property
    def lengths(self):
        return lengths(self.standard, f"M{_fmt(self.d)}")

    def clearance(self, fit="medium"):
        """Diameter of the clearance hole to ISO 273: fit "fine", "medium" or "coarse"."""
        return _clearance(self.d, fit)

    @property
    def tap_drill(self):
        """Tap drill diameter for the coarse thread in soft material (aluminium, plastic, brass)."""
        return _tap_drill(self.d)

    def tap_drill_for(self, material="soft"):
        """Tap drill diameter in "soft" (default) or "hard" material (steel). The table has both."""
        return _tap_drill(self.d, material)

    def _local(self):
        return _screw_local(self.head, self.d, self.length, self.pitch, tuple(sorted(self.dims.items())))

    def clearance_hole(self, fit="medium", depth=None, oversize=0.0, recess=None):
        """Tool for cut(): clearance hole, with a counterbore for a sunk head, with a 90 degree cone for countersunk screws.

        fit       ISO 273: "fine", "medium" (default) or "coarse"
        depth     depth from the surface (`at`), default: to 1 mm beyond the end of the shank
        oversize  added to all diameters (3D printing: holes come out smaller)
        recess    diameter of the counterbore instead of head + clearance (e.g. room for a socket wrench)
        """
        c0 = self.clearance(fit)
        c = c0 + oversize
        top = self._zs + MARGIN
        bottom = self._zs - depth if depth is not None else -(self.shank_length + 1.0)
        tool = _cyl(c, bottom, top)
        gap = c0 - self.d + oversize  # Spiel am Kopf wie am Schaft
        if self.head == "countersunk":
            big = recess or self.dims["dk"] + gap
            h = (big - c) / 2 / math.tan(math.radians(self.dims["a"] / 2))
            cone = cq.Solid.makeCone(c / 2, big / 2, h, cq.Vector(0, 0, -h), cq.Vector(0, 0, 1))
            tool = tool.fuse(cone, _cyl(big, 0.0, top))
        elif self.sunk and self.head != "set":
            tool = tool.fuse(_cyl(recess or self.head_diameter + gap, 0.0, top))
        return self._world(_one(tool))

    def shoulder_hole(self, fit=0.02, depth=None, oversize=0.0):
        """Tool for cut(): hole for the shoulder of a shoulder screw, for a pivot or a locating pin.

        fit       added to the shoulder diameter: 0.02 for a locating fit (H8), 0.1 for a sliding fit
        depth     depth from the surface (`at`), default: the shoulder length plus 1 mm
        oversize  added on top of everything (3D printing: holes come out smaller)
        """
        if self.shoulder is None:
            raise ValueError(f"{self.designation} has no shoulder; use clearance_hole() or tap_hole()")
        bottom = self._zs - depth if depth is not None else -(self.length + 1.0)
        return self._world(_cyl(self.shoulder + fit + oversize, bottom, self._zs + MARGIN))

    def tap_hole(self, depth=None, diameter=None, oversize=0.0, material="soft"):
        """Tool for cut(): tap drill hole for a thread (or for screwing into plastic with your own `diameter`).

        depth     depth from the surface, default to 3 pitches beyond the end of the shank
        material  "soft" (aluminium, plastic, brass) or "hard" (steel): the table gives a different drill
        """
        dia = (diameter or _tap_drill(self.d, material)) + oversize
        bottom = self._zs - depth if depth is not None else -(self.shank_length + 3 * self.pitch)
        return self._world(_cyl(dia, bottom, self._zs + MARGIN))


# --- Muttern, Scheiben, Gewindeeinsaetze -------------------------------------------------------------------------------

@functools.cache
def _nut_local(shape, d, m, s, dims=()):
    dims = dict(dims)
    if shape == "hex":
        body = _chamfered_hex(s, m, both=True)
    elif shape == "square":
        body = cq.Solid.makeBox(s, s, m, cq.Vector(-s / 2, -s / 2, 0))
    elif shape == "flange":  # Sechskant mit Bund am Auflagebund
        body = _one(_chamfered_hex(s, m, both=True).fuse(_cyl(dims["dc"], 0.0, dims["c"])))
    elif shape == "cap":  # geschlossene Hutmutter: Halbkugel auf dem Sechskant, Kernloch endet am Kugelansatz
        dome = cq.Solid.makeSphere(dims["dk"] / 2, cq.Vector(0, 0, m), angleDegrees1=0.0, angleDegrees2=90.0)
        return _one(_chamfered_hex(s, m, both=False).fuse(dome).cut(_cyl(d, -0.01, m + 0.01)))
    else:
        raise ValueError(f"Unknown nut shape {shape!r}")
    return _one(body.cut(_cyl(d, -0.01, m + 0.01)))


class Nut(_Part):
    """Nut. Nut("ISO 4032", "M3", at=(x, y, z), direction="+Z"): rests with one face at `at`, `direction` points
    from there into the material (so upwards for a nut under a plate).

    standard  "ISO 4032" (hex), "ISO 4033" (high), "ISO 4035" (thin), "DIN 557" (square), "DIN 1665" (with flange),
              "DIN 1587" (domed cap, closed)
    sunk      True: sunk flush (outer side at `at`), 0.5: 0.5 mm deeper. trap() gives the pocket for it
    angle     rotation about the axis in degrees. At 0 two flats are parallel to the X axis (for axis X: to the Y axis)
    """

    def __init__(self, standard, size=None, *, at=None, direction=None, on=None, sunk=False, angle=0.0):
        standard, size = _split_designation(standard, size)
        self.standard_key = _norm_standard(standard, NUTS, "Nut")
        spec = NUTS[self.standard_key]
        self.standard, self.shape_kind = spec["name"], spec["shape"]
        self.d, length = _parse_size(size, None, spec["name"])
        if length is not None:
            raise ValueError(f"{spec['name']}: nuts have no length, give only \"M{_fmt(self.d)}\"")
        vals = _lookup(spec["table"], spec["col"], spec.get("cols", ("m", "s")), self.d, spec["name"])
        self.dims = vals
        self.height, self.key = vals["m"], vals["s"]
        sink = _sink(sunk, spec["name"])
        self.sunk = sink is not None
        self._place(at, direction, on, angle, self.height + sink if sink is not None else 0.0)

    @property
    def designation(self):
        return f"{self.standard} M{_fmt(self.d)}"

    @property
    def outer(self):
        return self._local_point(self.overall_height)

    @property
    def overall_height(self):
        """Height from the seat to the highest point: the table's `m`, plus the dome for a cap nut."""
        if self.shape_kind == "cap":
            return self.height + self.dims["dk"] / 2
        return self.height

    def _local(self):
        return _nut_local(self.shape_kind, self.d, self.height, self.key, tuple(sorted(self.dims.items())))

    def trap(self, clearance=0.2, slot=None, slot_length=None):
        """Tool for cut(): pocket for the nut, `clearance` per side and in height.

        Hex and square nut: prism or box. Flange nut: round pocket for the flange, hexagon above it. Cap nut: round
        pocket up over the dome, so that the nut can be screwed in. A sunk nut opens up to the surface.

        slot="+X" with slot_length: slot to insert the nut from the side, as wide as the nut across the slot (with
        angle=0 and axis Z that is the width across flats for "+X"). Only for hex and square nuts: a flange or a dome
        cannot pass through a slot.
        """
        sc = self.key + 2 * clearance
        top = self._zs + MARGIN if self.sunk else self.height + clearance
        if self.shape_kind == "hex":
            pocket = _hex_prism(sc, 0.0, top)
        elif self.shape_kind == "flange":  # Bund zuerst, darueber der Sechskant
            pocket = _cyl(self.dims["dc"] + 2 * clearance, 0.0, self.dims["c"] + clearance)
            pocket = pocket.fuse(_hex_prism(sc, self.dims["c"] - 0.01, top))
        elif self.shape_kind == "cap":  # Hutmutter: rundes Loch bis ueber die Kuppe, kein Sechskant noetig
            pocket = _cyl(self.dims["dk"] + 2 * clearance, 0.0,
                          self._zs + MARGIN if self.sunk else self.overall_height + clearance)
        else:
            pocket = cq.Solid.makeBox(sc, sc, top, cq.Vector(-sc / 2, -sc / 2, 0))
        if slot is not None:
            if not slot_length or slot_length <= 0:
                raise ValueError("trap: slot needs slot_length, the length of the slot from the axis in mm")
            if self.shape_kind not in ("hex", "square"):
                raise ValueError(f"trap: a slot is for hex and square nuts, not for {self.standard}. "
                                 "Cut the pocket for this nut by hand")
            u = _direction(slot)
            if abs(u.dot(self._dir)) > 1e-6:
                raise ValueError("trap: slot must be perpendicular to the axis of the nut")
            ux, uy = u.dot(self._plane.xDir), u.dot(self._plane.yDir)
            if self.shape_kind == "hex":
                corners = [(sc / COS30 / 2 * math.cos(math.radians(60 * i)), sc / COS30 / 2 * math.sin(math.radians(60 * i)))
                           for i in range(6)]
            else:
                corners = [(sx * sc / 2, sy * sc / 2) for sx in (-1, 1) for sy in (-1, 1)]
            across = [-x * uy + y * ux for x, y in corners]
            width = max(across) - min(across)
            box = cq.Solid.makeBox(slot_length, width, top, cq.Vector(0, -width / 2, 0))
            box = box.rotate(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), math.degrees(math.atan2(uy, ux)))
            pocket = pocket.fuse(box)
        return self._world(_one(pocket))


@functools.cache
def _ring_local(d1, d2, h):
    return _one(_cyl(d2, 0, h).cut(_cyl(d1, -0.01, h + 0.01)))


@functools.cache
def _tooth_local(d1, d2, h, n):
    """Scheibe mit Innenzaehnen (DIN 6797): Ring plus n Zaehne, die nach innen zeigen."""
    ring = _ring_local(d1, d2, h)
    if not n:
        return ring
    deep = 0.3 * (d2 - d1) / 2          # Zahnlaenge nach innen
    wide = math.pi * d1 / (2 * n)       # halbe Teilung, damit Zaehne und Luecken gleich breit sind
    teeth = []
    for i in range(int(n)):
        t = cq.Solid.makeBox(deep + 0.3, wide, h, cq.Vector(d1 / 2 - deep, -wide / 2, 0))
        teeth.append(t.rotate(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), 360.0 * i / n))
    return _one(ring.fuse(*teeth))


class Washer(_Part):
    """Washer. Washer("ISO 7089", "M3", at=(x, y, z)): rests with one side at `at`, `outer` is the other side, where
    the head or nut then sits.

    standard  "ISO 7089" (normal), "ISO 7091" (coarse), "ISO 7093" (large), "ISO 7090" (chamfered),
              "DIN 6797" (lock washer with internal teeth)
    """

    def __init__(self, standard, size=None, *, at=None, direction=None, on=None, sunk=False, angle=0.0):
        standard, size = _split_designation(standard, size)
        self.standard_key = _norm_standard(standard, WASHERS, "Washer")
        spec = WASHERS[self.standard_key]
        self.standard = spec["name"]
        self.d, length = _parse_size(size, None, spec["name"])
        if length is not None:
            raise ValueError(f"{spec['name']}: washers have no length, give only \"M{_fmt(self.d)}\"")
        vals = _lookup(spec["table"], spec["col"], spec.get("cols", ("d1", "d2", "h")), self.d, spec["name"])
        self.dims = vals
        self.inner, self.outer_diameter, self.thickness = vals["d1"], vals["d2"], vals["h"]
        self.shape_kind = spec.get("shape", "ring")
        sink = _sink(sunk, spec["name"])
        self.sunk = sink is not None
        self._place(at, direction, on, angle, self.thickness + sink if sink is not None else 0.0)

    @property
    def designation(self):
        return f"{self.standard} M{_fmt(self.d)}"

    @property
    def outer(self):
        return self._local_point(self.thickness)

    def _local(self):
        if self.shape_kind == "toothed":
            return _tooth_local(self.inner, self.outer_diameter, self.thickness, self.dims.get("n"))
        return _ring_local(self.inner, self.outer_diameter, self.thickness)

    def trap(self, clearance=0.2, depth=None):
        """Tool for cut(): recess for the washer, `clearance` on the diameter per side and in depth.

        A recessed washer sits below the surface so a screw head does not stand proud. `depth` from the surface,
        default: the thickness plus the clearance.
        """
        deep = depth if depth is not None else self.thickness + clearance
        return self._world(_cyl(self.outer_diameter + 2 * clearance, self._zs - deep, self._zs + MARGIN))


def _inserts(brand):
    return _rows("heatset_nut_parameters.csv", brand, ("s", "m", "dc", "drill", "part"))


@functools.cache
def _insert_local(d, s, m):
    return _one(_cyl(s, -m, 0).cut(_cyl(d, -m - 0.01, 0.01)))


class HeatSetInsert(_Part):
    """Heat-set insert (3D printing). HeatSetInsert("M3x5.7", at=(x, y, z)): the top ends flush at `at`, the insert
    reaches into the material in direction `direction`. hole() gives the hole for it.

    size     "M3x5.7" (thread x length). Without a length only if the manufacturer has just one
    brand    "ruthex" (default), "CNCKitchen", "McMaster-Carr", "Hilitchi", "AE-SamZhihui"
    variant  for the same length, e.g. "Voron" (ruthex M3x4 with 5 mm outer diameter)
    sunk     0.5: top 0.5 mm below `at`
    """

    color = BRASS

    def __init__(self, size, length=None, *, brand="ruthex", variant=None, at=None, direction=None, on=None, sunk=False,
                 angle=0.0):
        key = re.sub(r"[\s_.-]", "", str(brand).lower())
        if key not in INSERT_BRANDS:
            raise ValueError(f"Heat-set insert: unknown brand {brand!r}. Available: "
                             + ", ".join(sorted(set(INSERT_BRANDS.values()))))
        self.brand = INSERT_BRANDS[key]
        self.d, length = _parse_size(size, length, "Heat-set insert")
        rows = [r for r in _inserts(self.brand) if abs(r[0] - self.d) < 1e-9]
        if not rows:
            sizes = sorted({r[0] for r in _inserts(self.brand)})
            raise ValueError(f"Heat-set insert {self.brand}: there is no M{_fmt(self.d)}. Available: "
                             + ", ".join(f"M{_fmt(x)}" for x in sizes))

        def label(r):  # "5.7", "4 Voron": wie man die Auswahl nennt
            extra = re.sub(r"^\d+(?:\.\d+)?", "", r[2]).strip(" -")
            return _fmt(r[3]["m"]) + (f" {extra}" if extra else "")

        found = rows
        if length is not None:
            found = [r for r in found if abs(r[3]["m"] - length) < 0.05]
        if variant is not None:
            found = [r for r in found if str(variant).lower() in r[2].lower()]
        elif len(found) > 1:  # ohne Variante: die Zeile ohne Zusatz ("4.0", nicht "4.0Voron")
            plain = [r for r in found if re.fullmatch(r"\d+(?:\.\d+)?", r[2])]
            found = plain if len(plain) == 1 else found
        if len(found) != 1:
            options = ", ".join(sorted({label(r) for r in rows}))
            what = "no length matches" if not found else "the length is ambiguous"
            raise ValueError(f"Heat-set insert {self.brand} M{_fmt(self.d)}: {what}. Lengths: {options} "
                             f"(e.g. \"M{_fmt(self.d)}x{label(rows[0]).split()[0]}\", the extra with variant=)")
        row = found[0][3]
        self.variant = re.sub(r"^\d+(?:\.\d+)?", "", found[0][2]).strip(" -") or None
        self.diameter, self.length, self.part_number = row["s"], row["m"], row["part"]
        self.hole_diameter = _drill_mm(row["drill"])
        if self.hole_diameter is None or not self.d < self.hole_diameter < self.diameter:
            raise ValueError(f"{self.designation}: the table gives no usable hole (drill {row['drill']!r}). "
                             "Look up the hole at the manufacturer and model the insert yourself")
        sink = _sink(sunk, "Heat-set insert")
        self.sunk = sink is not None
        self._place(at, direction, on, angle, sink or 0.0)

    @property
    def designation(self):
        return f"Heat-set insert {self.brand} M{_fmt(self.d)}x{_fmt(self.length)}" + (f" {self.variant}" if self.variant else "")

    @property
    def outer(self):
        return self._local_point(0.0)

    def _local(self):
        return _insert_local(self.d, self.diameter, self.length)

    def hole(self, extra_depth=1.0, oversize=0.0):
        """Tool for cut(): hole for the insert as the manufacturer specifies, `extra_depth` mm deeper than the insert is
        long (room for displaced plastic), `oversize` added to the diameter."""
        return self._world(_cyl(self.hole_diameter + oversize, -(self.length + extra_depth), self._zs + MARGIN))


# --- Sprengringe -------------------------------------------------------------------------------------------------------

def _dia(size, what):
    """20, "20" oder "M20" -> 20.0."""
    if isinstance(size, numbers.Real):
        return float(size)
    m = re.match(r"^\s*M?\s*(\d+(?:[.,]\d+)?)\s*$", str(size), re.IGNORECASE)
    if not m:
        raise ValueError(f"{what}: cannot read the diameter {size!r}. Expected e.g. 20")
    return _num(m.group(1))


@functools.cache
def _plain_rows(table, col, cols):
    """Tabelle, deren erste Spalte eine nackte Zahl in mm ist (Sprengringe, Passfedern): {mass: {spalte: wert}}."""
    out = {}
    for key, row in _table(table):
        try:
            out[_num(key)] = {c: _num(row.get(f"{col}:{c}" if col else c, "")) for c in cols}
        except ValueError:
            continue
    return out


def _box(x0, x1, y0, y1, z0, z1):
    """Quader zwischen zwei Ecken, die Reihenfolge der Ecken ist egal."""
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    z0, z1 = sorted((z0, z1))
    return cq.Solid.makeBox(x1 - x0, y1 - y0, z1 - z0, cq.Vector(x0, y0, z0))


RETAINING_RINGS = {
    "din471": dict(name="DIN 471", title="Retaining ring for shafts", table="din471.csv", bore=False),
    "din472": dict(name="DIN 472", title="Retaining ring for bores", table="din472.csv", bore=True),
}


@functools.cache
def _clip_local(bore, d3, a, b, d5, s):
    """Sprengring in der XY-Ebene, Dicke s nach +Z: Ringkoerper, Spalt, zwei Nasen mit Loch.

    d3 freier Durchmesser, b Bandbreite, a Nasenlaenge, d5 Spaltweite (auch das Loch der Zange).
    Die Nase ist ein Rechteck; DIN laesst ihre Form offen und zeichnet sie nur.
    """
    r_in, r_out = (d3 / 2 - b, d3 / 2) if bore else (d3 / 2, d3 / 2 + b)
    edge = r_in if bore else r_out
    lug = (edge - a, edge + b) if bore else (edge - b, edge + a)
    body = _cyl(2 * r_out, 0.0, s).cut(_cyl(2 * r_in, -0.01, s + 0.01))
    lugs = [_box(sx * d5 / 2, sx * (d5 / 2 + a), lug[0], lug[1], 0.0, s) for sx in (1, -1)]
    gap = _box(-d5 / 2, d5 / 2, min(lug[0], r_in) - 1, max(lug[1], r_out) + 1, -0.01, s + 0.01)
    shape = body.fuse(*lugs).cut(gap)
    for sx in (1, -1):
        hole = cq.Solid.makeCylinder(d5 / 2, s + 0.02, cq.Vector(sx * (d5 / 2 + a / 2), edge + (-a if bore else a) / 2, -0.01),
                                     cq.Vector(0, 0, 1))
        shape = shape.cut(hole)
    return _one(shape)


class RetainingRing(_Part):
    """Retaining ring (circlip). RetainingRing("DIN 471", 20, at=(0, 0, 0)) sits in a groove on a 20 mm shaft,
    RetainingRing("DIN 472", 20, at=(0, 0, 0)) in a groove in a 20 mm bore.

    standard  "DIN 471" (shaft), "DIN 472" (bore)
    size      shaft or bore diameter in mm, as a number or "20"
    at        seat; the ring lies in the plane of `at` and reaches `thickness` away from the material, like a washer
    direction from the seat into the material, default "-Z"

    The diameter of the ring body (d3), its width, the thickness and the gap are the table values, so the ring
    fits the groove it is meant for. The lugs are rectangles with a hole for the pliers: DIN leaves their shape
    to the maker and only draws it.
    """

    def __init__(self, standard, size=None, *, at=None, direction=None, on=None, angle=0.0):
        standard, size = _split_designation(standard, size)
        self.standard_key = _norm_standard(standard, RETAINING_RINGS, "RetainingRing")
        spec = RETAINING_RINGS[self.standard_key]
        self.standard = spec["name"]
        self.d = _dia(size, spec["name"])
        rows = _plain_rows(spec["table"], None, ("d3", "a", "b", "d5", "s", "d2", "m"))
        if self.d not in rows:
            raise ValueError(f"{spec['name']}: there is no ring for {_fmt(self.d)} mm. Available: "
                             + ", ".join(_fmt(x) for x in sorted(rows)))
        self.dims = rows[self.d]
        self.free_diameter = self.dims["d3"]
        self.thickness = self.dims["s"]
        self.groove_diameter, self.groove_width = self.dims["d2"], self.dims["m"]
        self.bore = spec["bore"]
        self._place(at, direction, on, angle, 0.0)

    @property
    def designation(self):
        return f"{self.standard} {_fmt(self.d)}x{_fmt(self.thickness)}"

    def _local(self):
        d = self.dims
        return _clip_local(self.bore, d["d3"], d["a"], d["b"], d["d5"], d["s"])

    def groove(self, oversize=0.0):
        """Tool for cut(): the groove the ring sits in, `groove_width` wide and centred on the ring, floor at
        `groove_diameter`. `oversize` widens the groove diameter (3D printing: a groove comes out narrower)."""
        extra = max((self.groove_width - self.thickness) / 2, 0.0)
        small, big = (self.d, self.groove_diameter + oversize) if self.bore else \
            (self.groove_diameter + oversize, self.d)
        ring = _cyl(big + 2, -extra, self.thickness + extra).cut(
            _cyl(small, -extra - 0.01, self.thickness + extra + 0.01))
        return self._world(_one(ring))


# --- Passfedern --------------------------------------------------------------------------------------------------------

SHAFT_KEYS = {"din6885": dict(name="DIN 6885", title="Parallel key, form A (rounded ends)",
                              table="shaft_key_parameters.csv")}


@functools.cache
def _key_local(b, h, length, depth):
    """Passfeder mit runden Enden, Unterkante bei -depth (Nut der Welle), Oberkante bei h - depth."""
    return cq.Workplane("XY").slot2D(length, b).extrude(h).translate((0, 0, -depth)).val()


class ShaftKey(_Part):
    """Parallel key (DIN 6885, form A with rounded ends). ShaftKey("DIN 6885", 20, 40, at=(0, 0, 10)) on a 20 mm
    shaft, 40 mm long. ShaftKey(20, 40) works too.

    The key sits in the shaft keyway: `at` is the point on the shaft surface, the key reaches `shaft_depth` into the
    shaft and `height - shaft_depth` out of it. `keyway()` cuts the matching groove in the shaft or in the hub.
    """

    def __init__(self, standard, size=None, length=None, *, at=None, direction=None, on=None, angle=0.0):
        if isinstance(standard, numbers.Real) or (isinstance(standard, str) and re.fullmatch(r"\s*M?\s*\d+([.,]\d+)?\s*", standard)):
            standard, size, length = "DIN 6885", standard, size  # ShaftKey(20, 40)
        standard, size = _split_designation(standard, size)
        self.standard_key = _norm_standard(standard, SHAFT_KEYS, "ShaftKey")
        spec = SHAFT_KEYS[self.standard_key]
        self.standard = spec["name"]
        self.d = _dia(size, spec["name"])
        rows = _plain_rows(spec["table"], "din6885", ("b", "h", "t2", "t4"))
        if self.d not in rows:
            raise ValueError(f"{spec['name']}: there is no key for a {_fmt(self.d)} mm shaft. Available: "
                             + ", ".join(_fmt(x) for x in sorted(rows)))
        if length is None:
            raise ValueError(f"{spec['name']} {_fmt(self.d)}: the length is missing, e.g. ShaftKey({_fmt(self.d)}, 40)")
        self.dims = rows[self.d]
        self.length = float(length)
        if self.length <= 0:
            raise ValueError(f"{spec['name']}: the length must be greater than 0")
        self._place(at, direction, on, angle, 0.0)

    @property
    def designation(self):
        return f"{self.standard} {_fmt(self.width)}x{_fmt(self.height)}x{_fmt(self.length)}"

    @property
    def width(self):
        return self.dims["b"]

    @property
    def height(self):
        return self.dims["h"]

    @property
    def shaft_depth(self):
        """Depth of the keyway in the shaft (t4 in the table)."""
        return self.dims["t4"]

    @property
    def hub_depth(self):
        """Depth of the keyway in the hub (t2 in the table)."""
        return self.dims["t2"]

    def _local(self):
        return _key_local(self.width, self.height, self.length, self.shaft_depth)

    def keyway(self, kind="shaft", depth=None, oversize=0.0):
        """Tool for cut(): the keyway for this key, at the same `at` and `direction`.

        kind      "shaft" (milled, rounded ends, `shaft_depth` deep) or "hub" (broached, square ends, `hub_depth`)
        depth     depth from the surface, default: the depth of the table
        oversize  added to width and length (3D printing: a groove comes out narrower)
        """
        if kind not in ("shaft", "hub"):
            raise ValueError(f"keyway: kind is \"shaft\" or \"hub\", not {kind!r}")
        deep = depth if depth is not None else (self.shaft_depth if kind == "shaft" else self.hub_depth)
        w, length = self.width + oversize, self.length + oversize
        if kind == "shaft":
            tool = cq.Workplane("XY").slot2D(length, w).extrude(deep).translate((0, 0, -deep)).val()
        else:
            tool = _box(-length / 2, length / 2, -w / 2, w / 2, -deep, 0.0)
        return self._world(tool)


# --- O-Ringe -----------------------------------------------------------------------------------------------------------

O_RINGS = {"iso3601": dict(name="ISO 3601", title="O-ring, class A", table="o-ring_parameters.csv", col="iso3601")}

# Zwei Nutentabellen nach Schnurdicke: statisch mit radialer und axialer Einfederung, dynamisch nur radial.
GLANDS = {
    "static": dict(table="o-ring_static_gland_parameters.csv", radial=("d_r_min", "d_r_max"),
                   axial=("d_a_min", "d_a_max"), squeeze=("sq_r_mm_min", "sq_r_mm_max"),
                   percent=("sq_r_p_min", "sq_r_p_max")),
    "dynamic": dict(table="o-ring_dynamic_gland_parameters.csv", radial=("d_min", "d_max"), axial=None,
                    squeeze=("sq_mm_min", "sq_mm_max"), percent=("sq_p_min", "sq_p_max")),
}


@functools.cache
def _gland_rows(table):
    """Nutentabelle nach Schnurdicke: {w: {spalte: zahl oder None}}. "-" heisst: gibt es fuer diese Schnur nicht."""
    out = {}
    for key, row in _table(table):
        out[round(_num(key), 3)] = {name: None if text in ("-", "") else _num(text) for name, text in row.items()}
    return out


@functools.cache
def _oring_index():
    """Groessen ("025") -> Maße, und Schnurdicke -> [(Innendurchmesser, Groesse)] nach Durchmesser sortiert."""
    spec = O_RINGS["iso3601"]
    by_size, by_width = {}, {}
    for key, row in _table(spec["table"]):
        try:
            vals = {c: _num(row[f"{spec['col']}:{c}"]) for c in ("id", "w", "id_tol", "w_tol")}
        except (KeyError, ValueError):
            continue
        size = key.removeprefix("-").strip().zfill(3)
        by_size[size] = vals
        by_width.setdefault(vals["w"], []).append((vals["id"], size))
    for entries in by_width.values():
        entries.sort()
    return by_size, by_width


def _groove_local(inner, outer, z0, z1, fillet=0.0, floor="inner"):
    """Ringfoermige Nut als Koerper: von Radius `inner` bis `outer`, von z0 bis z1.

    floor  "inner" oder "outer": die Nutgrundflaeche liegt innen oder aussen, gerundet werden dort beide Ecken;
           "z0": der Grund ist die Ebene z0, gerundet werden die beiden Ecken auf ihr. So entsteht ein Werkzeug,
           das eine Nut mit gerundetem Grund schneidet — scharfe Ecken kerben den Ring ein.
    """
    if floor not in ("inner", "outer", "z0"):
        raise ValueError(f"Unknown groove floor {floor!r}")
    f = 0.0 if not fillet else max(min(fillet, (outer - inner) / 3, (z1 - z0) / 3), 0.0)
    w = cq.Workplane("XZ")
    if f <= 1e-9:
        w = w.moveTo(inner, z0).lineTo(outer, z0).lineTo(outer, z1).lineTo(inner, z1).close()
    elif floor == "inner":
        w = (w.moveTo(inner + f, z0).lineTo(outer, z0).lineTo(outer, z1).lineTo(inner + f, z1)
             .radiusArc((inner, z1 - f), -f).lineTo(inner, z0 + f).radiusArc((inner + f, z0), -f).close())
    elif floor == "outer":
        w = (w.moveTo(inner, z0).lineTo(outer - f, z0).radiusArc((outer, z0 + f), -f)
             .lineTo(outer, z1 - f).radiusArc((outer - f, z1), -f).lineTo(inner, z1).close())
    else:
        w = (w.moveTo(inner, z0 + f).radiusArc((inner + f, z0), -f).lineTo(outer - f, z0)
             .radiusArc((outer, z0 + f), -f).lineTo(outer, z1).lineTo(inner, z1).close())
    return w.revolve(360, (0, 0, 0), (0, 1, 0)).val()


class ORing(_Part):
    """O-Ring. ORing("025", at=(x, y, z)): der Ring liegt mit seiner Mittelebene in `at`, +Z zeigt aus dem Material,
    also steht die eine Haelfte heraus. So steht der Ring in der Nut, die `gland()` schneidet.

    size   Groesse nach ISO 3601, dreistellig ("025", auch 25 oder "-025"). Das ist eine Groessennummer, **kein
           Durchmesser** — 025 hat 29,87 mm Innendurchmesser, 020 nur 21,95 mm. Welche Groesse zu einem Durchmesser
           passt, sagt `for_inner_diameter()`.
    at     Mitte des Ringes (Mittelebene), (x, y, z) oder cq.Location
    """

    def __init__(self, size, *, at=None, direction=None, on=None, angle=0.0):
        self.standard_key = "iso3601"
        self.standard = O_RINGS[self.standard_key]["name"]
        self.size = self._normalize(size)
        by_size, _ = _oring_index()
        self.dims = by_size[self.size]
        self.inner_diameter, self.width = self.dims["id"], self.dims["w"]
        self._place(at, direction, on, angle, 0.0)

    @staticmethod
    def _normalize(size):
        text = str(size).strip().removeprefix("-").strip()
        by_size, _ = _oring_index()
        if text.isdigit() and text.zfill(3) in by_size:
            return text.zfill(3)
        raise ValueError(f"O-ring size {size!r}: a three-digit ISO 3601 size code such as \"025\", not a diameter. "
                         f"Sizes run from {min(by_size)} to {max(by_size)}; for a diameter use "
                         f"ORing.for_inner_diameter()")

    @classmethod
    def for_inner_diameter(cls, diameter, width=None, tolerance=0.05):
        """Groessen, deren Innendurchmesser `diameter` entspricht (± tolerance relativ), als Liste von Codes.

        width  Schnurdicke in mm, etwa 1.78 fuer duenne und 2.62 fuer kraeftige Ringe; ohne Angabe alle Schnuere
        """
        if not isinstance(diameter, numbers.Real) or diameter <= 0:
            raise ValueError(f"for_inner_diameter: diameter in mm, not {diameter!r}")
        if tolerance < 0:
            raise ValueError(f"for_inner_diameter: tolerance is a fraction, not {tolerance!r}")
        _, by_width = _oring_index()
        found = []
        for w, entries in sorted(by_width.items()):
            if width is not None and abs(w - width) > 1e-6:
                continue
            found.extend(size for inner, size in entries if abs(inner - diameter) <= tolerance * diameter)
        if not found:
            raise ValueError(f"for_inner_diameter: no O-ring with {diameter} mm inner diameter"
                             + (f" and {width} mm cord" if width is not None else ""))
        return found

    @property
    def designation(self):
        return f"{self.standard} {self.size} {_fmt(self.inner_diameter)}x{_fmt(self.width)}"

    @property
    def dash_number(self):
        """Groesse nach ISO 3601, dreistellig."""
        return self.size

    @property
    def outer_diameter(self):
        return self.inner_diameter + 2 * self.width

    @property
    def major_radius(self):
        return (self.inner_diameter + self.width) / 2

    @property
    def minor_radius(self):
        return self.width / 2

    @property
    def length(self):
        """Laenge der Mittellinie: was der Ring im eingebauten Zustand umschliesst."""
        return 2 * math.pi * self.major_radius

    @property
    def outer(self):
        return self._local_point(self.minor_radius)

    def _local(self):
        return cq.Solid.makeTorus(self.major_radius, self.minor_radius)

    def gland_spec(self, kind="shaft", application="static", backing_rings=0):
        """Die Maße der Nut als dict: width, depth (Mittel), depth_min, depth_max, radius, clearance, squeeze_*.

        kind         "shaft" (Nut in der Welle), "bore" (Nut in der Bohrung), "face" (Nuten in einer Stirnflaeche)
        application  "static" oder "dynamic"; dynamisch gibt es nur die radiale Nut
        backing_rings  0, 1 oder 2 Stuetzringe — fuer duenne Schnuere gibt es sie nicht
        """
        if kind not in ("shaft", "bore", "face"):
            raise ValueError(f"gland: kind is \"shaft\", \"bore\" or \"face\", not {kind!r}")
        if application not in GLANDS:
            raise ValueError(f"gland: application is \"static\" or \"dynamic\", not {application!r}")
        if backing_rings not in (0, 1, 2):
            raise ValueError(f"gland: backing_rings is 0, 1 or 2, not {backing_rings!r}")
        spec = GLANDS[application]
        if kind == "face" and spec["axial"] is None:
            raise ValueError(f"gland: the {application} table has no axial gland, only a radial one. "
                             "A face seal is a static gland")
        try:
            row = _gland_rows(spec["table"])[round(self.width, 3)]
        except KeyError:
            raise ValueError(f"gland: no {application} gland for a {self.width} mm cord. The table has "
                             f"{', '.join(_fmt(w) for w in sorted(_gland_rows(spec['table'])))}") from None
        width = row[f"g_w_{backing_rings}"]
        if width is None:
            many = "backing ring" if backing_rings == 1 else "backing rings"
            raise ValueError(f"gland: {backing_rings} {many} are not possible with a {self.width} mm cord; "
                             "the table gives them from 1.78 mm")
        low, high = spec["axial"] if kind == "face" else spec["radial"]
        squeeze = spec["squeeze"] if kind != "face" else ("sq_a_mm_min", "sq_a_mm_max")
        percent = spec["percent"] if kind != "face" else ("sq_a_p_min", "sq_a_p_max")
        return dict(width=width, depth_min=row[low], depth_max=row[high],
                    depth=(row[low] + row[high]) / 2, radius=(row["g_r_min"] + row["g_r_max"]) / 2,
                    radius_min=row["g_r_min"], radius_max=row["g_r_max"], clearance=row["clr_max"],
                    squeeze_min=row[squeeze[0]], squeeze_max=row[squeeze[1]],
                    squeeze_percent_min=row[percent[0]], squeeze_percent_max=row[percent[1]])

    def gland(self, kind="shaft", application="static", backing_rings=0, oversize=0.0):
        """Werkzeug fuer cut(): die Nut zum Ring, an derselben Stelle und in derselben Richtung wie der Ring.

        Die Nut liegt mittig zum Ring, ihre Tiefe und Breite kommen aus der Tabelle. Fuer "shaft" ist der
        Nutgrund der Innendurchmesser des Ringes, die Welle also `inner_diameter + 2 x depth`; fuer "bore" ist
        die Bohrung der Aussendurchmesser und der Grund liegt `depth` tiefer. Fuer "face" liegt der Grund auf
        der Unterseite des Ringes, die Dichtflaeche `depth` darueber.

        oversize  auf Breite und Tiefe addiert (3D-Druck: eine Nut wird enger)
        """
        spec = self.gland_spec(kind, application, backing_rings)
        width, depth = spec["width"] + oversize, spec["depth"] + oversize
        r = self.major_radius
        if kind == "shaft":
            tool = _groove_local(self.inner_diameter / 2, self.inner_diameter / 2 + depth + MARGIN,
                                 -width / 2, width / 2, spec["radius"], "inner")
        elif kind == "bore":
            tool = _groove_local(self.outer_diameter / 2 - MARGIN, self.outer_diameter / 2 + depth,
                                 -width / 2, width / 2, spec["radius"], "outer")
        else:
            tool = _groove_local(r - width / 2, r + width / 2, -self.minor_radius,
                                 -self.minor_radius + depth + MARGIN, spec["radius"], "z0")
        return self._world(tool)


# --- Waelzlager --------------------------------------------------------------------------------------------------------

_BEARING_MARK = re.compile(r"^[*\s]+")


@functools.cache
def _bearing_index():
    """Bezeichnung -> [(Familie, Zeile)]. Zeilen ohne Bezeichnung und die Striche der Tabellen fallen weg."""
    out = {}
    for key, spec in BEARINGS.items():
        for _, row in _table(spec["table"]):
            name = _BEARING_MARK.sub("", row.get("SKT:Designation", "")).strip()
            if not name or name in ("-", "\u2013", "\u2014"):
                continue
            out.setdefault(name, []).append((key, row))
    return out


def _bnum(row, col):
    """Zahl aus einer Spalte der Lagertabelle, None wenn dort ein Strich oder nichts steht."""
    try:
        return _num(row.get(f"SKT:{col}", "").strip())
    except ValueError:
        return None


def _bearing_family(family):
    key = re.sub(r"[\s_.-]", "", str(family).lower())
    key = BEARING_FAMILIES.get(key, key)
    if key not in BEARINGS:
        raise ValueError("Bearing: family is " + " or ".join(repr(v["name"]) for v in BEARINGS.values())
                         + f", not {family!r}")
    return key


@functools.cache
def _bearing_local(d, D, B, capped):
    """Lager um die Achse, von z = 0 bis z = B.

    Ringe und Kugeln nach einer Regel, nicht nach Katalog: die Tabelle fuehrt d1 und D1 (Schulterdurchmesser), aber
    die beiden Tabellen meinen damit Verschiedenes — bei den gedeckelten Lagern ist D1 - d1 groesser als die Breite,
    ein Lager ginge also nicht auf. Deshalb: Wandstaerke aus dem radialen Platz, Kugeln mit 0,55 x Breite, Anzahl aus
    dem Teilkreis. Die Kugeln ueberlappen beide Ringe um 2 % und machen das Lager damit zu einem Koerper.
    """
    space = (D - d) / 2
    ball = min(0.55 * B, 0.8 * space)
    wall = max((space - ball) / 2, 0.15 * space)
    inner = _one(_cyl(d + 2 * wall, 0, B).cut(_cyl(d, -0.01, B + 0.01)))
    outer = _one(_cyl(D, 0, B).cut(_cyl(D - 2 * wall, -0.01, B + 0.01)))
    pitch = (d + D) / 2
    count = max(6, min(14, int(math.pi * pitch / (1.3 * ball))))
    r = 0.52 * ball
    balls = cq.Compound.makeCompound([
        cq.Solid.makeSphere(r, cq.Vector(pitch / 2 * math.cos(2 * math.pi * i / count),
                                         pitch / 2 * math.sin(2 * math.pi * i / count), B / 2))
        for i in range(count)])
    parts = [inner, outer, balls]
    if capped:
        t = min(0.3, 0.1 * B)
        for z in (0.0, B - t):
            seal = _ring_local(d + 2 * wall - 0.1, D - 2 * wall + 0.1, t)
            parts.append(seal.moved(cq.Location(cq.Vector(0, 0, z))))
    return _one(parts[0].fuse(*parts[1:]))


class Bearing(_Part):
    """Rolling bearing. Bearing("608", at=(x, y, z)): one face rests at `at` and the part extends away from the
    material by its width, like a washer.

    designation  catalogue number: "608", "6000", "6200", "6300", "623", "624" (open), "608-2Z", "623-2Z", "6300-2RS1"
                 (capped or sealed). The tables cover bores from 3 to 10 mm, which is the range small mechanisms use
    family       only needed when a number sits in both tables: "deep groove" (open) or "capped"

    Bore, outside diameter, width, chamfer and mass are the catalogue values; `mass_kg` is what the part really weighs.
    The rings and balls in between follow a rule, not a catalogue drawing — see `_bearing_local`. Chamfers are not
    modelled, `chamfer` is the table value for the corner of a housing.
    """

    def __init__(self, designation, *, family=None, at=None, direction=None, on=None, sunk=False, angle=0.0):
        if not isinstance(designation, str) or not designation.strip():
            raise ValueError("Bearing: give the catalogue number as text, e.g. \"608\" or \"608-2Z\"")
        name = designation.strip()
        hits = _bearing_index().get(name, [])
        if family is not None:
            key = _bearing_family(family)
            hits = [h for h in hits if h[0] == key]
        if not hits:
            known = sorted(_bearing_index())
            close = difflib.get_close_matches(name, known, n=3, cutoff=0.6)
            hint = (" Did you mean " + " or ".join(repr(c) for c in close) + "?") if close else ""
            raise ValueError(f"Bearing: there is no bearing {name!r} here.{hint} Available: " + ", ".join(known))
        if len(hits) > 1:
            raise ValueError(f"Bearing: {name!r} is in both tables; give family=\"deep groove\" or family=\"capped\"")
        key, row = hits[0]
        self.standard = BEARINGS[key]["name"]
        self.designation = name
        self.capped = key == "capped"
        self.bore, self.diameter, self.width = _bnum(row, "d"), _bnum(row, "D"), _bnum(row, "B")
        if None in (self.bore, self.diameter, self.width):
            raise ValueError(f"Bearing: the table has no usable bore, outside diameter or width for {name!r}")
        self.chamfer = _bnum(row, "r12")
        self.mass_kg = _bnum(row, "mass")
        sink = _sink(sunk, "Bearing")
        self.sunk = sink is not None
        self._place(at, direction, on, angle, self.width + sink if sink is not None else 0.0)

    @property
    def mass_g(self):
        """Catalogue mass in grams, None if the table has none."""
        return None if self.mass_kg is None else round(self.mass_kg * 1000.0, 4)

    @property
    def outer(self):
        return self._local_point(self.width)

    def _local(self):
        return _bearing_local(self.bore, self.diameter, self.width, self.capped)
