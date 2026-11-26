// Test für die Zukaufteile nach den Lagern (Lücken G3, G5, G6, G8): Schulter-, Flachkopf- und Schlitzkopfschraube,
// Sprengringe DIN 471/472 mit Nut, Passfeder DIN 6885 mit Nut, Bund- und Hutmutter, Fasen- und Zahnscheibe. Maße aus den
// Tabellen, ein Körper, Lage wie bei Scheibe und Lager, Werkzeuge zum Schneiden. Dann ohne App über die CLI: die Teile
// sind Zukaufteile in der Kosovnica und Körper im Messbericht. Läuft ohne App, nur mit Python.
// Aufruf: npm run test:hardware (SOMA_PYTHON zeigt auf das Python mit cadquery).
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { checker, cleanup } from './harness.mjs';

const t = checker();
const { check } = t;

const PY = process.env.SOMA_PYTHON || path.join(process.env.LOCALAPPDATA ?? '', 'soma-dev', 'venv', 'Scripts', 'python.exe');
const py = (args, opts = {}) => spawnSync(PY, ['-m', 'soma', ...args], {
  encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' }, ...opts,
});

const LIB_CHECKS = String.raw`
import json
import math
import cadquery as cq
from soma.fasteners import Screw, Nut, Washer, RetainingRing, ShaftKey, ORing, lengths, standards, _plain_rows

COS30 = math.cos(math.radians(30))

def out(label, ok, detail=""):
    print(json.dumps([label, bool(ok), str(detail)[:110]]), flush=True)

def bb(s):
    b = s.BoundingBox()
    return (b.xmin, b.xmax, b.ymin, b.ymax, b.zmin, b.zmax)

def near(a, b, tol=0.01):
    return abs(a - b) <= tol

def raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False

def dia_at(shape, z, th=0.02):
    """Durchmesser des Querschnitts bei z: beweist, dass dort wirklich ein Absatz ist."""
    box = cq.Solid.makeBox(200, 200, th, cq.Vector(-100, -100, z - th / 2))
    return shape.intersect(box).BoundingBox().xlen

def cyl(d, z0, z1):
    return cq.Solid.makeCylinder(d / 2, z1 - z0, cq.Vector(0, 0, z0), cq.Vector(0, 0, 1))

# --- G3: Schulter- und Flachkopfschraube ------------------------------------------------------------------------------

s = Screw("ISO 7379", "M6x25", at=(0, 0, 0))
d = s.dims
box = bb(s.shape)
out("ISO 7379 M6x25: ein Koerper, Kopf ueber der Schulter, Gewindeende darunter",
    len(s.shape.Solids()) == 1 and s.shape.isValid() and near(s.shoulder, d["ds"], 1e-9)
    and near(s.length, 25, 1e-9) and near(s.shank_length, 25 + d["b"], 1e-9)
    and near(box[5], d["k"], 1e-6) and near(box[4], -(25 + d["b"]), 1e-6),
    (len(s.shape.Solids()), round(box[4], 2), round(box[5], 2)))

# Der Freistich ist enger als das Gewinde: als Vereinigung von Zylindern entstuende dort eine Bohrung
mid = -(25 + d["g2"] / 2)
out("Freistich ist eine Nut, keine Bohrung: Schulter %s, Freistich %s, Gewinde 6" % (d["ds"], d["dg2"]),
    near(dia_at(s.shape, -12.5), d["ds"]) and near(dia_at(s.shape, mid), d["dg2"]) and near(dia_at(s.shape, -(25 + d["g2"] + 2)), 6.0),
    (round(dia_at(s.shape, -12.5), 2), round(dia_at(s.shape, mid), 2), round(dia_at(s.shape, -(25 + d["g2"] + 2)), 2)))

out("Laengen ISO 7379 M5 sind die Schulterlaengen der Tabelle",
    lengths("ISO 7379", "M5")[:5] == [10.0, 12.0, 16.0, 20.0, 25.0], lengths("ISO 7379", "M5")[:5])

h = s.shoulder_hole(fit=0.02)
out("shoulder_hole: Durchmesser Schulter + Passung, Tiefe bis unter die Schulter",
    near(bb(h)[1] - bb(h)[0], d["ds"] + 0.02, 1e-6) and bb(h)[5] > 0.0 and bb(h)[4] <= -(25 + 1.0) + 1e-6,
    (round(bb(h)[1] - bb(h)[0], 3), round(bb(h)[4], 2)))

c = s.clearance_hole()
out("clearance_hole reicht ueber das Gewindeende hinaus, nicht nur ueber die Schulter",
    bb(c)[4] <= -(25 + d["b"]), round(bb(c)[4], 2))

lo = Screw("OpenBuilds", "M5x10", at=(0, 0, 0))
std = Screw("ISO 4762", "M5x10", at=(0, 0, 0))
out("Flachkopf M5: Kopf 9 mm breit und 1,5 mm hoch, flacher als ISO 4762 (%s mm)" % std.head_height,
    near(lo.head_diameter, 9.0, 1e-9) and near(lo.head_height, 1.5, 1e-9) and lo.head_height < std.head_height,
    (lo.head_diameter, lo.head_height, std.head_height))

out("DIN 7984 wird nicht still umgedeutet, sondern erklaert", raises(lambda: Screw("DIN 7984", "M5x10", at=(0, 0, 0))))

# --- G5: Sprengringe ---------------------------------------------------------------------------------------------------

for std_name, table in (("DIN 471", "din471.csv"), ("DIN 472", "din472.csv")):
    rows = _plain_rows(table, None, ("d3", "a", "b", "d5", "s", "d2", "m"))
    bad = []
    for d1 in rows:
        r = RetainingRing(std_name, d1, at=(0, 0, 0))
        if not (near(r.free_diameter, rows[d1]["d3"], 1e-9) and near(r.thickness, rows[d1]["s"], 1e-9)
                and near(r.groove_diameter, rows[d1]["d2"], 1e-9) and near(r.groove_width, rows[d1]["m"], 1e-9)):
            bad.append(d1)
    out("%s: alle %d Groessen liefern d3, Dicke und Nutmaße der Tabelle" % (std_name, len(rows)), not bad, bad[:3])

bad = []
for std_name, d1 in (("DIN 471", 20), ("DIN 471", 8), ("DIN 472", 20), ("DIN 472", 12)):
    r = RetainingRing(std_name, d1, at=(0, 0, 0))
    s_, box = r.shape, bb(r.shape)
    ok = (len(s_.Solids()) == 1 and s_.isValid()
          and near(box[4], 0.0, 1e-6) and near(box[5], r.thickness, 1e-6))  # wie eine Scheibe: bei at, nach aussen
    if not ok:
        bad.append((std_name, d1, len(s_.Solids()), round(box[4], 2), round(box[5], 2)))
out("Vier Ringe: ein Koerper, Dicke ab at nach aussen wie eine Scheibe", not bad, bad[:3])

r = RetainingRing("DIN 471", 20, at=(0, 0, 0))
d = r.dims
r_out, r_in = d["d3"] / 2 + d["b"], d["d3"] / 2
gap = cq.Solid.makeBox(0.2, 0.2, d["s"], cq.Vector(-0.1, r_out - 0.1, 0.0))
lug = cq.Solid.makeBox(0.2, 0.2, d["s"], cq.Vector(d["d5"] / 2 + d["a"] - 0.3, r_out + d["a"] - 0.3, 0.0))
out("Ring ist offen (Spalt leer) und hat die Nase mit Loch",
    r.shape.intersect(gap).Volume() < 1e-6 and r.shape.intersect(lug).Volume() > 1e-3,
    (round(r.shape.intersect(gap).Volume(), 4), round(r.shape.intersect(lug).Volume(), 3)))

g = r.groove()
gb = bb(g)
out("Nut zum Ring: Boden bei d2, Breite m, zentriert auf den Ring",
    near(gb[1] - gb[0], r.d + 2.0, 1e-6) and near(gb[5] - gb[4], d["m"], 1e-6)
    and near(gb[4], -(d["m"] - d["s"]) / 2, 1e-6),
    (round(gb[1] - gb[0], 2), round(gb[5] - gb[4], 2), round(gb[4], 3)))

gi = RetainingRing("DIN 472", 20, at=(0, 0, 0)).groove()
out("Nut im Gehaeuse: Boden bei d2, Werkzeug beginnt an der Bohrung",
    near(bb(gi)[1] - bb(gi)[0], RetainingRing("DIN 472", 20, at=(0, 0, 0)).groove_diameter + 2.0, 1e-6),
    round(bb(gi)[1] - bb(gi)[0], 2))

# --- G6: Passfeder -----------------------------------------------------------------------------------------------------

rows = _plain_rows("shaft_key_parameters.csv", "din6885", ("b", "h", "t2", "t4"))
bad = []
for d1 in rows:
    k = ShaftKey(d1, 40, at=(0, 0, 0))
    if not (near(k.width, rows[d1]["b"], 1e-9) and near(k.height, rows[d1]["h"], 1e-9)
            and near(k.shaft_depth, rows[d1]["t4"], 1e-9) and near(k.hub_depth, rows[d1]["t2"], 1e-9)):
        bad.append(d1)
out("DIN 6885: alle %d Groessen liefern b, h und beide Nuttiefen der Tabelle" % len(rows), not bad, bad[:3])

k = ShaftKey(20, 40, at=(0, 0, 0))
box = bb(k.shape)
out("Passfeder 6x6x40 auf 20er Welle: sitzt 3,5 mm in der Welle und 2,5 mm heraus",
    len(k.shape.Solids()) == 1 and k.shape.isValid()
    and near(box[1] - box[0], 40, 1e-6) and near(box[3] - box[2], 6, 1e-6)
    and near(box[4], -k.shaft_depth, 1e-6) and near(box[5], k.height - k.shaft_depth, 1e-6),
    (round(box[1] - box[0], 2), round(box[4], 2), round(box[5], 2)))

ks, kh = k.keyway("shaft"), k.keyway("hub")
out("Nuten: Welle gerundet und t4 tief, Nabe eckig und t2 tief",
    near(bb(ks)[5] - bb(ks)[4], k.shaft_depth, 1e-6) and near(bb(kh)[5] - bb(kh)[4], k.hub_depth, 1e-6)
    and near(bb(ks)[3] - bb(ks)[2], k.width, 1e-6),
    (round(bb(ks)[5] - bb(ks)[4], 2), round(bb(kh)[5] - bb(kh)[4], 2)))

out("keyway kennt nur Welle und Nabe", raises(lambda: k.keyway("bore")))
out("ShaftKey(20, 40) und ShaftKey(\"DIN 6885\", 20, 40) sind dasselbe",
    ShaftKey(20, 40, at=(0, 0, 0)).designation == ShaftKey("DIN 6885", 20, 40, at=(0, 0, 0)).designation
    == "DIN 6885 6x6x40")

# --- G8: Schlitzkopf, Muttern- und Scheibenvarianten -------------------------------------------------------------------

pan = Screw("ISO 1580", "M3x10", at=(0, 0, 0))
cheese = Screw("ISO 1207", "M3x10", at=(0, 0, 0))
sock = Screw("ISO 4762", "M3x10", at=(0, 0, 0))
out("Schlitzkopf M3: Kopf aus der Tabelle, halb so hoch wie Inbus (1,8 gegen 3,0), keine Schluesselweite",
    len(pan.shape.Solids()) == 1 and near(pan.head_diameter, 5.6, 1e-9) and near(pan.head_height, 1.8, 1e-9)
    and pan.key is None and near(cheese.head_diameter, 5.5, 1e-9) and near(cheese.head_height, 2.0, 1e-9)
    and cheese.key is None and pan.head_height < sock.head_height,
    (pan.head_diameter, pan.head_height, sock.head_height, pan.key))

fn = Nut("DIN 1665", "M6", at=(0, 0, 0))
d = fn.dims
out("DIN 1665 M6: Bund %s breit und %s hoch, darueber der Sechskant" % (d["dc"], d["c"]),
    len(fn.shape.Solids()) == 1 and fn.shape.isValid()
    and near(dia_at(fn.shape, 0.5), d["dc"], 0.01) and near(dia_at(fn.shape, 5.0), d["s"] / COS30, 0.01)
    and near(bb(fn.shape)[5], d["m"], 1e-6),
    (round(dia_at(fn.shape, 0.5), 2), round(dia_at(fn.shape, 5.0), 2), round(bb(fn.shape)[5], 2)))

cn = Nut("DIN 1587", "M6", at=(0, 0, 0))
d = cn.dims
over = cq.Solid.makeBox(0.5, 0.5, 0.5, cq.Vector(-0.25, -0.25, d["m"] + 0.2))
inbore = cq.Solid.makeBox(0.5, 0.5, 0.5, cq.Vector(-0.25, -0.25, 0.5))
out("DIN 1587 M6: geschlossen, Kuppe %s hoch, das Gewinde geht nicht durch" % (d["dk"] / 2),
    len(cn.shape.Solids()) == 1 and near(bb(cn.shape)[5], d["m"] + d["dk"] / 2, 0.02)
    and near(cn.overall_height, d["m"] + d["dk"] / 2, 1e-9) and near(cn.outer[2], cn.overall_height, 1e-9)
    and cn.shape.intersect(over).Volume() > 0.1 and cn.shape.intersect(inbore).Volume() < 1e-6,
    (round(bb(cn.shape)[5], 2), round(cn.shape.intersect(over).Volume(), 3)))

ft, ct = fn.trap(), cn.trap()
out("trap: Bundmutter bekommt ein rundes Lager fuer den Bund, Hutmutter ein Loch ueber die Kuppe",
    near(dia_at(ft, 0.5), 14.6, 0.01) and near(dia_at(ft, 3.0), 10.4 / COS30, 0.01)
    and near(bb(ct)[1] - bb(ct)[0], 9.9, 1e-6) and near(bb(ct)[5], 5.0 + 9.5 / 2 + 0.2, 1e-6),
    (round(dia_at(ft, 0.5), 2), round(bb(ct)[1] - bb(ct)[0], 2), round(bb(ct)[5], 2)))

out("Ein Schlitz ist fuer Sechskant und Vierkant, nicht fuer Bund und Kuppe",
    raises(lambda: Nut("DIN 1665", "M6", at=(0, 0, 0)).trap(slot="+X", slot_length=20))
    and raises(lambda: Nut("DIN 1587", "M6", at=(0, 0, 0)).trap(slot="+X", slot_length=20))
    and len(Nut("DIN 557", "M6", at=(0, 0, 0)).trap(slot="+X", slot_length=20).Solids()) == 1)

cw = Washer("ISO 7090", "M5", at=(0, 0, 0))
out("ISO 7090 M5: Maße aus der Tabelle, Loch offen",
    len(cw.shape.Solids()) == 1 and near(cw.inner, 5.3, 1e-9) and near(cw.outer_diameter, 10.0, 1e-9)
    and near(cw.thickness, 1.1, 1e-9)
    and cw.shape.intersect(cq.Solid.makeBox(1, 1, 3, cq.Vector(-0.5, -0.5, -1))).Volume() < 1e-6,
    (cw.inner, cw.outer_diameter, cw.thickness))

tw = Washer("DIN 6797", "M3", at=(0, 0, 0))
teeth = tw.shape.intersect(cyl(3.1, -1, 1).cut(cyl(2.4, -2, 2)))
out("DIN 6797 M3: %d Innenzaehne, die in die Bohrung greifen" % tw.dims["n"],
    len(tw.shape.Solids()) == 1 and near(bb(tw.shape)[1] - bb(tw.shape)[0], 6.0, 1e-6)
    and len(teeth.Solids()) == int(tw.dims["n"]) and teeth.Volume() > 0.1,
    (len(teeth.Solids()), round(teeth.Volume(), 3)))

# --- G7: O-Ringe -------------------------------------------------------------------------------------------------------

o = ORing("025", at=(0, 0, 0))
box = bb(o.shape)
torus = 2 * math.pi ** 2 * o.major_radius * o.minor_radius ** 2
out("O-Ring 025: ein Koerper, Mittelebene in at, Aussen- und Innendurchmesser aus der Tabelle",
    len(o.shape.Solids()) == 1 and o.shape.isValid()
    and near(box[1] - box[0], o.outer_diameter, 0.02) and near(box[5], o.width / 2, 1e-6)
    and near(box[4], -o.width / 2, 1e-6) and near(o.shape.Volume(), torus, 0.02 * torus),
    (round(box[1] - box[0], 2), round(box[4], 2), round(box[5], 2), round(o.shape.Volume(), 1)))

out("Die Groesse ist eine Nummer, kein Durchmesser: 12.5 wird abgelehnt, 25 zu 025",
    raises(lambda: ORing("12.5", at=(0, 0, 0))) and ORing(25, at=(0, 0, 0)).dash_number == "025"
    and ORing("-025", at=(0, 0, 0)).dash_number == "025")

sizes = ORing.for_inner_diameter(30, 1.78)
out("for_inner_diameter(30, 1.78) findet 025 und 026 — die Nummer allein sagt das nicht",
    sizes == ["025", "026"] and near(ORing(sizes[0], at=(0, 0, 0)).inner_diameter, 29.87, 1e-9)
    and near(ORing(sizes[1], at=(0, 0, 0)).inner_diameter, 31.47, 1e-9), sizes)

spec = o.gland_spec("shaft")
out("Nutmaße: Breite aus der Tabelle, Tiefe als Mittel von min und max, Radius als Mittel von min und max",
    near(spec["width"], 2.41, 1e-9) and near(spec["depth"], (1.27 + 1.4) / 2, 1e-9)
    and near(spec["radius"], (0.13 + 0.38) / 2, 1e-9) and near(spec["squeeze_max"], 0.58, 1e-9),
    (spec["width"], round(spec["depth"], 3), round(spec["radius"], 3)))

shaft = cq.Workplane().circle(o.inner_diameter / 2 + spec["depth"]).extrude(20).translate((0, 0, -10)).val()
cut = shaft.cut(o.gland("shaft"))
wall = cq.Solid.makeBox(0.04, 0.04, 0.04, cq.Vector(o.inner_diameter / 2 + 0.2, -0.02, -0.02))
out("Nut in der Welle: Grund ist der Innendurchmesser des Ringes, die Welle ist um die Tiefe dicker",
    near(dia_at(cut, 0.0), o.inner_diameter, 0.01)
    and near(dia_at(cut, 5.0), o.inner_diameter + 2 * spec["depth"], 0.01)
    and cut.intersect(wall).Volume() < 1e-6 and near(bb(o.gland("shaft"))[5] - bb(o.gland("shaft"))[4], spec["width"], 1e-6),
    (round(dia_at(cut, 0.0), 2), round(dia_at(cut, 5.0), 2)))

housing = cq.Workplane().circle(25).circle(o.outer_diameter / 2).extrude(20).translate((0, 0, -10)).val()
bore = housing.cut(o.gland("bore"))
inside = cq.Solid.makeBox(0.04, 0.04, 0.04, cq.Vector(o.outer_diameter / 2 + 0.2, -0.02, -0.02))
outside = cq.Solid.makeBox(0.04, 0.04, 0.04, cq.Vector(o.outer_diameter / 2 + 0.2, -0.02, 5.0))
out("Nut in der Bohrung: Grund liegt um die Tiefe hinter dem Aussendurchmesser",
    bore.intersect(inside).Volume() < 1e-6 and bore.intersect(outside).Volume() > 1e-9
    and len(bore.Solids()) == 1,
    (round(bore.intersect(inside).Volume(), 6), round(bore.intersect(outside).Volume(), 6)))

plate = cq.Workplane().circle(25).extrude(10).translate((0, 0, -10)).val()
face = plate.cut(o.gland("face"))
deep = cq.Solid.makeBox(0.04, 0.04, 0.04, cq.Vector(o.major_radius - 0.02, -0.02, -0.3))
floor = cq.Solid.makeBox(0.04, 0.04, 0.04, cq.Vector(o.major_radius - 0.02, -0.02, -o.width / 2 - 0.3))
out("Nut in der Stirnflaeche: Grund auf der Unterseite des Ringes, Dichtflaeche eine Tiefe darueber",
    near(bb(o.gland("face"))[5], -o.width / 2 + o.gland_spec("face")["depth"] + 1.0, 1e-6)
    and face.intersect(deep).Volume() < 1e-6 and face.intersect(floor).Volume() > 1e-9,
    (round(bb(o.gland("face"))[5], 3), round(face.intersect(deep).Volume(), 6)))

out("Stuetzringe und Stirnflaechennuten werden abgelehnt, wo die Tabelle sie nicht kennt",
    raises(lambda: ORing("001", at=(0, 0, 0)).gland(backing_rings=1))
    and ORing("025", at=(0, 0, 0)).gland_spec(backing_rings=2)["width"] > o.gland_spec()["width"]
    and raises(lambda: o.gland("face", "dynamic")) and raises(lambda: o.gland("piston")))

# --- G9, G10, G11, G4: Werkzeuge und Meldungen -------------------------------------------------------------

s6 = Screw("ISO 4762", "M6x20", at=(0, 0, 0))
soft, hard = s6.tap_drill, s6.tap_drill_for("hard")
out("Kernloch: Stahl bekommt einen anderen Bohrer als Aluminium (M6: 5,0 gegen 5,4)",
    near(soft, 5.0, 1e-9) and near(hard, 5.4, 1e-9)
    and near(bb(s6.tap_hole())[1] - bb(s6.tap_hole())[0], soft, 1e-6)
    and near(bb(s6.tap_hole(material="hard"))[1] - bb(s6.tap_hole(material="hard"))[0], hard, 1e-6),
    (soft, hard))
out("tap_hole kennt nur weich und hart", raises(lambda: s6.tap_hole(material="wood")))

w = Washer("ISO 7089", "M3", at=(0, 0, 0))
wb = bb(w.trap())
out("Washer.trap: rundes Lager fuer eine versenkte Scheibe",
    near(wb[1] - wb[0], w.outer_diameter + 0.4, 1e-6) and near(wb[5] - wb[4], w.thickness + 0.2 + 1.0, 1e-6),
    (round(wb[1] - wb[0], 2), round(wb[5] - wb[4], 2)))

msgs = []
for bad in ("M10x1.25x40", "M10x1.25"):
    try:
        Screw("ISO 4762", bad, at=(0, 0, 0))
    except ValueError as e:
        msgs.append("pitch" in str(e) and "coarse" in str(e))
out("Feinheiten werden als Steigung erkannt und erklaert, nicht als Laenge", len(msgs) == 2 and all(msgs), msgs)

out("Gewindelaenge: ISO 4014 und DIN 931 nach der Regel 2d+6, ISO 4017 ganz",
    near(Screw("ISO 4014", "M10x50", at=(0, 0, 0)).thread_length, 26, 1e-9)
    and near(Screw("DIN 931", "M16x100", at=(0, 0, 0)).thread_length, 38, 1e-9)
    and near(Screw("ISO 4017", "M10x50", at=(0, 0, 0)).thread_length, 50, 1e-9),
    (Screw("ISO 4014", "M10x50", at=(0, 0, 0)).thread_length, Screw("ISO 4017", "M10x50", at=(0, 0, 0)).thread_length))

st = standards()
out("standards() nennt die neuen Familien",
    "DIN 471" in st["retaining_rings"] and "DIN 472" in st["retaining_rings"]
    and "DIN 6885" in st["shaft_keys"] and "ISO 7379" in st["screws"] and "OpenBuilds" in st["screws"],
    sorted(st))
out("standards() kennt auch die Varianten: Schlitzkopf, Bund- und Hutmutter, Fasen- und Zahnscheibe",
    "ISO 1580" in st["screws"] and "ISO 1207" in st["screws"]
    and "DIN 1665" in st["nuts"] and "DIN 1587" in st["nuts"]
    and "ISO 7090" in st["washers"] and "DIN 6797" in st["washers"] and "ISO 3601" in st["o_rings"],
    (sorted(st["nuts"]), sorted(st["washers"])))
`;

const MODEL = `import cadquery as cq
from soma import add_part
from soma.fasteners import Screw, Nut, Washer, RetainingRing, ShaftKey, ORing

add_part("Shaft", cq.Workplane().circle(10).extrude(60))
add_part("Ring", RetainingRing("DIN 471", 20, at=(0, 0, 55)))
add_part("Key", ShaftKey(20, 40, at=(0, 10, 20)))
add_part("Pin", Screw("ISO 7379", "M6x25", at=(30, 0, 0), direction="+Z"))
add_part("Screw", Screw("OpenBuilds", "M5x15", at=(-30, 0, 0), direction="+Z"))
add_part("FlangeNut", Nut("DIN 1665", "M8", at=(0, -30, 0), direction="+Z"))
add_part("LockWasher", Washer("DIN 6797", "M8", at=(0, 30, 0), direction="+Z"))
add_part("Seal", ORing("019", at=(0, 0, 80)))
`;

const lib = spawnSync(PY, ['-c', LIB_CHECKS], { encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });
const lines = lib.stdout.split('\n').filter((l) => l.trim().startsWith('['));
for (const line of lines) {
  const [label, ok, detail] = JSON.parse(line);
  check(label, ok, detail);
}
check('Python-Prüfungen liefen durch', lib.status === 0 && lines.length >= 40,
  lib.status === 0 ? `${lines.length} Prüfungen` : (lib.stderr ?? '').slice(-300));

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'soma-hardware-'));
try {
  fs.writeFileSync(path.join(dir, 'model.py'), MODEL);
  fs.writeFileSync(path.join(dir, 'soma.json'), JSON.stringify({ name: 'hardware', entry: 'model.py' }));

  const bom = py(['bom', '--json', '--project', dir]);
  const doc = bom.status === 0 ? JSON.parse(bom.stdout) : null;
  const line = (kind) => doc?.purchased?.find((p) => p.kind === kind);
  const screws = (doc?.purchased ?? []).filter((p) => p.kind === 'Screw').map((p) => p.designation).sort();
  check('Kosovnica: Ring, Feder und beide Schrauben sind Zukaufteile mit Bezeichnung',
    line('RetainingRing')?.designation === 'DIN 471 20x1.2' && line('ShaftKey')?.designation === 'DIN 6885 6x6x40'
      && screws.join(' | ') === 'ISO 7379 M6x25 | OpenBuilds M5x15',
    JSON.stringify(doc?.purchased ?? bom.stderr.slice(-150)));

  check('Kosovnica: Bundmutter, Zahnscheibe und O-Ring sind eigene Zeilen, nicht als Schraube gezaehlt',
    line('Nut')?.designation === 'DIN 1665 M8' && line('Washer')?.designation === 'DIN 6797 M8'
      && line('ORing')?.designation === 'ISO 3601 019 20.35x1.78' && (doc?.purchased ?? []).length === 7,
    JSON.stringify((doc?.purchased ?? []).map((p) => `${p.kind}:${p.designation}`)));

  const insp = py(['inspect', '--json', '--project', dir]);
  const ins = insp.status === 0 ? JSON.parse(insp.stdout) : null;
  const complaints = (ins?.checks?.issues ?? []).filter((c) => c.part !== 'Shaft');
  const ring = ins?.parts?.find((p) => p.name === 'Ring');
  const key = ins?.parts?.find((p) => p.name === 'Key');
  check('Messbericht: Ring und Feder sind je ein gültiger Körper ohne Beanstandung',
    Boolean(ring) && Boolean(key) && ring.topology.solids === 1 && key.topology.solids === 1
      && ring.valid === true && key.valid === true && complaints.length === 0,
    JSON.stringify(complaints.length ? complaints : (ring ?? insp?.error ?? insp.stderr.slice(-150))));

  const once = py(['bom', '--json', '--project', dir]);
  check('Zwei Läufe liefern dieselbe Kosovnica', once.status === 0 && once.stdout === bom.stdout,
    `${bom.stdout?.length} vs ${once.stdout?.length}`);
} finally {
  cleanup(dir);
}

process.exit(t.fails ? 1 : 0);
