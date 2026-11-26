"""SOMA as an MCP server over stdio (Model Context Protocol), for coding agents outside the app.

    soma mcp --project .              start the server for this model
    soma mcp --project . --read-only  measuring only, no build and no export

An agent that speaks MCP (Codex, Claude Code, Gemini CLI, Cursor, ...) starts this process and gets four tools:
build the model, measure it, list what it needs, export it. Nothing else.

## Why this is not the CadQuery MCP server

The official CadQuery MCP server takes a Python string as `code` and runs it. SOMA has no sandbox: `soma build`
runs `model.py` with the user's rights, so a tool that accepts arbitrary Python adds a second way to run code with
those rights — through a channel the user never sees. The plan (docs/FASTENERS-INVENTORY.md, docs/INSPECT-SCHEMA.md)
therefore rules that out.

This server has **no parameter anywhere that carries code, a script, a command or a path**:

| Rule | How |
|---|---|
| No code execution | No tool has a `code`, `script`, `cmd`, `python` or `shell` parameter. The tools call Python functions directly, never a shell. |
| No arbitrary paths | The project folder is fixed at start (`--project`). Export always writes to `exports/` inside it; no tool takes a path. |
| No format outside the list | `soma_export` takes an enum of the formats `soma export` already supports. |
| Read-only mode | `--read-only` removes `soma_build` and `soma_export` from the tool list entirely. |
| stdout belongs to the protocol | Anything a model prints while a tool runs goes to stderr, on the Python and on the file-descriptor level. |

`soma mcp --print-tools` writes the tool list as JSON and exits: that is what the test uses to prove the rules
above still hold.
"""
import contextlib
import json
import os
import sys
from pathlib import Path

PROTOCOL = "2025-06-18"
SUPPORTED = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER = "soma"

# Werkzeuge, die nur lesen und messen. Sie laufen im Modus --read-only weiter: sie fuehren model.py aus (das tut
# `soma build` auch), schreiben aber nichts.
READ_ONLY_TOOLS = ("soma_inspect", "soma_bom")

# Werkzeuge ohne Argument, das Code, einen Befehl oder einen Pfad traegt. Die Beschreibungen sind absichtlich knapp:
# sie landen im Kontextfenster des Agenten.
TOOLS = [
    dict(
        name="soma_build",
        description="Build the model: run model.py, write output/model.step, the viewer mesh and the mapping. "
                    "Returns the parts with their names, roles and groups, the parameter values, and any warnings. "
                    "Run this after editing the model. Takes seconds to minutes depending on the model.",
        inputSchema=dict(type="object", properties={}, additionalProperties=False),
    ),
    dict(
        name="soma_inspect",
        description="Measured facts about the built model, without writing anything: volume, surface area, bounding "
                    "box, centre of mass, number of solids/shells/faces/edges/vertices, whether each part is a valid "
                    "closed body, and a list of problems (no solid, invalid shape, duplicate). Use it to check that "
                    "a change did what it should instead of guessing from a picture. With overlaps=true it also "
                    "reports which parts cut into each other, which is how an assembly is checked.",
        inputSchema=dict(type="object", properties=dict(
            parts=dict(type="array", items=dict(type="string"),
                       description="Only these part names. Default: all parts."),
            density=dict(type="number", exclusiveMinimum=0,
                         description="Material density in g/cm³ for a mass estimate, e.g. 1.24 for PLA, 2.7 for "
                                     "aluminium, 7.85 for steel."),
            fast=dict(type="boolean", description="Skip the validity check (the slow part on freeform geometry)."),
            overlaps=dict(type="boolean",
                          description="Also measure which parts cut into each other, with the volume and the depth "
                                      "of each pair. Slower: one boolean intersection per candidate pair. Use it on "
                                      "an assembly, where a part in the wrong place is the usual mistake."),
        ), additionalProperties=False),
    ),
    dict(
        name="soma_bom",
        description="Bill of materials: what has to be bought, grouped by designation with a count, and what has to "
                    "be made, with volume. Use it to tell the user what the model needs, or to check that every "
                    "screw in the design is a standard part.",
        inputSchema=dict(type="object", properties=dict(
            density=dict(type="number", exclusiveMinimum=0,
                         description="Material density in g/cm³ for the mass of the manufactured parts."),
            merge_identical=dict(type="boolean",
                                 description="One line for manufactured parts with the same volume, area and box."),
        ), additionalProperties=False),
    ),
    dict(
        name="soma_export",
        description="Export parts to exports/ inside the model folder. Returns the written file names. "
                    "Reference and purchased parts are skipped unless named explicitly.",
        inputSchema=dict(type="object", properties=dict(
            format=dict(type="string", enum=["step", "stl", "3mf", "amf", "brep", "iges", "obj", "vrml", "glb",
                                             "gltf", "dxf", "svg"]),
            parts=dict(type="array", items=dict(type="string"),
                       description="Part names to export. Default: all own parts."),
            assembly=dict(type="boolean",
                          description="The whole model as one STEP file with groups, names and colours "
                                      "(only with format step)."),
            units=dict(type="string", enum=["mm", "cm", "m", "in"],
                       description="Mesh formats: unit of the file. Default: m for glb/gltf, mm otherwise."),
            up=dict(type="string", enum=["z", "y"], description="Mesh formats: axis pointing up."),
            detail=dict(type="string", enum=["coarse", "normal", "fine"], description="Mesh formats: mesh density."),
            tolerance=dict(type="number", exclusiveMinimum=0,
                           description="Mesh formats: maximum deviation from the surface in mm, overrides detail."),
        ), required=["format"], additionalProperties=False),
    ),
]


class McpError(Exception):
    """Ein Fehler, den der Aufrufer sieht: falsches Argument, unbekanntes Werkzeug, Projektfehler."""


def _inside(root, rel):
    """Ein Pfad muss im Projekt bleiben. Kein Werkzeug nimmt heute einen Pfad entgegen; diese Pruefung ist die
    Sperre fuer den Tag, an dem eines es tut."""
    p = (root / rel).resolve()
    if not p.is_relative_to(root):
        raise McpError(f"Path leaves the model folder: {rel!r}")
    return p


# --- Argumentpruefung ---------------------------------------------------------------------------------------------------

_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "number": (int, float)}


def _validate(schema, args, where="arguments"):
    """Prueft gegen das eigene Schema: unbekannte Schluessel, fehlende Pflichtfelder, Typ, enum, Grenzen.

    Bewusst klein und ohne Abhaengigkeit: das Schema oben ist der einzige Vertrag, den dieses Modul gibt, und
    `additionalProperties: false` ist Teil davon — ein Agent, der `code` mitschickt, bekommt einen Fehler.
    """
    if not isinstance(args, dict):
        raise McpError(f"{where}: expected an object, got {type(args).__name__}")
    props = schema.get("properties", {})
    if schema.get("additionalProperties") is False:
        unknown = sorted(set(args) - set(props))
        if unknown:
            raise McpError(f"{where}: unknown argument(s) {', '.join(repr(u) for u in unknown)}. "
                           f"Allowed: {', '.join(sorted(props)) or 'none'}")
    for key in schema.get("required", ()):
        if key not in args:
            raise McpError(f"{where}: {key!r} is required")
    for key, value in args.items():
        spec = props.get(key, {})
        kind = spec.get("type")
        if kind:
            ok = isinstance(value, _TYPES.get(kind, object))
            if kind == "number" and isinstance(value, bool):
                ok = False  # bool ist in Python eine Zahl, hier aber ein eigener Typ
            if not ok:
                raise McpError(f"{where}: {key!r} must be {kind}, got {type(value).__name__}")
        if "enum" in spec and value not in spec["enum"]:
            raise McpError(f"{where}: {key!r} must be one of {', '.join(map(str, spec['enum']))}, got {value!r}")
        if kind == "number":
            if "exclusiveMinimum" in spec and not value > spec["exclusiveMinimum"]:
                raise McpError(f"{where}: {key!r} must be greater than {spec['exclusiveMinimum']}")
            if "minimum" in spec and value < spec["minimum"]:
                raise McpError(f"{where}: {key!r} must be at least {spec['minimum']}")
        if kind == "array" and "items" in spec:
            for v in value:
                if spec["items"].get("type") and not isinstance(v, _TYPES[spec["items"]["type"]]):
                    raise McpError(f"{where}: every entry of {key!r} must be {spec['items']['type']}")


# --- Werkzeuge ----------------------------------------------------------------------------------------------------------

def tool_build(root, args):
    """Das Modell bauen. Dasselbe wie `soma build`."""
    from . import build
    res = build.run_build(root)
    if res["status"] != "ok":
        e = res["error"]
        where = f"{e.get('file')}:{e.get('line')}" if e.get("file") else ""
        text = f"Build failed{(' at ' + where) if where else ''}: {e['message']}"
        if e.get("traceback"):
            text += "\n\n" + e["traceback"]
        return text, dict(status="error", error=e, warnings=res.get("warnings", []))
    parts = res.get("parts", [])
    lines = [f"Build ok: {len(parts)} part(s) -> output/model.step"]
    for p in parts:
        group = "/".join(p.get("group") or ())
        lines.append(f"  {p['name']} ({p.get('role', 'part')}{', ' + group if group else ''})")
    for w in res.get("warnings", []):
        lines.append(f"warning: {w}")
    return "\n".join(lines), dict(status="ok", parts=parts, params=res.get("params", []),
                                  warnings=res.get("warnings", []))


def tool_inspect(root, args):
    """Messen. Dieselben Zahlen wie `soma inspect --json`."""
    from . import inspection
    doc = inspection.from_model(root, only=args.get("parts"), fast=bool(args.get("fast")),
                                density=args.get("density"), overlaps=bool(args.get("overlaps")))
    return inspection.text(doc), doc


def tool_bom(root, args):
    """Kosovnica. Dieselben Zahlen wie `soma bom --json`."""
    from . import bom
    try:
        doc = bom.build(root, args.get("density"), merge_identical=bool(args.get("merge_identical")))
    except bom.BomError as e:
        raise McpError(str(e)) from e
    return bom.text(doc), doc


def tool_export(root, args):
    """Exportieren. Ziel ist immer exports/ im Projekt: der Aufrufer kann keinen Pfad waehlen."""
    from . import build, cli, meshexport
    fmt = args["format"]
    assembly = bool(args.get("assembly"))
    if assembly and fmt != "step":
        raise McpError("assembly only works with format step")
    mesh = fmt in meshexport.MESH_FORMATS
    given = [k for k in ("units", "up", "detail", "tolerance") if k in args]
    if given and not mesh:
        raise McpError(f"{', '.join(given)} only apply to mesh formats ({', '.join(meshexport.MESH_FORMATS)}), "
                       f"not to {fmt}")
    try:
        parts = build.run_model(root)
    except build.BuildError as e:
        raise McpError(f"Cannot export, the model does not build: {e.message}") from e
    out_dir = _inside(root, "exports")
    if assembly:
        from . import registry
        name = build.read_project_json(root).get("name") or root.name
        path = out_dir / f"{registry.ascii_name(name)}.step"
        out_dir.mkdir(parents=True, exist_ok=True)
        build.step_assembly(parts, name).export(str(path))
        return f"exported: {path.relative_to(root).as_posix()}", dict(files=[path.relative_to(root).as_posix()])
    if args.get("parts"):
        wanted = list(dict.fromkeys(args["parts"]))
        unknown = [n for n in wanted if not any(n in (p["name"], p["step_name"]) for p in parts)]
        if unknown:
            raise McpError("No such part: " + ", ".join(repr(u) for u in unknown) + ". Registered: "
                           + ", ".join(repr(p["name"]) for p in parts))
        chosen = [p for p in parts if p["name"] in wanted or p["step_name"] in wanted]
    else:
        # Wie `soma export --all`: Referenzen und Zukaufteile gehoeren nicht dazu
        chosen = [p for p in parts if p["role"] not in ("reference", "hardware")]
    mesh_opts = None
    if mesh:
        du, dup = meshexport.default_options(fmt)
        mesh_opts = dict(units=args.get("units") or du, up=args.get("up") or dup,
                         detail=args.get("detail") or "normal", tol=args.get("tolerance"))
        err = meshexport.check_options(fmt, mesh_opts["units"], mesh_opts["up"], mesh_opts["detail"])
        if err:
            raise McpError(err)
    out_dir.mkdir(parents=True, exist_ok=True)
    files, notes = [], []
    for p in chosen:
        path = _inside(out_dir, f"{p['step_name']}.{fmt}")
        notes += cli._export_one(p["shape"], fmt, path, p["name"], mesh_opts)
        files.append(path.relative_to(root).as_posix())
    lines = [f"exported: {f}" for f in files] + [f"warning: {n}" for n in notes]
    if not files:
        lines.append("Nothing to export: no part with role 'part'.")
    return "\n".join(lines), dict(files=files, warnings=notes)


HANDLERS = {"soma_build": tool_build, "soma_inspect": tool_inspect, "soma_bom": tool_bom,
            "soma_export": tool_export}


# --- Protokoll ----------------------------------------------------------------------------------------------------------

class Server:
    """JSON-RPC 2.0 ueber stdio, eine Nachricht je Zeile. Kein HTTP, kein Port, kein Socket: der Agent startet den
    Prozess und redet mit ihm ueber seine Standardkanaele."""

    def __init__(self, root, read_only=False, stdin=None, stdout=None):
        self.root = Path(root).resolve()
        self.read_only = read_only
        self.stdin = stdin or sys.stdin
        self.out = stdout or sys.stdout
        self.tools = [t for t in TOOLS if not read_only or t["name"] in READ_ONLY_TOOLS]
        self.initialized = False

    # Ausgabe: immer an den beim Start gemerkten Strom, nie an sys.stdout (das zeigt waehrend eines Werkzeugs nach stderr)
    def _send(self, msg):
        self.out.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.out.flush()

    def _result(self, rid, result):
        self._send(dict(jsonrpc="2.0", id=rid, result=result))

    def _error(self, rid, code, message, data=None):
        err = dict(code=code, message=message)
        if data is not None:
            err["data"] = data
        self._send(dict(jsonrpc="2.0", id=rid, error=err))

    def handle(self, msg):
        """Eine Nachricht. Benachrichtigungen (ohne id) bekommen keine Antwort."""
        if not isinstance(msg, dict):
            self._error(None, -32600, "Invalid Request")
            return
        method = msg.get("method")
        rid = msg.get("id")
        params = msg.get("params") or {}
        if method is None:
            self._error(rid, -32600, "Invalid Request: no method")
            return
        if rid is None:  # notification: initialized, cancelled, ...
            return
        if method == "initialize":
            self._result(rid, self._initialize(params))
        elif method == "ping":
            self._result(rid, {})
        elif method == "tools/list":
            self._result(rid, dict(tools=self.tools))
        elif method == "tools/call":
            self._call(rid, params)
        else:
            self._error(rid, -32601, f"Method not found: {method}")

    def _initialize(self, params):
        asked = params.get("protocolVersion")
        version = asked if asked in SUPPORTED else PROTOCOL
        return dict(
            protocolVersion=version,
            capabilities=dict(tools=dict(listChanged=False)),
            serverInfo=dict(name=SERVER, version=_version()),
            instructions=(
                "SOMA builds parametric CAD models from Python (CadQuery). The model is model.py in this folder; "
                "every part is registered with add_part(name, shape). "
                + ("This server is read-only: only soma_inspect and soma_bom are available."
                   if self.read_only else
                   "Edit model.py, then call soma_build and check the result with soma_inspect before exporting.")
            ),
        )

    def _call(self, rid, params):
        name = params.get("name")
        args = params.get("arguments") or {}
        tool = next((t for t in self.tools if t["name"] == name), None)
        if tool is None:
            self._error(rid, -32602, f"Unknown tool: {name!r}. Available: "
                                     + ", ".join(t["name"] for t in self.tools))
            return
        try:
            _validate(tool["inputSchema"], args, f"{name} arguments")
            with _quiet():
                text, structured = HANDLERS[name](self.root, args)
        except McpError as e:
            self._result(rid, dict(content=[dict(type="text", text=str(e))], isError=True))
            return
        except Exception as e:  # nie den Server abstuerzen: der Agent soll den Fehler lesen und weitermachen
            import traceback
            traceback.print_exc(file=sys.stderr)
            self._result(rid, dict(content=[dict(type="text", text=f"{type(e).__name__}: {e}")], isError=True))
            return
        self._result(rid, dict(content=[dict(type="text", text=text)], structuredContent=structured,
                               isError=False))

    def run(self):
        for line in self.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError as e:
                self._error(None, -32700, f"Parse error: {e}")
                continue
            for one in (msg if isinstance(msg, list) else [msg]):
                self.handle(one)
        return 0


def _version():
    from . import __version__
    return __version__


@contextlib.contextmanager
def _quiet():
    """stdout gehoert dem Protokoll. Was ein Modell waehrend eines Werkzeugs druckt, geht nach stderr — auch was
    native Bibliotheken (OCCT, gmsh) am Dateideskriptor vorbei an Python schreiben."""
    saved_py = sys.stdout
    saved_fd = None
    try:
        sys.stdout = sys.stderr
        try:
            saved_fd = os.dup(1)
            os.dup2(2, 1)
        except (OSError, AttributeError, ValueError):
            saved_fd = None  # keine echten Deskriptoren (Tests, Umleitungen): die Python-Ebene genuegt
        yield
    finally:
        sys.stdout = saved_py
        if saved_fd is not None:
            try:
                os.dup2(saved_fd, 1)
            finally:
                os.close(saved_fd)


def serve(project=".", read_only=False):
    """Der Server. Blockiert, bis der Agent stdin schliesst."""
    root = Path(project).resolve()
    if not root.is_dir():
        raise McpError(f"Not a folder: {root}")
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass
    return Server(root, read_only).run()


def tools_json(read_only=False):
    """Die Werkzeugliste als JSON. Fuer `--print-tools` und den Test, der die Sicherheitsregeln prueft."""
    return [t for t in TOOLS if not read_only or t["name"] in READ_ONLY_TOOLS]
