// Test für die Kosovnica (soma bom, Schema soma.bom/1, bom.py): gekaufte Teile nach Bezeichnung mit Anzahl,
// Teilenummer der Gewindeeinsätze, von Hand modellierte Zukaufteile, eigene Teile mit Volumen und Masse,
// --merge-identical, CSV, Referenzen, Fehler. Läuft ohne App, nur mit Python.
// Aufruf: npm run test:bom (SOMA_PYTHON zeigt auf das Python mit cadquery).
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

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'soma-bom-'));
const json = (args) => {
  const r = py(['bom', '--json', '--project', dir, ...args]);
  return { r, doc: r.status === 0 ? JSON.parse(r.stdout) : null };
};

// Gehäuse und Deckel mit vier Einsätzen und vier Schrauben, eine Klemmschraube mit Mutter und Scheibe, ein von Hand
// modelliertes Zukaufteil (Lager), zwei gleiche Winkel und eine Referenzplatine.
const MODEL = `import cadquery as cq
from soma import add_part, param
from soma.fasteners import Screw, Nut, Washer, HeatSetInsert

H = param(20.0, "Height", min=10, max=40, unit="mm")
body = cq.Workplane().box(60, 40, H, centered=(True, True, False)).faces(">Z").shell(-2)
lid = cq.Workplane().box(60, 40, 3).translate((0, 0, H))

for i, (x, y) in enumerate([(-22, -12), (22, -12), (-22, 12), (22, 12)], 1):
    ins = HeatSetInsert("M3x5.7", at=(x, y, H))
    s = Screw("ISO 4762", "M3x12", at=(x, y), on=lid)
    body = body.cut(ins.hole())
    lid = lid.cut(s.clearance_hole())
    add_part(f"Insert {i}", ins, group="Hardware/Inserts")
    add_part(f"Screw {i}", s, group="Hardware/Screws")

side = Screw("ISO 4762", "M4x16", at=(30, 0, 10), direction="-X")
nut = Nut("ISO 4032", "M4", at=side.point(7), direction="+X")
washer = Washer("ISO 7089", "M4", at=side.point(2), direction="+X")
body = body.cut(side.clearance_hole()).cut(nut.trap(slot="+Z", slot_length=14))
add_part("Clamp screw", side, group="Hardware")
add_part("Clamp nut", nut, group="Hardware")
add_part("Clamp washer", washer, group="Hardware")

add_part("Bracket", cq.Workplane().box(10, 10, 10).translate((0, 0, -8)))
add_part("Bracket 2", cq.Workplane().box(10, 10, 10).translate((0, 0, -8)))
add_part("Bearing", cq.Workplane().circle(11).extrude(7), role="hardware")
add_part("Board", cq.Workplane().box(30, 20, 1.6), role="reference")

add_part("Housing", body)
add_part("Lid", lid)
`;

try {
  fs.writeFileSync(path.join(dir, 'model.py'), MODEL);

  // 1) Dokument, Summen
  const { r, doc } = json(['--density', '2.7']);
  check('soma bom --json läuft', r.status === 0, (r.stderr || '').slice(-200));
  check('Schema soma.bom/1, Einheit mm, Quelle mit Eintrittspunkt',
    doc?.schema === 'soma.bom/1' && doc.units === 'mm' && doc.source.entry === 'model.py', JSON.stringify(doc?.source));
  check('Summen: 17 Teile, 12 gekauft, 4 eigene, 1 Referenz, 10 Zeilen',
    doc.totals.parts === 17 && doc.totals.purchased === 12 && doc.totals.manufactured === 4
    && doc.totals.references === 1 && doc.totals.items === 10, JSON.stringify(doc.totals));

  // 2) Gekaufte Teile: nach Bezeichnung gruppiert, nicht nach Name
  const screws = doc.purchased.find((x) => x.designation === 'ISO 4762 M3x12');
  check('Vier Schrauben M3x12 sind eine Zeile mit Anzahl 4 und allen Namen',
    screws?.count === 4 && screws.names.length === 4 && screws.kind === 'Screw'
    && screws.group.join() === 'Hardware/Screws', JSON.stringify(screws?.names));
  const ins = doc.purchased.find((x) => x.kind === 'HeatSetInsert');
  check('Gewindeeinsätze: Teilenummer aus der Tabelle, Anzahl 4',
    ins?.count === 4 && ins.part_number === 'GE-M3x57-001', `${ins?.part_number} x${ins?.count}`);
  const nut = doc.purchased.find((x) => x.kind === 'Nut');
  const washer = doc.purchased.find((x) => x.kind === 'Washer');
  check('Mutter und Scheibe je eine Zeile mit Anzahl 1', nut?.count === 1 && washer?.count === 1,
    `${nut?.designation} / ${washer?.designation}`);
  const bearing = doc.purchased.find((x) => x.kind === null);
  check('Von Hand modelliertes Zukaufteil (Lager): eigene Zeile ohne Bezeichnung, ohne Teilenummer',
    bearing?.designation === null && bearing.count === 1 && bearing.part_number === null, JSON.stringify(bearing));

  // 3) Eigene Teile: Volumen, Masse
  const lid = doc.manufactured.find((x) => x.name === 'Lid');
  const housing = doc.manufactured.find((x) => x.name === 'Housing');
  // Der Deckel: 60 x 40 x 3 minus vier Durchgangslöcher M3 (3,4 mm) über 3 mm
  const wantLid = 60 * 40 * 3 - 4 * Math.PI * 1.7 ** 2 * 3;
  check('Eigene Teile mit Volumen und Masse (Deckel 7200 mm³ minus vier Durchgangslöcher)',
    Math.abs(lid.volume - wantLid) < 0.1 && Math.abs(lid.mass_g - wantLid * 2.7 / 1000) < 0.01 && housing.volume > 0,
    `${lid.volume} statt ${wantLid.toFixed(2)} mm³, ${lid.mass_g} g`);
  check('Summe Volumen und Masse über die eigenen Teile',
    Math.abs(doc.totals.volume - (lid.volume + housing.volume + 1000 + 1000)) < 1
    && Math.abs(doc.totals.mass_g - doc.totals.volume * 2.7 / 1000) < 0.01, `${doc.totals.volume} mm³`);

  // 4) Referenzen sind nicht in der Liste, werden aber genannt
  check('Referenz nicht in der Liste, mit Namen gemeldet',
    !doc.manufactured.some((x) => x.name === 'Board') && !doc.purchased.some((x) => x.names.includes('Board'))
    && doc.references.count === 1 && doc.references.names.join() === 'Board', JSON.stringify(doc.references));

  // 5) --merge-identical: zwei gleiche Winkel werden eine Zeile mit Anzahl 2
  const merged = json(['--merge-identical', '--density', '2.7']).doc;
  const bracket = merged.manufactured.find((x) => x.name === 'Bracket');
  check('--merge-identical: zwei gleiche Winkel eine Zeile mit Anzahl 2 und beiden Namen',
    merged.manufactured.length === 3 && bracket?.count === 2 && bracket.names.join() === 'Bracket,Bracket 2',
    merged.manufactured.map((x) => `${x.name}x${x.count}`).join(' '));
  check('--merge-identical: Summen weiterhin ueber alle Teile, nicht nur ueber die Zeilen',
    Math.abs(merged.totals.volume - doc.totals.volume) < 0.01
    && Math.abs(merged.totals.mass_g - merged.totals.volume * 2.7 / 1000) < 0.01,
    `${merged.totals.volume}/${doc.totals.volume} mm³, ${merged.totals.mass_g} g`);
  check('ohne --merge-identical bleiben sie getrennt', doc.manufactured.length === 4
    && doc.manufactured.filter((x) => x.name.startsWith('Bracket')).length === 2, String(doc.manufactured.length));

  // 6) Ohne Dichte keine Masse, mit Dichte eine
  const noDensity = json([]).doc;
  check('ohne --density: Volumen ja, Masse nein', noDensity.manufactured.every((x) => x.mass_g === null)
    && noDensity.manufactured.every((x) => x.volume !== null) && noDensity.totals.mass_g === null,
    String(noDensity.totals.mass_g));

  // 7) CSV: Kopfzeile, BOM für Excel, eine Zeile je Listeneintrag
  const csvPath = path.join(dir, 'order.csv');
  const csvRun = py(['bom', '--project', dir, '--csv', csvPath]);
  const raw = fs.existsSync(csvPath) ? fs.readFileSync(csvPath) : null;
  const lines = raw ? raw.toString('utf8').replace(/^\uFEFF/, '').trim().split(/\r?\n/) : [];
  check('CSV: UTF-8 mit BOM, Kopfzeile, 10 Zeilen wie die Liste',
    csvRun.status === 0 && raw && raw[0] === 0xEF && lines[0] === 'type,item,part_number,count,group,volume_mm3,mass_g,names'
    && lines.length === 11, `${lines.length - 1} Zeile(n)`);
  check('CSV: gekaufte Zeile mit Anzahl, eigene Zeile mit Volumen',
    lines.some((l) => l.startsWith('purchased,ISO 4762 M3x12,,4,'))
    && lines.some((l) => l.startsWith('manufactured,Lid,,1,')), lines.find((l) => l.includes('Lid')));

  // 8) Determinismus und --out
  const a = py(['bom', '--json', '--project', dir]).stdout;
  const b = py(['bom', '--json', '--project', dir]).stdout;
  check('Zwei Läufe liefern dasselbe JSON', a === b && a.length > 200, `${a.length} Zeichen`);
  const outFile = path.join(dir, 'bom.json');
  const w = py(['bom', '--project', dir, '--out', outFile]);
  check('--out schreibt das Dokument als Datei', w.status === 0 && fs.existsSync(outFile)
    && JSON.parse(fs.readFileSync(outFile, 'utf8')).totals.parts === 17, String(w.status));

  // 9) Fehler
  const broken = fs.mkdtempSync(path.join(os.tmpdir(), 'soma-bom2-'));
  fs.writeFileSync(path.join(broken, 'model.py'), 'raise RuntimeError("kaputt")\n');
  const br = py(['bom', '--json', '--project', broken]);
  check('Modell baut nicht: JSON mit der Meldung, Exit 1',
    br.status === 1 && /kaputt/.test(br.stdout) && JSON.parse(br.stdout).schema === 'soma.bom/1', br.stdout.slice(0, 80));
  cleanup(broken);
  const empty = fs.mkdtempSync(path.join(os.tmpdir(), 'soma-bom3-'));
  fs.writeFileSync(path.join(empty, 'model.py'), 'import cadquery as cq\nfrom soma import add_part\n'
    + 'add_part("Only", cq.Workplane().box(10, 10, 10))\n');
  const one = JSON.parse(py(['bom', '--json', '--project', empty]).stdout);
  check('Modell ohne Zukaufteile: leere Liste gekaufter Teile, keine Fehlermeldung',
    one.purchased.length === 0 && one.manufactured.length === 1 && one.totals.items === 1, JSON.stringify(one.totals));
  cleanup(empty);
} catch (e) {
  console.log('ABBRUCH:', e.message);
  t.fail();
}
cleanup(dir);
console.log(t.fails ? `\n${t.fails} Prüfung(en) fehlgeschlagen` : '\nALLE PRÜFUNGEN BESTANDEN');
process.exit(t.fails ? 1 : 0);
