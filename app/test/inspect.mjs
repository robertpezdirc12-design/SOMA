// Test für `soma inspect` (Schema soma.inspect/1, inspection.py): Volumen, Hüllbox, Topologie, Prüfungen, Determinismus,
// Rundlauf Modell -> STEP -> Messung, Exit-Codes und Fehlermeldungen. Läuft ohne App, nur mit Python.
// Aufruf: npm run test:inspect (SOMA_PYTHON zeigt auf das Python mit cadquery).
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { checker, cleanup } from './harness.mjs';

const t = checker();
const { check } = t;

// Dasselbe Python wie die App (paths.ts): SOMA_PYTHON oder die Entwicklungsumgebung aus Phase 0
const PY = process.env.SOMA_PYTHON || path.join(process.env.LOCALAPPDATA ?? '', 'soma-dev', 'venv', 'Scripts', 'python.exe');
const py = (args, opts = {}) => spawnSync(PY, ['-m', 'soma', ...args], {
  encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' }, ...opts,
});

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'soma-inspect-'));
const json = (args) => {
  const r = py(['inspect', '--json', '--project', dir, ...args]);
  return { r, doc: r.status === 0 ? JSON.parse(r.stdout) : null };
};

// Eine Platte 40 x 30 x 5 mit einem Durchgangsloch Ø 4 und ein Deckel. Dazu eine Referenzfläche ohne Körper und ein
// zweites Teil mit derselben Hüllbox wie ein anderes (die Warnung dafür).
const MODEL = `import cadquery as cq
from soma import add_part, param

W = param(40.0, "Width", min=20, max=80, unit="mm")
plate = cq.Workplane().box(W, 30, 5).faces(">Z").workplane().hole(4)
add_part("Plate", plate)
add_part("Lid", cq.Workplane().box(W, 30, 3).translate((0, 0, 8)), group="Housing")
add_part("Surface", cq.Workplane("XY").rect(10, 10).val(), role="reference")
add_part("TwinA", cq.Workplane().box(5, 5, 5).translate((15, 10, 0)))
add_part("TwinB", cq.Workplane().box(5, 5, 5).translate((15, 10, 0)))
`;

try {
  fs.writeFileSync(path.join(dir, 'model.py'), MODEL);

  // 1) Dokument und Schema
  const { r, doc } = json([]);
  check('soma inspect --json läuft', r.status === 0, (r.stderr || '').slice(-200));
  const keys = Object.keys(doc ?? {}).join(',');
  check('Schema soma.inspect/1 mit fester Schlüsselfolge', doc?.schema === 'soma.inspect/1' && doc.units === 'mm'
    && keys === 'schema,soma,units,source,bounds,totals,parts,checks,ok', keys);

  // 2) Zahlen: Platte 40x30x5 minus Loch Ø4 (40*30*5 - pi*2^2*5), Deckel 40x30x3
  const plate = doc.parts.find((p) => p.name === 'Plate');
  const lid = doc.parts.find((p) => p.name === 'Lid');
  const wantPlate = 40 * 30 * 5 - Math.PI * 4 * 5;
  check('Volumen der Platte stimmt mit der Rechnung (Loch abgezogen)', Math.abs(plate.volume - wantPlate) < 0.01,
    `${plate.volume} statt ${wantPlate.toFixed(2)}`);
  check('Deckel: Volumen 3600, 6 Flächen, 1 Körper, gültig und geschlossen',
    lid.volume === 3600 && lid.topology.faces === 6 && lid.topology.solids === 1 && lid.valid === true && lid.closed === true,
    JSON.stringify(lid.topology));
  check('Hüllbox des Modells: 40 x 30 x 12 ab z = -2.5', doc.bounds.size.join() === '40,30,12'
    && doc.bounds.min.join() === '-20,-15,-2.5', JSON.stringify(doc.bounds));
  check('Summen: 5 Teile, 4 Körper, Volumen = Summe der Teile',
    doc.totals.parts === 5 && doc.totals.solids === 4 && Math.abs(doc.totals.volume - (plate.volume + 3600 + 250)) < 0.01,
    JSON.stringify(doc.totals));
  check('Gruppe des Deckels als Liste, Rolle der Referenz', lid.group.join() === 'Housing'
    && doc.parts.find((p) => p.name === 'Surface').role === 'reference', JSON.stringify(lid.group));

  // 3) Prüfungen: Referenzfläche ohne Körper ist eine Warnung, gleiche Hüllbox auch; nichts ist ein Fehler
  const codes = doc.checks.issues.map((i) => `${i.level}:${i.code}:${i.part}`).sort();
  check('Prüfungen: Referenz ohne Körper und gleiche Hüllbox als Warnung, kein Fehler',
    doc.ok === true && codes.join(' ') === 'warning:duplicate_bounds:TwinB warning:no_solid:Surface', codes.join(' '));
  check('dieselbe Fläche als eigenes Teil wäre ein Fehler', (() => {
    const d2 = fs.mkdtempSync(path.join(os.tmpdir(), 'soma-inspect2-'));
    fs.writeFileSync(path.join(d2, 'model.py'), 'import cadquery as cq\nfrom soma import add_part\n'
      + 'add_part("Surface", cq.Workplane("XY").rect(10, 10).val())\n');
    const r2 = py(['inspect', '--json', '--project', d2]);
    const strict = py(['inspect', '--strict', '--project', d2]);
    const out = { ok: JSON.parse(r2.stdout).ok, exit: strict.status };
    cleanup(d2);
    return out.ok === false && out.exit === 1;
  })(), '');

  // 4) Determinismus: zwei Läufe sind gleich (kein Zeitstempel, kein absoluter Pfad)
  const a = py(['inspect', '--json', '--project', dir]).stdout;
  const b = py(['inspect', '--json', '--project', dir]).stdout;
  check('Zwei Läufe liefern dasselbe JSON', a === b && a.length > 100, `${a.length} / ${b.length} Zeichen`);
  const tmp = os.tmpdir();
  check('Kein absoluter Pfad im Dokument, nur der Ordnername',
    !a.includes(tmp) && !a.includes(tmp.replace(/\\/g, '\\\\')) && doc.source.project === path.basename(dir),
    doc.source.project);

  // 5) Parameter stehen im Dokument, mit Quelle
  const p = doc.source.parameters.find((x) => x.name === 'W');
  check('Parameter W = 40 aus dem Code, mit Einheit', p?.value === 40 && p.source === 'code' && p.unit === 'mm', JSON.stringify(p));

  // 6) --fast lässt die Gültigkeit weg, --density rechnet die Masse, --parts filtert
  const fast = json(['--fast']).doc;
  check('--fast: valid ist null, Prüfungen laufen weiter', fast.parts[0].valid === null && fast.checks.ok === true, String(fast.parts[0].valid));
  const dens = json(['--density', '2.7']).doc;
  // mass_g ist auf vier Stellen gerundet, deshalb 1e-3 statt exakt
  check('--density 2.7: Masse = Volumen / 1000 * 2.7', Math.abs(dens.totals.mass_g - dens.totals.volume * 2.7 / 1000) < 1e-3,
    `${dens.totals.mass_g} g`);
  const one = json(['--parts', 'Lid']).doc;
  check('--parts Lid: ein Teil, Summen nur für dieses Teil', one.parts.length === 1 && one.totals.parts === 1
    && one.totals.solids === 1, JSON.stringify(one.totals));

  // --overlaps ist die einzige Prüfung, die Paare misst: ohne die Angabe steht das Feld nicht da (die Ausgabe bleibt
  // so schnell und so bytegleich wie vorher), mit ihr steht es da. Dieses Testmodell hat zwei gleiche Körper (TwinA,
  // TwinB), die absichtlich ineinander und in die Platte ragen — genau das muss herauskommen.
  const ov = json(['--overlaps']).doc;
  const pairs = (ov.overlaps ?? []).map((o) => `${o.a}/${o.b}`);
  check('--overlaps: drei Paare mit 125 mm³, 1,67 mm Tiefe und einem Ort, ohne die Angabe gar kein Feld',
    pairs.join() === 'Plate/TwinA,Plate/TwinB,TwinA/TwinB'
    && (ov.overlaps ?? []).every((o) => o.volume === 125 && o.thickness === 1.6667
      && Array.isArray(o.at) && o.at.length === 3 && o.at.every((v) => typeof v === 'number'))
    && ov.ok === false && !('overlaps' in doc),
    `${JSON.stringify(ov.overlaps)} / ohne: ${'overlaps' in doc}, ok ${ov.ok}`);

  // 7) Rundlauf: Modell -> STEP -> Messung der Datei. Anderer Code-Weg, gleiche Zahlen.
  const exp = py(['export', '--assembly', '--format', 'step', '--project', dir]);
  const step = path.join(dir, 'exports', `${path.basename(dir)}.step`);
  check('soma export --assembly schreibt eine STEP-Datei', exp.status === 0 && fs.existsSync(step), exp.stderr.slice(-160));
  const file = JSON.parse(py(['inspect', '--step', step, '--json']).stdout);
  check('STEP-Datei: gleiche Zahl Körper, gleiches Volumen, gleiche Hüllbox wie das Modell',
    file.totals.solids === doc.totals.solids && Math.abs(file.totals.volume - doc.totals.volume) < 1e-3 * doc.totals.volume
    && file.bounds.size.join() === doc.bounds.size.join(),
    `${file.totals.solids}/${doc.totals.solids} Körper, ${file.totals.volume}/${doc.totals.volume} mm³`);
  check('Namen aus der Baugruppe bleiben erhalten (Plate, Lid, TwinA, TwinB)',
    file.parts.map((x) => x.name).sort().join() === 'Lid,Plate,TwinA,TwinB', file.parts.map((x) => x.name).join(' '));

  // 8) Fehler werden erklärt, nicht gestapelt
  const unknown = py(['inspect', '--project', dir, '--parts', 'Nope']);
  check('Unbekanntes Teil: Meldung mit den vorhandenen Namen', unknown.status === 1 && /No such part: 'Nope'/.test(unknown.stderr)
    && /Plate/.test(unknown.stderr), unknown.stderr.trim().slice(-90));
  const missing = py(['inspect', '--step', path.join(dir, 'nope.step')]);
  check('Fehlende Datei: Meldung, Exit 1', missing.status === 1 && /No such file/.test(missing.stderr), missing.stderr.trim().slice(-60));
  const bad = py(['inspect', '--step', path.join(dir, 'model.py')]);
  check('Falsche Endung: unterstützte Formate genannt', bad.status === 1 && /Supported: \.step, \.stp, \.brep/.test(bad.stderr),
    bad.stderr.trim().slice(-60));
  const broken = fs.mkdtempSync(path.join(os.tmpdir(), 'soma-inspect3-'));
  fs.writeFileSync(path.join(broken, 'model.py'), 'raise RuntimeError("kaputt")\n');
  const br = py(['inspect', '--json', '--project', broken]);
  check('Modell baut nicht: JSON mit ok=false und der Fehlermeldung, Exit 1',
    br.status === 1 && JSON.parse(br.stdout).ok === false && /kaputt/.test(br.stdout), br.stdout.slice(0, 90));
  cleanup(broken);

  // 9) --out schreibt eine eingerückte Datei, die dasselbe aussagt
  const outFile = path.join(dir, 'report.json');
  const w = py(['inspect', '--project', dir, '--out', outFile]);
  const written = fs.existsSync(outFile) ? JSON.parse(fs.readFileSync(outFile, 'utf8')) : null;
  check('--out schreibt dasselbe Dokument als Datei', w.status === 0 && written?.totals.parts === doc.totals.parts
    && fs.readFileSync(outFile, 'utf8').includes('\n  "'), String(written?.schema));
} catch (e) {
  console.log('ABBRUCH:', e.message);
  t.fail();
}
cleanup(dir);
console.log(t.fails ? `\n${t.fails} Prüfung(en) fehlgeschlagen` : '\nALLE PRÜFUNGEN BESTANDEN');
process.exit(t.fails ? 1 : 0);
