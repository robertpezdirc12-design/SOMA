"""Measured facts about a model or a CAD file, as one JSON document with a stable schema (`soma inspect`).

Why this exists: a picture shows that a model *looks* right, not that it *is* right. The schema below is the
contract that lets an agent, a test or a CI job answer "did the geometry survive this change?" without opening the
viewer and without parsing human-readable output. It is versioned (`schema`), additive changes bump the minor part,
renaming or removing a field bumps the major part.

    soma inspect                      the current model (model.py), per part and in total
    soma inspect --step out.step      a STEP or BREP file, one entry per solid
    soma inspect --json               the document on stdout, nothing else
    soma inspect --overlaps           also measure which parts cut into each other

The document never contains paths that are not relative to the project, and never a timestamp: two runs on the
same geometry produce byte-identical output, so it can be diffed in a regression test.

Cost: about the same as `soma export` (the model has to run) plus a few milliseconds per part for volume, area and
the topology counts. `isValid()` on a large freeform part is the slowest single call and is skipped with --fast.
`--overlaps` adds a boolean intersection per candidate pair, which is why it is not on by default: a bounding box
test throws away most pairs, but a model with a hundred overlapping boxes is still a hundred intersections.
"""
import json
import math
from pathlib import Path

SCHEMA = "soma.inspect/1"
UNITS = "mm"
FORMATS = (".step", ".stp", ".brep")

# Ab hier ist eine Schnittmenge kein Rechenrauschen an einer Beruehrflaeche mehr. Dieselben Schwellen wie in
# soma.anim (animrun.VOL_MIN und die Eindringtiefe): Volumen allein reicht nicht, ein flacher Span entlang einer
# Auflageflaeche hat viel Volumen und keine Tiefe, eine Nadelspitze umgekehrt.
OVERLAP_VOLUME = 1e-3    # mm3
OVERLAP_DEPTH = 0.01     # mm


class InspectError(Exception):
    """A problem the caller can fix: no model, no such file, a part that does not build."""


def _r(x, digits=6):
    """Zahl fuer JSON: gerundet, ohne -0.0, ohne nan/inf (die sind in JSON nicht darstellbar)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    v = round(v, digits)
    return 0.0 if v == 0 else v


def _vec(v):
    return [_r(v.x), _r(v.y), _r(v.z)]


def _box(shape):
    """Bounding box als min/max/size/center. Leere Formen (nur Referenzen ohne Geometrie) geben null."""
    try:
        bb = shape.BoundingBox()
    except Exception:  # keine Geometrie: BoundingBox wirft oder liefert eine leere Box
        return None
    size = [_r(bb.xlen), _r(bb.ylen), _r(bb.zlen)]
    if size == [0.0, 0.0, 0.0] and not math.isfinite(bb.xmin):
        return None
    return dict(min=[_r(bb.xmin), _r(bb.ymin), _r(bb.zmin)],
                max=[_r(bb.xmax), _r(bb.ymax), _r(bb.zmax)],
                size=size,
                center=[_r(bb.center.x), _r(bb.center.y), _r(bb.center.z)])


def _union_box(boxes):
    """Eine Box um alle: fuer die Gesamtangaben des Modells."""
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    lo = [min(b["min"][i] for b in boxes) for i in range(3)]
    hi = [max(b["max"][i] for b in boxes) for i in range(3)]
    return dict(min=lo, max=hi,
                size=[_r(hi[i] - lo[i]) for i in range(3)],
                center=[_r((hi[i] + lo[i]) / 2) for i in range(3)])


def _topology(shape):
    """Zaehlung der Topologie. Solid-Anzahl ist die wichtigste Zahl: 0 heisst "keine geschlossene Geometrie",
    mehr als 1 in einem Bauteil heisst meist "zwei Koerper, die jemand trennen wollte"."""
    try:
        return dict(solids=len(shape.Solids()), shells=len(shape.Shells()), faces=len(shape.Faces()),
                    edges=len(shape.Edges()), vertices=len(shape.Vertices()))
    except Exception:
        return dict(solids=0, shells=0, faces=0, edges=0, vertices=0)


def _measure(shape, fast=False):
    """Volumen, Flaeche, Schwerpunkt, Gueltigkeit einer Form. Fehler einzelner Werte machen die Anfrage nicht kaputt.

    `closed` wird an den Shells gemessen, nicht an der Form: `cq.Shape.Closed()` liefert bei einem Solid `False`,
    weil es BRep_Tool.IsClosed auf die Form selbst anwendet. Eine geschlossene Shell ist die Aussage, die zaehlt —
    nur aus ihr entsteht ein Koerper, den ein Slicer als Volumen versteht.
    """
    out = dict(topology=_topology(shape))
    solids = out["topology"]["solids"]
    try:
        # Ohne Solid ist Volume() bedeutungslos (eine Flaeche liefert in OCCT irgendeine Zahl)
        out["volume"] = _r(shape.Volume(), 4) if solids else None
    except Exception:
        out["volume"] = None
    try:
        out["area"] = _r(shape.Area(), 4)
    except Exception:
        out["area"] = None
    try:
        out["center_of_mass"] = _vec(shape.Center()) if solids else None
    except Exception:
        out["center_of_mass"] = None
    if fast:
        out["valid"] = None
        out["closed"] = None
    else:
        try:
            out["valid"] = bool(shape.isValid())
        except Exception:
            out["valid"] = None
        try:
            from OCP.BRep import BRep_Tool
            shells = shape.Shells()
            out["closed"] = all(BRep_Tool.IsClosed_s(s.wrapped) for s in shells) if shells else None
        except Exception:
            out["closed"] = None
    return out


def _part(name, shape, role="part", group=(), step_name=None, fastener=None, fast=False, **extra):
    """Ein Eintrag der Bauteilliste. Dieselbe Form fuer Modell und Datei, damit ein Vergleich moeglich ist."""
    entry = dict(name=name, step_name=step_name or name, role=role, group=list(group or ()),
                 bounds=_box(shape))
    entry.update(_measure(shape, fast))
    if fastener is not None:
        designation = getattr(fastener, "designation", None)
        if designation:
            entry["designation"] = str(designation)
    entry.update({k: v for k, v in extra.items() if v is not None})
    return entry


def _checks(parts, fast=False, overlaps=None):
    """Was an der Geometrie messbar falsch ist. `ok` ist nur bei Fehlern falsch, Warnungen sind Hinweise.

    Die Pruefungen sind bewusst billig und deterministisch: keine Interferenz zwischen Bauteilen, solange der
    Aufrufer sie nicht mit `overlaps` misst (das kostet einen Schnitt pro Paar), kein Vergleich gegen eine
    Erwartung (das macht der Aufrufer).
    """
    issues = []

    def add(level, code, part, message):
        issues.append(dict(level=level, code=code, part=part, message=message))

    for p in parts:
        t = p["topology"]
        if p.get("valid") is False:
            add("error", "invalid_shape", p["name"],
                "The shape is not valid (OCCT BRepCheck). A cut or a fillet left a broken face or edge.")
        if t["solids"] == 0:
            # Ein Referenzteil ohne Koerper ist zulaessig (eine Flaeche, an der gemessen wird) und wird nicht
            # exportiert. Ein eigenes Bauteil ohne Koerper ist dagegen fast immer ein Fehler.
            add("warning" if p["role"] == "reference" else "error", "no_solid", p["name"],
                "No closed solid. The part is an open shell or a bare face: it has no volume and no mesh a slicer accepts.")
        if p.get("volume") is not None and p["volume"] <= 0 and t["solids"] > 0:
            add("error", "zero_volume", p["name"], "Volume is 0 although the part has a solid.")
        if t["solids"] > 1:
            add("warning", "multiple_bodies", p["name"],
                f"{t['solids']} separate solids in one part. Intentional, or two bodies that should be two parts?")
        if p.get("closed") is False:
            add("warning", "open_shell", p["name"],
                "The shell is not closed. Boolean operations on it are unreliable, exports may be empty.")
        if p["bounds"] is None:
            add("warning", "no_geometry", p["name"], "The part carries no geometry (a reference without a body?).")

    # Zwei Bauteile mit genau derselben Box sind fast immer eine Kopie, die niemand wollte
    seen = {}
    for p in parts:
        b = p["bounds"]
        if not b:
            continue
        key = (tuple(b["min"]), tuple(b["max"]))
        if key in seen:
            add("warning", "duplicate_bounds", p["name"],
                f"Same bounding box as {seen[key]!r}. A duplicate, or a part placed twice?")
        else:
            seen[key] = p["name"]

    # Nur wenn der Aufrufer danach gefragt hat (--overlaps): eine Ueberschneidung ist ein Fehler, kein Hinweis.
    # Zwei Koerper koennen nicht am selben Ort sein: entweder sitzt ein Teil falsch oder die Tasche fehlt, in die
    # es hineinragt. Ein Presssitz ist im Modell nominal, also null Ueberschneidung.
    for o in overlaps or ():
        where = f" at {_fmt3(o['at'])}" if o.get("at") else ""
        add("error", "overlap", o["a"],
            f"cuts {o['thickness']} mm deep into {o['b']!r}{where}, {o['volume']} mm³. Move the part or cut the "
            "pocket it is meant to sink into")

    errors = [i for i in issues if i["level"] == "error"]
    return dict(ok=not errors, issues=issues)


def _overlaps(items):
    """Paare, deren Koerper sich durchdringen: [dict(a, b, volume, thickness, at)], nach Namen sortiert.

    `items` ist [(Name, Form)]. Die Boxpruefung wirft zuerst alles weg, was sich nicht beruehren kann; erst dann
    schneidet OCCT. Gemeldet wird nur, was zugleich Volumen und Tiefe hat (OVERLAP_VOLUME, OVERLAP_DEPTH): zwei
    Bauteile, die sich in einer Flaeche beruehren, haben eine Schnittmenge von ein paar Mikrometern Kubik, und
    die ist Rechenrauschen, kein Fehler. Die Dicke 2 V / A macht daraus eine Zahl, die man mit einem Spalt
    vergleichen kann. `at` ist der Schwerpunkt der Schnittmenge: das ist die Stelle, die man im Viewer sucht.
    """
    boxes = []
    for name, shape in items:
        try:
            b = shape.BoundingBox()
        except Exception:
            continue
        boxes.append((name, shape, (b.xmin, b.ymin, b.zmin), (b.xmax, b.ymax, b.zmax)))
    found = []
    for i in range(len(boxes)):
        na, sa, loa, hia = boxes[i]
        for j in range(i + 1, len(boxes)):
            nb, sb, lob, hib = boxes[j]
            if any(loa[k] > hib[k] or lob[k] > hia[k] for k in range(3)):
                continue
            try:
                common = sa.intersect(sb)
                volume = common.Volume()
                area = common.Area()
            except Exception:
                continue  # zwei Koerper, die OCCT nicht schneiden kann: das ist ein Fall fuer isValid, nicht hier
            if volume <= OVERLAP_VOLUME:
                continue
            thickness = 2 * volume / area if area > 1e-9 else 0.0
            if thickness <= OVERLAP_DEPTH:
                continue
            try:
                at = _vec(common.Center())
            except Exception:
                at = None
            found.append(dict(a=na, b=nb, volume=_r(volume, 4), thickness=_r(thickness, 4), at=at))
    found.sort(key=lambda o: (o["a"], o["b"]))
    return found


def _totals(parts):
    """Summen und Grenzen des ganzen Modells. Volumen ist die Summe der Bauteile: bei ueberlappenden Teilen zaehlt
    der Ueberschneidungsbereich doppelt, deshalb steht das im Feld `note`."""
    volumes = [p["volume"] for p in parts if p.get("volume") is not None]
    areas = [p["area"] for p in parts if p.get("area") is not None]
    t = dict(parts=len(parts),
             solids=sum(p["topology"]["solids"] for p in parts),
             faces=sum(p["topology"]["faces"] for p in parts),
             edges=sum(p["topology"]["edges"] for p in parts),
             volume=_r(sum(volumes), 4) if volumes else None,
             area=_r(sum(areas), 4) if areas else None)
    if len(parts) > 1:
        t["note"] = "volume and area are the sum of the parts; overlapping parts count twice"
    return t


def _document(source, parts, fast=False, density=None, items=None):
    """Das Dokument. Reihenfolge der Schluessel ist fest: so ist die Ausgabe zwischen zwei Laeufen vergleichbar.

    `items` ist [(Name, Form)] und nur gesetzt, wenn der Aufrufer die Ueberschneidungen messen will.
    """
    from . import __version__
    doc = dict(schema=SCHEMA, soma=__version__, units=UNITS, source=source,
               bounds=_union_box([p["bounds"] for p in parts]), totals=_totals(parts))
    if density is not None:
        total = doc["totals"]["volume"]
        doc["totals"]["mass_g"] = _r(total * density / 1000.0, 4) if total is not None else None
        doc["totals"]["density_g_cm3"] = density
    doc["parts"] = parts
    if items is not None:
        doc["overlaps"] = _overlaps(items)
    doc["checks"] = _checks(parts, fast, doc.get("overlaps"))
    doc["ok"] = doc["checks"]["ok"]
    return doc


# --- Modell -------------------------------------------------------------------------------------------------------------

def from_model(project, entry=None, only=None, fast=False, density=None, overlaps=False):
    """Das Modell ausfuehren und messen. Aendert nichts im Projekt: `run_model` schreibt keine Dateien."""
    from . import build, params
    root = Path(project).resolve()
    try:
        built = build.run_model(root, entry)
    except build.BuildError as e:
        raise InspectError(e.message if getattr(e, "message", None) else str(e)) from e
    if only:
        wanted = {n.strip() for n in only if n.strip()}
        unknown = wanted - {p["name"] for p in built}
        if unknown:
            raise InspectError("No such part: " + ", ".join(sorted(repr(u) for u in unknown))
                               + ". Registered: " + ", ".join(repr(p["name"]) for p in built))
        built = [p for p in built if p["name"] in wanted]
    parts = [_part(p["name"], p["shape"], role=p["role"], group=p.get("group", ()),
                   step_name=p.get("step_name"), fastener=p.get("fastener"), fast=fast) for p in built]
    source = dict(kind="model", project=root.name,
                  entry=str(entry or build.read_project_json(root).get("entry") or build.DEFAULT_ENTRY))
    # Referenzteile sind mitgebracht (eine Flaeche zum Messen, ein Gehaeuse aus einer anderen Baugruppe): dass sie
    # sich mit dem Modell schneiden, ist gewollt und keine Kollision.
    items = [(p["name"], p["shape"]) for p in built if p.get("role") != "reference"] if overlaps else None
    doc = _document(source, parts, fast, density, items)
    doc["source"]["parameters"] = [dict(name=s["name"], value=s.get("value"), source=s.get("source"),
                                        unit=s.get("unit"), group=s.get("group"))
                                   for s in params.PARAMS]
    return doc


# --- Datei --------------------------------------------------------------------------------------------------------------

def _step_solids(path):
    """Alle Koerper einer STEP-Datei als (Name, Form).

    Namen kommen aus der Baugruppe, soweit sie zuzuordnen sind: ein Knoten mit einem Solid gibt seinen Namen, ein
    Knoten mit mehreren Koerpern im Verbund nummeriert sie durch. Knoten ohne Solid (eine Referenzflaeche, eine
    leere Unterbaugruppe) fallen weg. Passt die Zahl der benannten Koerper nicht zu der Zahl im Verbund, sind die
    Namen geraten und werden verworfen — lieber "Solid 3" als ein falscher Name.
    """
    import cadquery as cq
    from . import stepimport
    items = []
    try:
        asm = stepimport.read_assembly(path)
    except Exception:
        asm = None
    if asm is not None:
        def walk(node):
            obj = getattr(node, "obj", None)
            if obj is not None:
                try:
                    solids = obj.Solids()
                except Exception:
                    solids = []
                name = str(getattr(node, "name", "") or "")
                for i, s in enumerate(solids):
                    items.append((name if i == 0 else f"{name} {i + 1}", s))
            for child in getattr(node, "children", []):
                walk(child)
        try:
            walk(asm)
            compound = asm.toCompound()
        except Exception:
            items, compound = [], None
    else:
        compound = None
    if compound is None:
        compound = cq.Compound.makeCompound(cq.importers.importStep(str(path)).vals())
        items = []
    total = len(compound.Solids())
    if not total:
        raise InspectError(f"{path.name} contains no solid. A STEP file without a closed body cannot be measured "
                           "and cannot be printed.")
    if len(items) != total:
        items = [(f"Solid {i + 1}", s) for i, s in enumerate(compound.Solids())]
    return [(n or f"Solid {i + 1}", s) for i, (n, s) in enumerate(items)]


def from_file(path, fast=False, density=None, overlaps=False):
    """Eine STEP- oder BREP-Datei messen. Gedacht zum Pruefen eines Exports: dieselben Zahlen wie am Modell, aber
    aus der Datei gelesen, also nach der Uebergabe an ein anderes Programm."""
    import cadquery as cq
    p = Path(path).resolve()
    if not p.is_file():
        raise InspectError(f"No such file: {p}")
    suffix = p.suffix.lower()
    if suffix not in FORMATS:
        raise InspectError(f"Cannot inspect {suffix or 'a file without extension'}. Supported: "
                           + ", ".join(FORMATS))
    if suffix == ".brep":
        shape = cq.Shape.importBrep(str(p))
        solids = shape.Solids()
        if not solids:
            raise InspectError(f"{p.name} contains no solid")
        items = [(f"Solid {i + 1}", s) for i, s in enumerate(solids)]
    else:
        items = _step_solids(p)
    parts = [_part(name, shape, fast=fast) for name, shape in items]
    return _document(dict(kind="file", file=p.name, format=suffix.lstrip(".")), parts, fast, density,
                     items if overlaps else None)


# --- Ausgabe ------------------------------------------------------------------------------------------------------------

def text(doc):
    """Kurzfassung fuer das Terminal. Die Zahlen stehen auf sechs Stellen gerundet wie im JSON."""
    src = doc["source"]
    where = src.get("entry") if src["kind"] == "model" else src.get("file")
    t = doc["totals"]
    lines = [f"{where}: {t['parts']} part(s), {t['solids']} solid(s)"]
    b = doc["bounds"]
    if b:
        lines.append(f"Bounds  {_fmt3(b['size'])} mm  from {_fmt3(b['min'])} to {_fmt3(b['max'])}")
    if t["volume"] is not None:
        vol = f"Volume  {t['volume']:.1f} mm³"
        if t.get("mass_g") is not None:
            vol += f"   Mass {t['mass_g']:.1f} g at {t['density_g_cm3']:g} g/cm³"
        lines.append(vol)
    if t["area"] is not None:
        lines.append(f"Area    {t['area']:.1f} mm²")
    if t.get("note"):
        lines.append(f"Note    {t['note']}")
    lines.append("")
    head = f"{'Part':<28} {'Role':<10} {'Volume mm³':>13} {'Faces':>7} {'Solids':>7} {'Valid':>6}"
    lines.append(head)
    lines.append("-" * len(head))
    for p in doc["parts"]:
        name = p["name"] if len(p["name"]) <= 27 else p["name"][:26] + "…"
        vol = "—" if p["volume"] is None else f"{p['volume']:.1f}"
        valid = {True: "yes", False: "NO", None: "?"}[p.get("valid")]
        lines.append(f"{name:<28} {p['role']:<10} {vol:>13} {p['topology']['faces']:>7} "
                     f"{p['topology']['solids']:>7} {valid:>6}")
    issues = doc["checks"]["issues"]
    lines.append("")
    if "overlaps" in doc:
        # Ohne diese Zeile sieht "Checks: ok" genauso aus wie ein Lauf, der gar nicht nach Ueberschneidungen gefragt hat
        n = len(doc["overlaps"])
        lines.append("Overlaps: none" if not n else f"Overlaps: {n} pair(s)")
    if not issues:
        lines.append("Checks: ok")
    else:
        errors = sum(1 for i in issues if i["level"] == "error")
        warnings = len(issues) - errors
        lines.append(f"Checks: {'FAILED' if errors else 'ok'} ({errors} error(s), {warnings} warning(s))")
        for i in issues:
            lines.append(f"  {i['level']:<7} {i['part']}: {i['message']}")
    return "\n".join(lines)


def _fmt3(v):
    return "(" + ", ".join(f"{x:g}" for x in v) + ")"


def write(doc, out=None):
    """JSON schreiben: nach `out` (Pfad, lesbar eingerueckt) oder als eine Zeile fuer die Pipe. Immer UTF-8.

    Die Pipe bekommt die kompakte Form: eine Zeile ist in einem Test oder einem Diff eine Zeile, nicht hundert.
    Eine Datei bekommt indent=2, weil sie gelesen wird.
    """
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return None
    return json.dumps(doc, ensure_ascii=False)
