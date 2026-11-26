# External CAD bridges — PartCAD, FreeCAD, KiCad

**Status:** decision and POC procedure · **Prepared:** 2026-11-26 · **Executed:** no (neither tool is installed on the
machine this was written on)

> This document decides **whether and how** SOMA talks to another CAD system. It does not install anything and adds
> no dependency. Read it as: what a POC has to prove before anyone writes a line of integration code.

---

## 1. The rule that decides everything else

**SOMA stays a CadQuery tool.** `model.py` is Python, `add_part` registers parts, `soma build` writes the STEP. Every
bridge below is a **file handoff**, not a second geometry kernel inside SOMA:

```
model.py --soma build--> output/model.step --handoff--> external tool --> result.step / result.json --back-->
```

Four consequences, all of them non-negotiable:

| Rule | Why |
|---|---|
| **No external package in `.soma/env`** | `env.py` pins the base environment for every model. One package that wants another numpy breaks CadQuery for that model and every later `pip install` in it. |
| **No external daemon started by SOMA** | A daemon runs with the user's rights and outlives the window. If the user did not start it, SOMA must not either. |
| **No `--http` transport, ever** | PartCAD's HTTP mode has no authentication (its own documentation says so). `--http` on a laptop is a CAD server for the whole network. |
| **Every handoff is verified by measurement, not by eye** | `soma inspect --step result.step` and a comparison against the model. A file that opens is not a file that is correct. |

## 2. What each candidate is actually good for

### PartCAD — library, assemblies, BOM, procurement

Apache-2.0, declarative `partcad.yaml`, own daemon, own execution environments, own MCP over stdio.

**Good for:** part libraries with parameters and interfaces, assemblies and sub-assemblies, materials and BOM,
reuse of catalogue components, 2.5D CAM, and a documented way to publish and consume CAD packages.

**Overlaps with SOMA:** parametric parts (SOMA: `model.py` + `param()`), assemblies (SOMA: `group=`), BOM (SOMA:
`soma bom`, quantities and designations only), FEA (SOMA: `soma analyze fem`).

**Verdict:** the interesting overlap is **part libraries and procurement**, not geometry and not quantities. SOMA's
`soma bom` already produces the quantities from the model (`docs/BOM.md`); what PartCAD adds on top is supply chain,
make-or-buy decisions and published packages. A POC should therefore test exactly that — not "can PartCAD open our
STEP file" (it can), and not "can it count screws" (SOMA does).

### FreeCAD — PartDesign, TechDraw, CAM, FEM

Three MCP servers are on the table. Pick **one**, by measurement:

| Project | Licence | Strength | Known weakness |
|---|---|---|---|
| `gchen19/AnkusDrive` | Apache-2.0 | ~280 structured tools, FreeCAD 1.1, parts, gears, bearings, drawings, CAM, FEM | Needs FreeCAD 1.1.x and its own Python; not a library |
| `trailcurrentoss/TrailCurrentFreeCADTools` | MIT | ~100 tools, also QR relief and handoff to Bambu Studio / Blender | Runs on the **GUI thread**: a long call freezes the window, a modal dialog blocks every later call |
| `sergiudanstan/freecad-mcp` | MIT | FEM, TechDraw, sketches, assemblies | Third option, unmeasured |

**Overlap:** TechDraw (SOMA has `soma drawing` with HLR), PartDesign (SOMA is code-first by design), FEM (SOMA has its
own).

**Verdict:** only worth it for **TechDraw output a shop demands** or for a feature SOMA genuinely lacks. A GUI-thread
MCP is a hang waiting to happen in a desktop app — that alone disqualifies TrailCurrent for anything automated.

### KiCad Packages3D — footprints to 3D

Not a CAD bridge but a **model source**: 3D bodies for electronic parts, generated from footprints. The honest path
today is: export the STEP from KiCad by hand into `inputs/`, then `import_assembly` (see the `assemblies` skill). A
generator integration is only worth it if a user produces boards weekly.

---

## 3. POC procedure

Each candidate gets its own POC, in this order, and each POC can fail without affecting the others.

### 3.1 Setup (outside the project)

```bash
# A separate environment, NOT in .soma/env and NOT the app's base environment
python -m venv ~/poc/partcad-env
~/poc/partcad-env/bin/pip install partcad      # or: pipx install partcad
pc --version
```

Record the version in the POC result. A bridge is only as reproducible as the version it was tested with.

### 3.2 The handoff that must work first

This half needs no external tool and can be run today:

```bash
soma export --assembly --format step            # -> exports/<model>.step
soma inspect --json --out model.json
soma inspect --step exports/<model>.step --json --out handoff.json
```

**Acceptance:** `totals.solids` equal, `totals.volume` equal within 0.1 %, `bounds.size` equal. If this fails, the
problem is in SOMA and no external tool will fix it.

### 3.3 Round trip

```bash
# external tool reads the STEP and writes it back unchanged (no edits)
pc <verb> exports/<model>.step --out ~/poc/back.step     # exact command depends on the PartCAD version
soma inspect --step ~/poc/back.step --json
```

**Acceptance:** same solid count, volume within 0.1 %, box within 0.05 mm. Anything worse means the tool re-tessellated
or repaired the geometry. That is a fact to record, not a bug to work around.

### 3.4 The feature the bridge is for

Only now test the actual reason:

- **PartCAD:** read a `partcad.yaml` with three parts and one assembly, produce a BOM with quantities, part numbers
  and a make-or-buy decision, and compare the quantities against `soma bom --json`. Acceptance: same quantities, same
  designations, and a named part number for every purchased part. **Quantities alone are not a reason to adopt it** —
  `soma bom` does those. What the POC has to show is the part beyond that: a catalogue component SOMA cannot model,
  or a supply-chain field that survives.
- **FreeCAD:** open the assembly, produce a TechDraw sheet with one section and three dimensions, export PDF. Acceptance:
  the dimensions match `soma inspect` within 0.05 mm, and the call does not freeze a window for more than 2 s.
- **KiCad:** one board STEP through `import_assembly`, clearances cut around it, `soma inspect` shows the board as one
  reference with its bodies.

### 3.5 Kill criteria

Stop the POC and record the reason if any of these happens:

- The tool wants to be installed into `.soma/env` or into the app's base environment.
- A round trip changes the volume by more than 1 %.
- A call blocks for more than 30 s without progress output.
- The only way to use it is `--http` or a GUI thread.
- The licence is not Apache-2.0/MIT-compatible with GPL-3.0-or-later distribution (SOMA ships under
  GPL-3.0-or-later, see `LICENSE`).

### 3.6 What to record

A short table in this document per candidate: version, date, machine, the three acceptance numbers, the feature result,
and the verdict. Without that, the next person repeats the POC.

---

## 4. If a bridge is adopted later

Shape of the integration, if a POC succeeds:

1. **A separate command, not a hidden call.** `soma external <tool> …`, opt-in, with the tool path from an environment
   variable. Never started by `soma build`.
2. **A fixed argument vector.** `subprocess.run([...], shell=False)` with a list built from an enum and validated paths
   — the same rule as `mcp.py` (no free-form string reaches a process).
3. **A file contract, versioned.** `exports/<model>.step` out, `external/<tool>/result.step` and `result.json` back,
   both inside the project.
4. **Measurement as the gate.** The command ends with the comparison from §3.3 and fails loudly if the numbers moved.
5. **A skill, not a new architecture.** The agent learns the bridge from a skill (like `soma-app.md` teaches the app),
   so the workflow is documented where the agent already looks.

## 5. Decision log

| Candidate | Status | Reason |
|---|---|---|
| `cq_warehouse` as a dependency | **rejected** | The dimension tables are already in `data/fasteners/` and the geometry is SOMA's own code. See `FASTENERS-INVENTORY.md`. |
| Official CadQuery MCP server | **rejected as a server, kept as a reference** | It executes a Python string as `code`. SOMA has no sandbox, so that is a second way to run code with the user's rights. Its tool set informed `soma mcp`. |
| PartCAD | **POC open** | Value is part libraries and procurement, not geometry and not quantities (those are `soma bom`). §3.1–3.4 not yet run. |
| FreeCAD (AnkusDrive) | **POC open** | Only if TechDraw or a missing solver is a real need. §3.1–3.4 not yet run. |
| FreeCAD (TrailCurrent) | **rejected for automation** | Runs on the GUI thread; a modal dialog blocks every later call. |
| KiCad Packages3D | **not a bridge** | Manual STEP export into `inputs/` is enough until someone produces boards weekly. |
