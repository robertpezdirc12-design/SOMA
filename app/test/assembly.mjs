// Test für die Baugruppe (docs/examples/bearing-block): ein Gehäuse mit zwei Rillenkugellagern auf einer Welle, die
// Innenringe mit zwei Sprengringen, dazu eine Passfeder. Der Punkt ist nicht, dass die Teile einzeln gültig sind — das
// prüft test:hardware — sondern dass sie zueinander passen. Genau das kann `soma inspect` von sich aus nicht: es misst
// jedes Bauteil für sich. Mit --overlaps misst es die Schnittmenge je Paar, und dieser Test hält die Zahl fest.
// Läuft ohne App, nur mit Python.
// Aufruf: npm run test:assembly (SOMA_PYTHON zeigt auf das Python mit cadquery).
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { checker, cleanup } from './harness.mjs';

const t = checker();
const { check } = t;

const PY = process.env.SOMA_PYTHON || path.join(process.env.LOCALAPPDATA ?? '', 'soma-dev', 'venv', 'Scripts', 'python.exe');
const py = (args) => spawnSync(PY, ['-m', 'soma', ...args], { encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });
const json = (args) => { const r = py(args); return r.status === 0 ? JSON.parse(r.stdout) : null; };

const EXAMPLE = path.resolve(import.meta.dirname, '..', '..', 'docs', 'examples', 'bearing-block');

const BORE = 10;          // 6200
const SEAT = 9;           // Breite des Lagers: so tief sitzt es in seiner Bohrung
const DEPTH = 34;         // Gehäusetiefe
const MID = DEPTH - SEAT; // 25
const OVERHANG = 15;
const STUB = 30;
const SHAFT_LEN = OVERHANG + DEPTH + STUB;

/** Kopie des Beispiels in einen temporären Ordner, optional mit einer Änderung am Quelltext. */
function copy(dir, name, edit) {
  const project = path.join(dir, name);
  fs.cpSync(EXAMPLE, project, { recursive: true });
  if (edit) {
    const file = path.join(project, 'model.py');
    const before = fs.readFileSync(file, 'utf8');
    const after = edit(before);
    if (after === before) throw new Error(`${name}: die Änderung hat nichts getroffen`);
    fs.writeFileSync(file, after);
  }
  return project;
}

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'soma-assembly-'));
try {
  const project = copy(dir, 'block');

  const build = py(['build', '--project', project]);
  check('Die Baugruppe baut', build.status === 0, build.status === 0 ? '' : (build.stderr || build.stdout).slice(-200));

  const doc = json(['inspect', '--overlaps', '--json', '--project', project]);
  check('Die Baugruppe lässt sich messen', Boolean(doc), doc ? '' : 'inspect gab kein JSON');
  if (!doc) throw new Error('ohne Messung läuft der Rest des Tests ins Leere');

  const part = (n) => doc.parts.find((p) => p.name === n);
  const names = doc.parts.map((p) => p.name);
  check('Sieben Teile: Gehäuse, Welle und fünf gekaufte',
    names.length === 7 && doc.totals.solids === 7 && names.every((n) => part(n)?.valid === true),
    names.join(', '));

  // Der eigentliche Punkt: nichts schneidet sich. Ein Presssitz ist im Modell nominal, also null.
  check('Kein Paar schneidet sich', Array.isArray(doc.overlaps) && doc.overlaps.length === 0 && doc.ok === true,
    JSON.stringify(doc.overlaps ?? 'kein Feld') + ` / ok ${doc.ok}`);

  // Ohne --overlaps steht das Feld nicht da: die Voreinstellung bleibt so schnell wie vorher und die Ausgabe gleich.
  const plain = json(['inspect', '--json', '--project', project]);
  check('Ohne --overlaps bleibt das Dokument unverändert', plain && !('overlaps' in plain),
    plain ? Object.keys(plain).join(', ') : 'kein JSON');

  // Das Volumen der Welle beweist, dass beide Nuten und die Passfeder wirklich geschnitten sind: ein voller Zylinder
  // minus zwei Ringnuten (je 6,77 mm³) und eine 20 mm lange Nut (100,2 mm³) ergibt 6091,5 mm³. Fehlte die Passfeder,
  // läge das Volumen um 100 mm³ höher, fehlten die Nuten um 13,5.
  const removed = Math.PI * (BORE / 2) ** 2 * SHAFT_LEN - part('Shaft').volume;
  check('Beide Ringnuten und die Passfeder stecken im Wellenvolumen', removed > 112 && removed < 116,
    `${removed.toFixed(2)} mm³ entfernt, Erwartung 113,8 (Nuten 13,5 + Nut 100,2)`);

  // Jeder Ring liegt in seiner Nut und stößt an sein Lager: A bei 9..10 auf der Innenseite von Lager A, B bei 24..25
  // auf der Innenseite von Lager B. Damit hält A die Welle in der einen Richtung und B in der anderen.
  const z = (n) => [part(n).bounds.min[2], part(n).bounds.max[2]];
  check('Ring A liegt in der Nut bei 9 mm und stößt an Lager A',
    z('Ring A')[0] === SEAT && z('Ring A')[1] === SEAT + 1 && z('Bearing A')[1] === SEAT,
    `Ring ${z('Ring A')}, Lager ${z('Bearing A')}`);
  check('Ring B liegt in der Nut bei 24 mm und stößt an Lager B',
    z('Ring B')[0] === MID - 1 && z('Ring B')[1] === MID && z('Bearing B')[0] === MID,
    `Ring ${z('Ring B')}, Lager ${z('Bearing B')}`);

  // Die Nasen des Rings stehen über den Ringkörper hinaus (DIN zeichnet sie nur). Sie müssen im Mittelloch bleiben,
  // sonst schlüge der Ring ins Gehäuse: Mittelloch 26 mm, also höchstens 13 mm vom Mittelpunkt.
  const reach = Math.max(...['Ring A', 'Ring B'].flatMap((n) => [part(n).bounds.min[1], part(n).bounds.max[1]]));
  check('Die Nasen der Ringe bleiben im Mittelloch (Radius 13)', Math.abs(reach) < 13,
    `Nase bis ${Math.abs(reach).toFixed(2)} mm`);

  // Und die Messung muss zubeißen. Erste Gegenprobe: Ringe im freien Zustand (ohne mounted=True). d3 ist 9,3 mm, die
  // Nut 9,6 — ein freier Ring ist für seine eigene Nut zu klein und steckt 0,15 mm in der Welle.
  const free = copy(dir, 'free-rings', (s) => s.replaceAll(', mounted=True', ''));
  const freeBuild = py(['build', '--project', free]);
  const freeDoc = json(['inspect', '--overlaps', '--json', '--project', free]);
  const freePairs = (freeDoc?.overlaps ?? []).map((o) => [o.a, o.b].sort().join('/')).sort();
  check('Freie Ringe werden als Überschneidung gemeldet',
    freeBuild.status === 0 && freeDoc?.ok === false && freePairs.length === 2
      && freePairs.every((p) => p === ['Ring A', 'Shaft'].sort().join('/') || p === ['Ring B', 'Shaft'].sort().join('/'))
      && (freeDoc.overlaps ?? []).every((o) => o.volume > 3 && o.volume < 6 && o.thickness > 0.1),
    (freeDoc?.overlaps ?? []).map((o) => `${o.a}/${o.b} ${o.volume} mm³ ${o.thickness} mm`).join('; ') || 'nichts gemeldet');

  // Zweite Gegenprobe: die Passfeder ohne direction und angle. Die Welle liegt in Z, ohne die beiden Angaben liegt die
  // Feder quer über der Welle statt in ihrer Nut — und verschwindet teilweise in ihr. Der Span ist flach (die Feder
  // liegt in der Ebene der Oberfläche, also nur die Linse darunter steckt in der Welle), aber 8,9 mm³ sind kein Rauschen.
  const across = copy(dir, 'key-across', (s) => s.replace(', direction="-Y", angle=90', ''));
  const acrossBuild = py(['build', '--project', across]);
  const acrossDoc = json(['inspect', '--overlaps', '--json', '--project', across]);
  const keyPair = (acrossDoc?.overlaps ?? []).find((o) => [o.a, o.b].sort().join('/') === ['Key', 'Shaft'].sort().join('/'));
  check('Eine falsch gedrehte Passfeder wird als Überschneidung gemeldet',
    acrossBuild.status === 0 && acrossDoc?.ok === false && keyPair && keyPair.thickness > 0.3 && keyPair.volume > 5,
    keyPair ? `${keyPair.volume} mm³, ${keyPair.thickness} mm tief` : JSON.stringify(acrossDoc?.overlaps ?? null));

  // Die Stückliste fasst zusammen, was gleich ist: zwei Lager, zwei Ringe, eine Feder.
  const bom = json(['bom', '--json', '--project', project]);
  const bought = bom?.purchased ?? [];
  const count = (needle) => bought.filter((l) => (l.designation ?? '').includes(needle)).reduce((n, l) => n + (l.count ?? 0), 0);
  check('Die Stückliste zählt zwei Lager, zwei Ringe und eine Passfeder',
    count('6200') === 2 && count('DIN 471') === 2 && count('DIN 6885') === 1 && (bom?.manufactured ?? []).length === 2,
    bought.map((l) => `${l.count} x ${l.designation}`).join(', ') + ` / ${(bom?.manufactured ?? []).length} gefertigt`);
} finally {
  cleanup(dir);
}

console.log(t.fails ? `\n${t.fails} PRÜFUNGEN FEHLGESCHLAGEN` : '\nALLE PRÜFUNGEN BESTANDEN');
process.exit(t.fails ? 1 : 0);
