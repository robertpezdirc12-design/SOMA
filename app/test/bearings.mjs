// Test für die Wälzlager (soma.fasteners.Bearing, Lücke G1): Maße aus den Tabellen, ein Körper, freie Bohrung, exakte
// Hülle, Deckel, Katalogmasse, Lage, Fehlermeldungen mit Vorschlag. Dann ohne App über die CLI: das Lager ist ein
// Zukaufteil in der Kosovnica (eine Zeile, Anzahl 2) und ein Körper im Messbericht. Läuft ohne App, nur mit Python.
// Aufruf: npm run test:bearings (SOMA_PYTHON zeigt auf das Python mit cadquery).
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

// Jede Prüfung als JSON-Zeile [Text, ok, Detail]
const LIB_CHECKS = String.raw`
import json
import cadquery as cq
from soma.fasteners import Bearing, standards, _bearing_index, _bearing_local

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

# 1) Jede Bezeichnung aller fünf Tabellen findet ihre Zeile und liefert die Maße der Tabelle
idx = _bearing_index()
bad = []
for name, hits in idx.items():
    if len(hits) != 1:
        bad.append((name, "rows", len(hits)))
        continue
    row = hits[0][1]
    b = Bearing(name, at=(0, 0, 0))
    # Bei den Kegelrollenlagern ist T die Breite über alles, B nur die Innenringbreite
    want = (float(row["SKT:d"]), float(row["SKT:D"]), float(row.get("SKT:T") or row["SKT:B"]))
    if not (near(b.bore, want[0], 1e-6) and near(b.diameter, want[1], 1e-6) and near(b.width, want[2], 1e-6)):
        bad.append((name, want, (b.bore, b.diameter, b.width)))
out("Alle %d Bezeichnungen der Tabellen liefern ihre Maße" % len(idx), not bad and len(idx) > 50, bad[:3])

# 2) Ein Körper, exakte Hülle, freie Bohrung
cases = ["608", "6000", "6200", "6300", "623", "624", "618/4", "619/8-2Z", "E2.608-2Z", "630/8-2RS1"]
bad = []
for name in cases:
    b = Bearing(name, at=(0, 0, 0))
    s = b.shape
    box = bb(s)
    probe = cq.Solid.makeCylinder(b.bore / 2 - 0.05, 4 * b.width, cq.Vector(0, 0, -2 * b.width), cq.Vector(0, 0, 1))
    free = s.intersect(probe).Volume()
    good = (s.isValid() and len(s.Solids()) == 1
            and near(box[1] - box[0], b.diameter, 1e-3) and near(box[3] - box[2], b.diameter, 1e-3)
            and near(box[4], 0.0, 1e-6) and near(box[5], b.width, 1e-6) and free < 1e-6)
    if not good:
        bad.append((name, len(s.Solids()), round(box[5] - box[4], 2), round(free, 4)))
out("Zehn Lager: ein Körper, Hülle = D x D x B, Bohrung frei", not bad, bad[:3])

# 3) Katalogmasse: gesetzt, positiv und größer als die Stahlmasse der gezeichneten Hülle
bad = []
for name in ("608", "623", "6000", "6200", "6300"):
    b = Bearing(name, at=(0, 0, 0))
    steel = b.shape.Volume() * 7.85e-3
    if not (b.mass_g and b.mass_g > 0 and steel < b.mass_g):
        bad.append((name, b.mass_g, round(steel, 2)))
out("Katalogmasse gesetzt und größer als die Stahlmasse der Hülle", not bad, bad[:3])

# 4) Gedeckelt: erkannt, gleiche Hülle, mehr Material als das offene Lager
o, c = Bearing("623", at=(0, 0, 0)), Bearing("623-2Z", at=(0, 0, 0))
out("623-2Z gedeckelt, gleiche Hülle, mehr Material als 623",
    c.capped and not o.capped and near(c.diameter, o.diameter) and near(c.width, o.width) and c.shape.Volume() > o.shape.Volume(),
    (round(o.shape.Volume(), 2), round(c.shape.Volume(), 2)))

# 5) Selbstauskunft
out("standards() nennt alle fünf Lagerfamilien", len(standards()["bearings"]) == 5, list(standards()["bearings"].values()))

# 5b) Die drei neuen Familien: Art, Breite, Masse, und die Kegelrollenbreite ist T statt B
ang = Bearing("7200 BECBP", at=(0, 0, 0))
cyl = Bearing("NJ 202 ECP", at=(0, 0, 0))
tap = Bearing("30302 J2", at=(0, 0, 0))
row = _bearing_index()["30302 J2"][0][1]
out("Drei neue Familien mit ihrer Art und ihrer Massenspalte",
    ang.kind == "ball" and cyl.kind == "roller" and tap.kind == "roller"
    and ang.mass_g == 30.0 and cyl.mass_g == 48.0 and tap.mass_g == 94.0,
    (ang.kind, cyl.kind, tap.kind, ang.mass_g, cyl.mass_g, tap.mass_g))
out("Kegelrollenlager: Breite ist T (14,25), nicht B (13) — sonst 1,25 mm zu dünn",
    near(tap.width, float(row["SKT:T"])) and not near(tap.width, float(row["SKT:B"]))
    and near(bb(tap.shape)[5] - bb(tap.shape)[4], float(row["SKT:T"]), 1e-3),
    (tap.width, row["SKT:T"], row["SKT:B"]))

# 5c) Eine Walze ist keine Kugel: bei gleicher Hülle füllt sie den Ringraum deutlich mehr
ball = _bearing_local(15, 35, 11, "ball", False)
roll = _bearing_local(15, 35, 11, "roller", False)
out("Walzenlager wird als Walze gezeichnet, nicht als Kugellager",
    roll.Volume() > 1.1 * ball.Volume(), (round(ball.Volume(), 1), round(roll.Volume(), 1)))

# 6) Fehler: unbekannte Nummer mit Vorschlag, leere Nummer, unbekannte Familie
try:
    Bearing("608-2Z")
    msg = "keine Ausnahme"
except ValueError as e:
    msg = str(e)
out("608-2Z gibt es nicht: Vorschlag E2.608-2Z", "Did you mean" in msg and "E2.608-2Z" in msg, msg[:95])
out("Leere Bezeichnung: Fehler", raises(lambda: Bearing("   ")))
out("Unbekannte Familie: Fehler", raises(lambda: Bearing("608", family="kegelrollen")))
out("family= wählt unter fünf Familien", Bearing("30302 J2", family="tapered", at=(0, 0, 0)).kind == "roller"
    and Bearing("NJ 202 ECP", family="cylindrical", at=(0, 0, 0)).kind == "roller"
    and Bearing("7200 BECBP", family="angular", at=(0, 0, 0)).kind == "ball"
    and raises(lambda: Bearing("30302 J2", family="deep groove")))

# 7) Lage: at, direction, outer, sunk
b = Bearing("608", at=(10, 20, 30), direction="-Z")
box = bb(b.shape)
out("at/direction: sitzt bei at und reicht B nach außen",
    near(box[0] + box[1], 20, 1e-6) and near(box[2] + box[3], 40, 1e-6)
    and near(box[4], 30, 1e-6) and near(box[5], 30 + b.width, 1e-6) and near(b.outer[2], 30 + b.width, 1e-6),
    [round(v, 2) for v in box])
b2 = Bearing("608", at=(0, 0, 0), sunk=2.0)
out("sunk=2: Außenfläche 2 mm tiefer", near(bb(b2.shape)[5], -2.0, 1e-6), round(bb(b2.shape)[5], 3))
`;

// Ein Gehäuse mit zwei Lagern: die Kosovnica muss daraus eine Zeile mit Anzahl 2 machen.
const MODEL = `import cadquery as cq
from soma import add_part
from soma.fasteners import Bearing

add_part("Housing", cq.Workplane().box(40, 40, 20))
add_part("Bearing 1", Bearing("608", at=(0, 0, 20)), group="Hardware/Bearings")
add_part("Bearing 2", Bearing("608", at=(0, 0, 13)), group="Hardware/Bearings")
`;

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'soma-bearings-'));
try {
  fs.writeFileSync(path.join(dir, 'model.py'), MODEL);
  fs.writeFileSync(path.join(dir, 'soma.json'), JSON.stringify({ name: 'bearings', entry: 'model.py' }));

  const lib = spawnSync(PY, ['-c', LIB_CHECKS], {
    encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  });
  const lines = (lib.stdout ?? '').split('\n').filter((l) => l.startsWith('['));
  for (const l of lines) {
    const [label, ok, detail] = JSON.parse(l);
    check(label, ok, ok ? '' : detail);
  }
  check('Python-Prüfungen liefen durch', lib.status === 0 && lines.length >= 10,
    lib.status !== 0 ? (lib.stderr ?? '').slice(-300) : String(lines.length));

  const bom = py(['bom', '--json', '--project', dir]);
  const doc = bom.status === 0 ? JSON.parse(bom.stdout) : null;
  const line = doc?.purchased?.find((p) => p.kind === 'Bearing');
  check('Kosovnica: das Lager ist ein Zukaufteil mit Bezeichnung und Anzahl 2',
    Boolean(line) && line.designation === '608' && line.count === 2,
    JSON.stringify(doc?.purchased ?? bom.stderr.slice(-150)));

  const insp = py(['inspect', '--json', '--project', dir]);
  const ins = insp.status === 0 ? JSON.parse(insp.stdout) : null;
  const bearing = ins?.parts?.find((p) => p.name === 'Bearing 1');
  const complaints = (ins?.checks?.issues ?? []).filter((c) => c.part === 'Bearing 1');
  check('Messbericht: das Lager ist ein gültiger, geschlossener Körper mit 8 mm Bohrung',
    Boolean(bearing) && bearing.topology.solids === 1 && bearing.valid === true && bearing.closed === true
      && complaints.length === 0,
    JSON.stringify(complaints.length ? complaints : (bearing ?? insp?.error ?? insp.stderr.slice(-150))));

  const parts = ins?.parts?.map((p) => `${p.name}:${p.role}`) ?? [];
  check('Rollen: Lager "hardware", Gehäuse "part"',
    parts.includes('Bearing 1:hardware') && parts.includes('Housing:part'), parts.join(' '));

  const once = py(['bom', '--json', '--project', dir]);
  check('Zwei Läufe liefern dieselbe Kosovnica', once.status === 0 && once.stdout === bom.stdout,
    `${bom.stdout?.length} vs ${once.stdout?.length}`);
} finally {
  cleanup(t, dir);
}
