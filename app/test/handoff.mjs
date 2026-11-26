// Test für den Draftwright-Übergang (docs/DRAFTWRIGHT-HANDOFF.md): der Beispielauftrag wird in einen temporären Ordner
// kopiert, gebaut und gemessen, und dann wird das Ergebnis gegen inputs/draftwright.json gehalten — jede gemessene Zahl
// als param() mit demselben Wert, jede Zahl, die keiner ist, als Konstante mit Begründung, und bounds.size als die Platte,
// die das JSON beschreibt. Zuletzt wird dasselbe Modell mit einer falschen Dicke gebaut: der Vergleich muss das melden,
// sonst prüft der Test nur sich selbst. Läuft ohne App, nur mit Python.
// Aufruf: npm run test:handoff (SOMA_PYTHON zeigt auf das Python mit cadquery).
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { checker, cleanup } from './harness.mjs';

const t = checker();
const { check } = t;

const PY = process.env.SOMA_PYTHON || path.join(process.env.LOCALAPPDATA ?? '', 'soma-dev', 'venv', 'Scripts', 'python.exe');
const py = (args) => spawnSync(PY, ['-m', 'soma', ...args], { encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });

const EXAMPLE = path.resolve(import.meta.dirname, '..', '..', 'docs', 'examples', 'draftwright-bracket');

// Zahlen, die bewusst keine Parameter sind: die Schnittstelle (VESA 100) und die Regel (0,5 mm Fase). Sie stehen im
// Modell als Konstante, und die Zeile trägt einen Kommentar, der sagt warum — genau das verlangt der Übergang.
const CONSTANTS = { hole_pitch: 'PITCH', chamfer: 'CHAMFER' };

/**
 * Hält das Messergebnis gegen das JSON. Gibt die Abweichungen zurück, leer heißt einig.
 * Das ist die Prüfung aus §4 des Übergangs, als Funktion — damit sie auch gegen ein absichtlich falsches Modell laufen kann.
 */
function compare(doc, insp, source) {
  const problems = [];
  const params = new Map((insp?.source?.parameters ?? []).map((p) => [p.name, p]));
  for (const dim of doc.dimensions ?? []) {
    const name = dim.id.toUpperCase();
    const found = params.get(name);
    if (found) {
      if (Math.abs(found.value - dim.value) > 1e-9) problems.push(`${dim.id}: param ${found.value} != ${dim.value}`);
      if (found.source !== 'code') problems.push(`${dim.id}: source ${found.source}`);
      continue;
    }
    const constant = CONSTANTS[dim.id];
    if (!constant) { problems.push(`${dim.id}: neither a param nor a declared constant`); continue; }
    const line = source.split('\n').find((l) => new RegExp(`^${constant}\\s*=`).test(l));
    if (!line) problems.push(`${dim.id}: no line ${constant} = ... in model.py`);
    else if (!line.includes('#')) problems.push(`${dim.id}: ${constant} has no comment saying why it is not a param`);
  }
  const want = ['plate_w', 'plate_h', 'plate_t'].map((id) => (doc.dimensions ?? []).find((d) => d.id === id)?.value);
  const size = insp?.bounds?.size ?? [];
  if (want.some((v) => typeof v !== 'number')) problems.push('the JSON has no plate_w/plate_h/plate_t');
  else want.forEach((v, i) => {
    if (Math.abs((size[i] ?? NaN) - v) > 0.01) problems.push(`bounds.size[${'xyz'[i]}] ${size[i]} != ${v}`);
  });
  return problems;
}

/** Die Regel aus §4: ein geschlossener, gültiger Körper ohne Beanstandung. */
const sound = (insp) => insp?.checks?.ok === true && insp?.parts?.length === 1
  && insp.parts[0].topology.solids === 1 && insp.parts[0].valid === true && insp.parts[0].closed === true
  && (insp.checks.issues ?? []).length === 0;

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'soma-handoff-'));
try {
  const project = path.join(dir, 'bracket');
  fs.cpSync(EXAMPLE, project, { recursive: true });
  const doc = JSON.parse(fs.readFileSync(path.join(project, 'inputs', 'draftwright.json'), 'utf8'));
  const source = fs.readFileSync(path.join(project, 'model.py'), 'utf8');

  check('Der Übergang ist als draftwright.handoff/1 geschrieben', doc.schema === 'draftwright.handoff/1' && doc.unit === 'mm',
    `${doc.schema} / ${doc.unit}`);

  const build = py(['build', '--project', project]);
  check('Der Beispielauftrag baut', build.status === 0, (build.status === 0 ? '' : (build.stderr || build.stdout).slice(-200)));

  const insp = py(['inspect', '--json', '--project', project]);
  const ins = insp.status === 0 ? JSON.parse(insp.stdout) : null;
  check('Das Ergebnis lässt sich messen', Boolean(ins), (ins ? '' : (insp.stderr || '').slice(-200)));

  const problems = compare(doc, ins, source);
  check('Jede gemessene Zahl ist ein param() mit dem Wert aus dem JSON, jede andere eine begründete Konstante',
    problems.length === 0, problems.length ? JSON.stringify(problems) : `${(doc.dimensions ?? []).length} Zahlen`);

  const want = ['plate_w', 'plate_h', 'plate_t'].map((id) => doc.dimensions.find((d) => d.id === id).value);
  check('bounds.size ist die Platte, die das JSON beschreibt', JSON.stringify(ins?.bounds?.size) === JSON.stringify(want),
    `${JSON.stringify(ins?.bounds?.size)} gegen ${JSON.stringify(want)}`);

  check('Ein geschlossener, gültiger Körper ohne Beanstandung', sound(ins),
    JSON.stringify(ins ? { ok: ins.checks.ok, issues: ins.checks.issues, topology: ins.parts?.[0]?.topology } : null).slice(0, 200));

  // Das Volumen beweist, dass die Merkmale wirklich gebaut sind: der Quader minus vier Eckenrundungen und vier Löcher.
  // Die Fase ist als einzige nicht in der Erwartung; sie nimmt entlang 466 mm Umriss und vier Lochrändern weniger als
  // 100 mm³ weg. Fehlten die Löcher (821 mm³) oder die Rundungen (330 mm³), läge das Volumen über der Erwartung.
  const [w, h, t2] = want;
  const holeD = doc.dimensions.find((d) => d.id === 'hole_d').value;
  const r = doc.dimensions.find((d) => d.id === 'corner_r').value;
  const expected = w * h * t2 - 4 * (r * r - Math.PI * r * r / 4) * t2 - 4 * Math.PI * (holeD / 2) ** 2 * t2;
  const volume = ins?.parts?.[0]?.volume ?? 0;
  check('Vier Löcher, vier Eckenrundungen und die Fase stecken im Volumen',
    expected - volume > 0.5 && expected - volume < 100,
    `${volume.toFixed(1)} mm³, Erwartung ${expected.toFixed(1)} ohne Fase, Rest ${(expected - volume).toFixed(1)}`);

  // Jedes offene Fragezeichen bekommt genau eine Antwortzeile, sonst wäre es im Chat beantwortet und nicht im Projekt.
  const notes = fs.readFileSync(path.join(project, 'NOTES.md'), 'utf8');
  const answers = notes.split(/^## Open questions, answered$/m)[1] ?? '';
  const bullets = (answers.split(/^## /m)[0].match(/^- /gm) ?? []).length;
  check('NOTES.md beantwortet jede offene Frage', bullets === (doc.open_questions ?? []).length && bullets > 0,
    `${bullets} Antworten für ${(doc.open_questions ?? []).length} Fragen`);

  // Und der Vergleich selbst muss zubeißen: dasselbe Modell mit 4 mm statt 6 mm Dicke.
  const wrong = path.join(dir, 'wrong');
  fs.cpSync(EXAMPLE, wrong, { recursive: true });
  const wrongPy = path.join(wrong, 'model.py');
  const doctored = fs.readFileSync(wrongPy, 'utf8').replace('param(6.0, "Plate thickness"', 'param(4.0, "Plate thickness"');
  fs.writeFileSync(wrongPy, doctored);
  const wrongBuild = py(['build', '--project', wrong]);
  const wrongInsp = py(['inspect', '--json', '--project', wrong]);
  const wrongIns = wrongInsp.status === 0 ? JSON.parse(wrongInsp.stdout) : null;
  const caught = compare(doc, wrongIns, doctored);
  check('Der Vergleich meldet ein Modell, das dem JSON widerspricht',
    wrongBuild.status === 0 && caught.some((p) => p.startsWith('plate_t')) && caught.some((p) => p.startsWith('bounds.size')),
    caught.length ? JSON.stringify(caught.slice(0, 3)) : 'nichts gemeldet');
} finally {
  cleanup(dir);
}

console.log(t.fails ? `\n${t.fails} PRÜFUNGEN FEHLGESCHLAGEN` : '\nALLE PRÜFUNGEN BESTANDEN');
process.exit(t.fails ? 1 : 0);
