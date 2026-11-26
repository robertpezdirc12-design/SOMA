// Test für die Tabellen selbst: jede Zeile jeder Zukaufteil-Tabelle wird gebaut, nicht nur die Zeilen, die zufällig in einem
// anderen Test vorkommen. Das findet die Fehlerklasse, zu der der Tippfehler "68" in nominal_screw_lengths.csv gehörte: eine
// Zeile, aus der die Geometrie keinen gültigen Körper macht oder deren Zahlen sich widersprechen. Dazu die Listen, die niemand
// prüft, solange sie niemand benutzt: standards(), HINTS und ALIASES. Läuft ohne App, nur mit Python.
// Aufruf: npm run test:tables (SOMA_PYTHON zeigt auf das Python mit cadquery).
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { checker } from './harness.mjs';

const t = checker();
const { check } = t;

const PY = process.env.SOMA_PYTHON || path.join(process.env.LOCALAPPDATA ?? '', 'soma-dev', 'venv', 'Scripts', 'python.exe');

// Die drei Zeilen der Tabelle, die sich selbst widersprechen: der genannte Bohrer ist größer als der Aussendurchmesser des
// Einsatzes, ein solches Loch hält nicht. Sie werden abgelehnt, nicht gebaut — das ist die richtige Antwort, und die Meldung
// sagt warum. Steht eine davon eines Tages richtig in der Tabelle, schlägt diese Prüfung an und die Liste gehört gekürzt.
const KNOWN_BAD = [
  ['CNCKitchen', 'M1.6x1.6'],   // "#39" = 2,53 mm bei 2,5 mm Aussendurchmesser
  ['CNCKitchen', 'M10x12.7'],   // "M14" bei 12,6 mm
  ['ruthex', 'M10x12.7'],       // "M14" bei 12,6 mm
];

const SWEEP = String.raw`
import json
import math
import cadquery as cq
from soma.fasteners import (Screw, Nut, Washer, HeatSetInsert, Bearing, RetainingRing, ShaftKey, ORing,
                            SCREWS, NUTS, WASHERS, BEARINGS, RETAINING_RINGS, SHAFT_KEYS, O_RINGS, INSERT_BRANDS,
                            ALIASES, HINTS, standards, _table, _inserts, _KEY)

COS30 = math.cos(math.radians(30))
built = {}
fails = []
skipped = {}


def out(payload):
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def skip(why):
    skipped[why] = skipped.get(why, 0) + 1


def probe(family, standard, size, make, expect):
    """Ein Teil bauen, dann seine Zahlen gegen den Körper prüfen, den er erzeugt hat."""
    try:
        part = make()
    except ValueError as exc:
        text = str(exc)
        if "is not in the table" in text or "cannot read the size" in text:
            skip(family)  # Zeile gehoert zu einer anderen Norm derselben Tabelle, oder ist Zoll
            return
        fails.append([family, standard, size, f"{type(exc).__name__}: {text}"[:400]])
        return
    except Exception as exc:  # noqa: BLE001 - genau dafuer ist der Durchlauf da
        fails.append([family, standard, size, f"{type(exc).__name__}: {exc}"[:400]])
        return
    built[family] = built.get(family, 0) + 1
    try:
        shape = part.shape
        box = shape.BoundingBox()
        volume = shape.Volume()
        why = expect(part, box, volume)
        if len(shape.Solids()) != 1:
            why = f"{len(shape.Solids())} Koerper"
        elif not shape.isValid():
            why = "ungueltig"
        elif volume <= 0:
            why = "Volumen 0"
    except Exception as exc:  # noqa: BLE001
        why = f"{type(exc).__name__}: {exc}"[:400]
    if why:
        fails.append([family, standard, size, why])


def metric(key):
    """Zeilenschluessel "M3-0.5" -> 3.0; Zoll-Zeilen ("#8-32", "1/4-20") -> None."""
    m = _KEY.match(key)
    return float(m.group(1)) if m else None


def plain(key):
    return "M" + f"{metric(key):g}"


# --- Schrauben: jede Groesse mit einer Laenge aus der eigenen Laengenreihe --------------------------------------------------
for key, spec in SCREWS.items():
    for size, _row in _table(spec["table"]):
        if metric(size) is None:
            skip("Schraube (Zoll)")
            continue
        name = plain(size)
        try:
            from soma.fasteners import lengths
            series = lengths(key, name)
        except ValueError as exc:
            if "is not in the table" in str(exc):
                skip("Schraube")
                continue
            fails.append(["Screw", spec["name"], name, f"lengths: {exc}"[:400]])
            continue
        if not series:
            fails.append(["Screw", spec["name"], name, "leere Laengenreihe"])
            continue
        if series != sorted(series):
            fails.append(["Screw", spec["name"], name, f"Laengen nicht sortiert: {series}"])
        if len(set(series)) != len(series):
            fails.append(["Screw", spec["name"], name, f"Laengen doppelt: {series}"])
        design = f"{name}x{f'{series[len(series) // 2]:g}'}"

        def expect_screw(part, box, volume):
            if part.d <= 0:
                return "d <= 0"
            if part.head != "set" and part.head_diameter <= part.d:
                return f"Kopf {part.head_diameter:.2f} <= Schaft {part.d}"
            if part.length <= 0:
                return "Laenge <= 0"
            if part.key is not None and part.key <= 0:
                return f"Schluesselweite {part.key} <= 0"
            return ""

        probe("Screw", spec["name"], design, lambda design=design, key=key: Screw(key, design, at=(0, 0, 0)),
              expect_screw)


# --- Muttern --------------------------------------------------------------------------------------------------------------
for key, spec in NUTS.items():
    for size, _row in _table(spec["table"]):
        if metric(size) is None:
            skip("Mutter (Zoll)")
            continue
        name = plain(size)

        def expect_nut(part, box, volume):
            if part.height <= 0:
                return "Hoehe <= 0"
            if part.key <= part.d:
                return f"Schluesselweite {part.key:.2f} <= d {part.d}"
            if part.overall_height < part.height:
                return "overall_height < height"
            return ""

        probe("Nut", spec["name"], name, lambda key=key, name=name: Nut(key, name, at=(0, 0, 0)), expect_nut)


# --- Scheiben -------------------------------------------------------------------------------------------------------------
for key, spec in WASHERS.items():
    for size, _row in _table(spec["table"]):
        if metric(size) is None:
            skip("Scheibe (Zoll)")
            continue
        name = plain(size)

        def expect_washer(part, box, volume):
            d1, d2, h = part.dims["d1"], part.dims["d2"], part.dims["h"]
            if d2 <= d1:
                return f"d2 {d2} <= d1 {d1}"
            if h <= 0:
                return "h <= 0"
            if abs(box.zlen - h) > 0.02:
                return f"zlen {box.zlen:.3f} != h {h}"
            if box.xlen > d2 + 0.02:
                return f"xlen {box.xlen:.3f} > d2 {d2}"
            return ""

        probe("Washer", spec["name"], name, lambda key=key, name=name: Washer(key, name, at=(0, 0, 0)), expect_washer)


# --- Sprengringe ----------------------------------------------------------------------------------------------------------
for key, spec in RETAINING_RINGS.items():
    for size, _row in _table(spec["table"]):
        def expect_ring(part, box, volume):
            if part.d <= 0 or part.thickness <= 0:
                return "d oder Dicke <= 0"
            return ""

        probe("RetainingRing", spec["name"], size,
              lambda key=key, size=size: RetainingRing(key, size, at=(0, 0, 0)), expect_ring)


# --- Passfedern -----------------------------------------------------------------------------------------------------------
for key, spec in SHAFT_KEYS.items():
    for size, _row in _table(spec["table"]):
        def expect_key(part, box, volume):
            if part.width <= 0 or part.height <= 0:
                return "Breite oder Hoehe <= 0"
            if abs(box.xlen - 20) > 0.02:
                return f"xlen {box.xlen:.3f} != Laenge 20"
            return ""

        probe("ShaftKey", spec["name"], size, lambda key=key, size=size: ShaftKey(key, size, 20, at=(0, 0, 0)),
              expect_key)


# --- O-Ringe: alle 349 Groessen, nicht nur 019 -----------------------------------------------------------------------------
for key, spec in O_RINGS.items():
    for size, _row in _table(spec["table"]):
        if not size.lstrip("-").isdigit():
            skip("O-Ring (Kopfzeile)")
            continue

        def expect_oring(part, box, volume):
            if part.inner_diameter <= 0 or part.width <= 0:
                return "Innendurchmesser oder Schnur <= 0"
            want = part.inner_diameter + 2 * part.width
            if abs(box.xlen - want) > 0.02:
                return f"od {box.xlen:.3f} != {want:.3f}"
            if abs(box.zlen - 2 * part.minor_radius) > 0.02:
                return f"zlen {box.zlen:.3f} != Schnur {2 * part.minor_radius:.3f}"
            return ""

        probe("ORing", spec["name"], size, lambda size=size: ORing(size, at=(0, 0, 0)), expect_oring)


# --- Waelzlager -----------------------------------------------------------------------------------------------------------
for key, spec in BEARINGS.items():
    for _key, row in _table(spec["table"]):
        des = row.get("SKT:Designation", "").strip().lstrip("*").strip()  # "* 625" ist eine Fussnote der Tabelle
        if not des:
            skip("Lager (ohne Bezeichnung)")
            continue

        def expect_bearing(part, box, volume):
            if part.bore <= 0 or part.diameter <= part.bore:
                return "Bohrung oder Aussendurchmesser falsch"
            if abs(box.xlen - part.diameter) > 0.02:
                return f"xlen {box.xlen:.3f} != D {part.diameter}"
            if abs(box.zlen - part.width) > 0.02:
                return f"zlen {box.zlen:.3f} != B {part.width}"
            return ""

        probe("Bearing", spec["name"], des, lambda des=des: Bearing(des, at=(0, 0, 0)), expect_bearing)


# --- Gewindeeinsaetze: je Marke jede Zeile --------------------------------------------------------------------------------
for brand in sorted(set(INSERT_BRANDS.values())):
    for row in _inserts(brand):
        d, length, variant, dims = row[0], row[3]["m"], row[2], row[3]
        des = f"M{d:g}x{length:g}"

        def make_insert(brand=brand, des=des, variant=variant):
            try:
                return HeatSetInsert(des, brand=brand, at=(0, 0, 0))
            except ValueError as exc:
                if "ambiguous" not in str(exc):
                    raise
                return HeatSetInsert(des, brand=brand, variant=variant, at=(0, 0, 0))

        def expect_insert(part, box, volume):
            if part.diameter <= part.d:
                return f"Aussendurchmesser {part.diameter} <= Gewinde {part.d}"
            if not part.d < part.hole_diameter < part.diameter:
                return "Loch nicht zwischen Gewinde und Aussendurchmesser"
            if abs(box.zlen - part.length) > 0.02:
                return f"zlen {box.zlen:.3f} != Laenge {part.length}"
            return ""

        probe("HeatSetInsert", brand, f"{des} {variant}", make_insert, expect_insert)


# --- Die Listen, die niemand prueft, solange sie niemand benutzt -----------------------------------------------------------
groups = {"screws": SCREWS, "nuts": NUTS, "washers": WASHERS, "bearings": BEARINGS,
          "retaining_rings": RETAINING_RINGS, "shaft_keys": SHAFT_KEYS, "o_rings": O_RINGS}
table = standards()
missing = {g: sorted({v["name"] for v in reg.values()} - set(table.get(g, {}))) for g, reg in groups.items()}
out(["standards", not any(missing.values()), {g: m for g, m in missing.items() if m} or len(table)])

every_key = set().union(*[set(reg) for reg in groups.values()])
real_names = {v["name"] for reg in groups.values() for v in reg.values()}

# Ein Hinweis ist tot, wenn der Name in *jeder* Klasse aufgeloest wird: dann meldet ihn keine mehr. In einer einzelnen
# Klasse zu fehlen genuegt dagegen — "DIN 1665" ist als Mutter vorhanden und als Schraube nicht, der Hinweis also lebendig.
hints_dead = [k for k in HINTS if all(k in reg for reg in groups.values())]
hints_empty = [k for k, v in HINTS.items() if not any(n in v for n in real_names)]
out(["hints", not hints_dead and not hints_empty, {"dead": hints_dead, "zielt ins Leere": hints_empty} or len(HINTS)])

alias_dead = sorted({v for v in ALIASES.values() if v not in every_key})
out(["aliases", not alias_dead, alias_dead or len(ALIASES)])

out(["built", built])
out(["skipped", skipped])
out(["fails", fails])
`;

const lib = spawnSync(PY, ['-c', SWEEP], {
  encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' }, timeout: 15 * 60 * 1000,
});
const lines = (lib.stdout ?? '').split('\n').filter(Boolean).map((l) => {
  try { return JSON.parse(l); } catch { return null; }
}).filter(Boolean);
const get = (name) => lines.find((l) => l[0] === name);
const detail = (payload) => JSON.stringify(payload).slice(0, 200);

if (lib.status !== 0 && !get('fails')) {
  console.log(lib.stdout ?? '');
  console.log(lib.stderr ?? '');
  check('Der Durchlauf über die Tabellen läuft durch', false, `Exit ${lib.status}: ${(lib.stderr ?? '').split('\n').slice(-3).join(' ')}`);
  process.exit(1);
}

const built = get('built')?.[1] ?? {};
const fails = get('fails')?.[1] ?? [];
const skipped = get('skipped')?.[1] ?? {};

// Mindestzahlen: eine Tabelle, die plötzlich keine Zeile mehr liefert, fällt sonst nicht auf, weil "keine Fehler" auch
// "nichts geprüft" heißen kann. Die Zahlen sind der Stand vom Durchlauf, nicht das Ziel.
const MINIMUM = { Screw: 200, Nut: 100, Washer: 100, RetainingRing: 170, ShaftKey: 25, ORing: 340, Bearing: 50, HeatSetInsert: 140 };

for (const [family, minimum] of Object.entries(MINIMUM)) {
  check(`${family}: jede Zeile der Tabellen wird gebaut`, (built[family] ?? 0) >= minimum,
    `${built[family] ?? 0} gebaut, erwartet mindestens ${minimum}`);
}

const knownBad = fails.filter(([, std, size]) => KNOWN_BAD.some(([b, s]) => b === std && size.startsWith(s)));
const unexpected = fails.filter((f) => !knownBad.includes(f));
check('Jede Zeile ergibt genau einen gültigen Körper mit den Maßen der Tabelle', unexpected.length === 0,
  unexpected.length ? JSON.stringify(unexpected.slice(0, 4)) : `${Object.values(built).reduce((a, b) => a + b, 0)} Teile`);

check('Die drei Zeilen, die sich selbst widersprechen, werden abgelehnt statt gebaut',
  knownBad.length === KNOWN_BAD.length && knownBad.every((f) => /contradicts itself/.test(f[3])),
  knownBad.length ? knownBad.map((f) => `${f[1]} ${f[2]}`).join(', ') : 'keine mehr — dann gehört KNOWN_BAD gekürzt');

const standardsCheck = get('standards');
check('standards() nennt jede Norm, die eine Klasse kennt', standardsCheck?.[1] === true, detail(standardsCheck?.[2] ?? null));

const hintsCheck = get('hints');
check('Jeder Hinweis zeigt auf eine Norm, die es gibt, und keiner auf einen Namen, den es gibt',
  hintsCheck?.[1] === true, detail(hintsCheck?.[2] ?? null));

const aliasCheck = get('aliases');
check('Jeder Alias löst auf eine vorhandene Norm auf', aliasCheck?.[1] === true, detail(aliasCheck?.[2] ?? null));

const total = Object.values(built).reduce((a, b) => a + b, 0);
console.log(`\n${total} Teile gebaut, ${fails.length} abgelehnt (davon ${knownBad.length} bekannt), `
  + `übersprungen: ${Object.entries(skipped).map(([k, v]) => `${k} ${v}`).join(', ')}`);
console.log(t.fails ? `\n${t.fails} PRÜFUNGEN FEHLGESCHLAGEN` : '\nALLE PRÜFUNGEN BESTANDEN');
process.exit(t.fails ? 1 : 0);
