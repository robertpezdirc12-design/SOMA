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

// Ein verschraubtes Blech, absichtlich ohne Passung: die Schraube steckt in einem 6,6-mm-Loch, die Scheibe liegt auf
// dem Blech, die Mutter darüber. Nichts davon darf sich schneiden — die Mutter hat die Nennbohrung, weil SOMA keine
// Gewinde zeichnet.
const JOINT_PLATE_T = 8.0;
const JOINT = `import cadquery as cq
from soma import add_part
from soma.fasteners import Nut, Screw, Washer

PLATE_T = 8.0
plate = cq.Workplane("XY").box(40, 30, PLATE_T, centered=(True, True, False))
plate = plate.faces(">Z").workplane().hole(6.6)                      # Durchgangsloch fuer M6
add_part("Plate", plate)

screw = Screw("ISO 4762", "M6x20", at=(0, 0, 0), direction="+Z")     # Kopf unten, Schaft nach oben durch
washer = Washer("ISO 7089", "M6", at=(0, 0, PLATE_T), direction="-Z")
nut = Nut("ISO 4032", "M6", at=(0, 0, PLATE_T + washer.thickness), direction="-Z")
add_part("Screw", screw)
add_part("Washer", washer)
add_part("Nut", nut)
`;

/** Kopie des Beispiels in einen temporären Ordner, optional mit einer Änderung am Quelltext. */
function copy(dir, name, edit) {
  const project = path.join(dir, name);
  // .soma, output, exports und __pycache__ sind Ergebnisse eines früheren Laufs: sie mitzunehmen machte den Test von
  // dem abhängig, was zufällig im Beispielordner liegt.
  const skip = new Set(['.soma', 'output', 'exports', '__pycache__']);
  fs.cpSync(EXAMPLE, project, { recursive: true, filter: (src) => !skip.has(path.basename(src)) });
  if (edit) {
    const file = path.join(project, 'model.py');
    const before = fs.readFileSync(file, 'utf8');
    const after = edit(before);
    if (after === before) throw new Error(`${name}: die Änderung hat nichts getroffen`);
    fs.writeFileSync(file, after);
  }
  return project;
}

// Was auf dem Blatt steht, gelesen aus der DXF: die Zellen der Stückliste (die Zeile mit "Pos" ist die Kopfzeile,
// alles darunter gehört zur Tabelle) und das Maß "Ø10", dessen Text neben dem Maß steht. So prüft der Test, was auf
// dem Blatt steht, und nicht, was im Quelltext steht.
const SHEET = `
import json, sys, ezdxf
msp = ezdxf.readfile(sys.argv[1]).modelspace()
cells = [e for e in msp if e.dxftype() == "TEXT"]
head = next(e for e in cells if e.dxf.text.strip() == "Pos")
y0, x0 = head.dxf.insert.y, head.dxf.insert.x
rows = {}
for e in cells:
    if e.dxf.insert.x >= x0 - 1 and -41 < e.dxf.insert.y - y0 < 1:
        rows.setdefault(round(e.dxf.insert.y, 2), []).append((e.dxf.insert.x, e.dxf.text))
dim = next(d for d in msp.query("DIMENSION") if d.dxf.text == "Ø10")
lines = [e for e in dim.virtual_entities() if e.dxftype() == "LINE"]
print(json.dumps(dict(
    rows=[[t for _x, t in sorted(v)] for _y, v in sorted(rows.items(), reverse=True)],
    leader=dict(lines=len(lines), reach=round(max(max(e.dxf.start.x, e.dxf.end.x) for e in lines), 2))),
    ensure_ascii=False))
`;

/** Alle Texte eines Blatts, für die Notizen: sie sollen die Zahlen des Modells nennen, nicht eigene. */
const SHAFT_TEXTS = `
import json, sys, ezdxf
msp = ezdxf.readfile(sys.argv[1]).modelspace()
print(json.dumps([e.dxf.text for e in msp if e.dxftype() == "TEXT"], ensure_ascii=False))
`;

/** Was auf dem Blatt steht, gegen das, was `soma bom` sagt: Liste der Abweichungen, leer heißt einig.
 *  Spalten: Pos, Name, Qty, Bezeichnung. Gefertigte Teile stehen mit ihrem Namen, gekaufte mit ihrer Bezeichnung. */
function listDiff(rows, bom) {
  const body = rows.slice(1);            // ohne Kopfzeile
  const cell = (row, i) => (row[i] ?? '').trim();
  const off = [];
  if (!rows.length) return ['keine Tabelle gefunden'];
  if (body.length !== (bom?.totals?.items ?? -1)) off.push(`${body.length} Zeilen statt ${bom.totals.items}`);
  const pos = body.map((r) => cell(r, 0)).join(',');
  if (pos !== body.map((_r, i) => String(i + 1)).join(',')) off.push(`Positionen ${pos}`);
  for (const m of bom?.manufactured ?? []) {
    const r = body.find((row) => cell(row, 1) === m.name);
    if (!r) off.push(`${m.name} fehlt`);
    else if (Number(cell(r, 2)) !== m.count) off.push(`${m.name} ${cell(r, 2)}x statt ${m.count}x`);
  }
  for (const p of bom?.purchased ?? []) {
    const r = body.find((row) => cell(row, 3) === p.designation);
    if (!r) off.push(`${p.designation} fehlt`);
    else if (Number(cell(r, 2)) !== p.count) off.push(`${p.designation} ${cell(r, 2)}x statt ${p.count}x`);
  }
  return off;
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

  // Die Zeichnung: sie muss ohne Warnung bauen, und ihre Stückliste muss sagen, was `soma bom` sagt. Der Test liest die
  // Zellen aus der DXF und vergleicht sie mit der Stückliste — eine Tabelle, die veraltet, fällt damit auf.
  const draw = json(['drawing', 'build', 'assembly', '--json', '--project', project]);
  const sheet = draw?.built?.[0];
  check('Die Zeichnung baut ohne Warnung',
    Boolean(sheet) && (draw.errors ?? []).length === 0 && sheet.warnings.length === 0,
    sheet ? ((sheet.warnings ?? []).map((w) => w.message ?? JSON.stringify(w)).join('; ') || 'keine Warnung')
      : JSON.stringify(draw?.errors ?? 'kein JSON'));
  check('Zwei Ansichten und sechs Maße auf der Baugruppe',
    sheet && sheet.views.length === 2 && sheet.dims.length === 6,
    sheet ? `${sheet.views.length} Ansichten, ${sheet.dims.length} Maße` : 'kein Blatt');

  const dump = spawnSync(PY, ['-c', SHEET, path.join(project, sheet?.dxf ?? '')],
    { encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });
  let page = null;
  try {
    page = JSON.parse(dump.stdout || 'null');
  } catch {
    page = null;
  }
  const rows = page?.rows ?? [];
  const off = listDiff(rows, bom);
  check('Die Stückliste auf dem Blatt stimmt mit soma bom überein', off.length === 0,
    off.join(', ') || rows.slice(1).map((r) => r.join(' ')).join(' | '));

  // Gegenprobe, ohne noch einmal zu bauen: eine Bezeichnung, die nicht mehr zur Stückliste passt, muss auffallen —
  // sonst wäre die Zeile darüber eine Prüfung, die immer besteht.
  const stale = JSON.parse(JSON.stringify(bom));
  stale.purchased.find((p) => p.designation.startsWith('DIN 6885')).designation = 'DIN 6885 3x3x25';
  const caught = listDiff(rows, stale);
  check('Eine veraltete Bezeichnung auf dem Blatt fällt auf',
    caught.some((m) => m.includes('DIN 6885 3x3x25')), caught.join(', ') || 'nichts bemerkt');

  // Der Wellendurchmesser ist 10 mm breit und sein Text 13: er passt nicht zwischen die Pfeile, also steht er
  // daneben — und muss mit einer Hinweislinie an das Maß angebunden sein. Ein Maß hat drei Linien (Maßlinie und zwei
  // Verlängerungen), mit Leader sind es fünf, und die letzte reicht bis unter den Text.
  check('Der Text "Ø10" steht neben dem Maß und hängt an einer Hinweislinie',
    page?.leader?.lines === 5 && page.leader.reach > 145,
    JSON.stringify(page?.leader ?? null));

  // Das zweite Blatt: die Welle. Auf einer Teilzeichnung stehen die Maße, die die Werkstatt braucht — und sie sind aus
  // dem Modell gerechnet, nicht getippt: die Kette 23,95 / 15 / 20 / 8 kommt aus Lagerbreite, Nut und Passfeder. Ein
  // getipptes Maß wäre hier die Stelle, an der die Zeichnung still veraltet.
  const part2 = json(['drawing', 'build', 'shaft', '--json', '--project', project]);
  const shaft = (part2?.built ?? []).find((s) => s.id === 'Shaft');
  check('Die Wellenzeichnung baut ohne Warnung',
    Boolean(shaft) && (part2.errors ?? []).length === 0 && shaft.warnings.length === 0,
    shaft ? ((shaft.warnings ?? []).map((w) => w.message ?? JSON.stringify(w)).join('; ') || 'keine Warnung')
      : JSON.stringify(part2?.errors ?? 'kein JSON'));
  check('Zwei Schnitte und acht Maße auf dem Wellenblatt',
    shaft && shaft.views.length === 2 && shaft.dims.length === 8
      && shaft.views.every((v) => v.kind === 'section'),
    shaft ? `${shaft.views.length} Ansichten, ${shaft.dims.length} Maße` : 'kein Blatt');

  // Die Kette auf dem Blatt, gegen die Maße, aus denen sie gerechnet ist: Gesamtlänge, Überstand, die Lage der ersten
  // Nut (Überstand + Lagerbreite - Spiel), der Abstand der Nuten (Lagerbreite + Tiefe - Spiel - Spiel), die Länge der
  // Passfeder, ihr Abstand zur Stirnfläche — und die beiden Maße, die im Schnitt stehen.
  const val = (v) => shaft?.dims.some((d) => Math.abs(d.value - v) < 1e-9);
  const groove = OVERHANG + SEAT - 0.05;        // 23,95: das Spiel des Sprengrings in seiner Nut ist 0,05 je Seite
  const keyEnd = DEPTH + 12 + 10;               // 56: Mitte der Passfeder + halbe Länge
  check('Die Maße der Welle stimmen mit dem Modell überein',
    val(SHAFT_LEN) && val(OVERHANG) && val(groove) && val(MID - SEAT - 1) && val(20)
      && val(DEPTH + STUB - keyEnd) && val(BORE) && val(3),
    (shaft?.dims ?? []).map((d) => d.label).join(', '));
  check('Der Satz hat zwei Blätter', (part2.set?.sheets ?? 0) === 2 && (part2.built ?? []).length === 2,
    `${part2?.set?.sheets} Blätter, ${(part2?.built ?? []).length} gebaut`);

  // Die Notizen nennen die Nutentiefe der Passfeder — und auch die steht im Modell (`key.shaft_depth`), damit die
  // Zeichnung nicht behauptet, die Nut sei 1,4 tief, während die Welle 1,8 tief gefräst wird.
  const texts = spawnSync(PY, ['-c', SHAFT_TEXTS, path.join(project, shaft?.dxf ?? '')],
    { encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });
  let notes = [];
  try {
    notes = JSON.parse(texts.stdout || '[]');
  } catch {
    notes = [];
  }
  check('Die Notizen des Wellenblatts kommen aus dem Modell',
    notes.some((s) => s.includes('3x3x20') && s.includes('shaft depth 1.8'))
      && notes.some((s) => s.includes('Ø9.6') && s.includes('width 1.1')),
    notes.filter((s) => s.startsWith('  ')).join(' / ') || 'keine Notiz gefunden');

  // Dieselbe Messung an der exportierten Datei: from_file(overlaps=True) ist ein eigener Weg und muss dasselbe sagen.
  // Ein Export, in dem zwei Körper ineinandersitzen, ist genau der Fehler, den man erst im anderen Programm merkt.
  const exp = py(['export', '--assembly', '--format', 'step', '--project', project]);
  const step = path.join(project, 'exports', `${path.basename(project)}.step`);
  const stepDoc = json(['inspect', '--step', step, '--overlaps', '--json']);
  check('Die exportierte STEP-Datei: sieben Körper und ebenfalls kein Paar',
    exp.status === 0 && fs.existsSync(step) && stepDoc?.totals?.solids === 7
    && Array.isArray(stepDoc.overlaps) && stepDoc.overlaps.length === 0 && stepDoc.ok === true,
    `${stepDoc?.totals?.solids} Körper, ${JSON.stringify(stepDoc?.overlaps)}`);

  // Und die Kehrseite: eine Schraube in ihrer Mutter ist KEINE Überschneidung. SOMA zeichnet keine Gewinde, die
  // Mutter hat also die Nennbohrung und die Schraube geht mit null hindurch. Fiele diese Zusage, wäre jedes
  // verschraubte Modell voller Meldungen — deshalb steht sie hier als Prüfung.
  const joint = path.join(dir, 'joint');
  fs.mkdirSync(joint);
  fs.writeFileSync(path.join(joint, 'model.py'), JOINT);
  const jointBuild = py(['build', '--project', joint]);
  const jointDoc = json(['inspect', '--overlaps', '--json', '--project', joint]);
  // Damit die Prüfung nicht bloß deshalb besteht, weil die Teile zufällig nebeneinander liegen: der Stapel muss
  // wirklich ein Stapel sein — Scheibe auf dem Blech, Mutter auf der Scheibe, Schaft durch beide hindurch.
  const jp = (n) => jointDoc?.parts?.find((p) => p.name === n);
  const stack = jp('Washer')?.bounds.min[2] === JOINT_PLATE_T && jp('Nut')?.bounds.min[2] === jp('Washer')?.bounds.max[2]
    && (jp('Screw')?.bounds.max[2] ?? 0) > (jp('Nut')?.bounds.max[2] ?? 0);
  check('Schraube durch Scheibe und Mutter: vier Teile im Stapel, kein Paar',
    jointBuild.status === 0 && jointDoc?.totals?.parts === 4 && stack
    && (jointDoc?.overlaps ?? []).length === 0 && jointDoc.ok === true,
    stack ? `${(jointDoc?.overlaps ?? []).length} Paare` : `Stapel: ${JSON.stringify(jointDoc?.parts?.map((p) => [p.name, p.bounds?.min[2], p.bounds?.max[2]]))}`);
} finally {
  cleanup(dir);
}

console.log(t.fails ? `\n${t.fails} PRÜFUNGEN FEHLGESCHLAGEN` : '\nALLE PRÜFUNGEN BESTANDEN');
process.exit(t.fails ? 1 : 0);
