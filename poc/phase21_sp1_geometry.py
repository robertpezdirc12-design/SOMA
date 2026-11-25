#!/usr/bin/env python3
"""
Phase 2.1 - Specialist 1 (Geometry QA): cq_warehouse 0.8.0 geometry validation
on SOMA's pinned stack (Python 3.12, cadquery 2.8.0, cadquery-ocp 7.9.3.1.1).

Runs on a GitHub-hosted runner via the temporary workflow on branch
test/phase21-geometry of the fork (robertpezdirc12-design/SOMA).
Evidence gathering only - no SOMA production code is modified.

Coverage:
  1. creation success + time for every required part type
  2. isValid() of the whole shape AND of every solid/body individually
  3. solid/body count BEFORE and AFTER STEP export + re-import, on BOTH
     export paths: (a) Shape.exportStep of a single solid/compound,
     (b) cq.Assembly export with named parts
  4. volume / surface area / bbox before-after with relative deltas
  5. PlainWasher root cause: analytic vs measured volume, topology dump,
     BRepCheck diagnostics, profile/revolve control experiments vs the
     boolean hypothesis, all washer subclasses x 2 sizes
  6. Bearing root cause: component structure (races/rollers/caps/cage),
     fused compound vs separate named components through STEP
  7. IsoThread (simple + threaded) and Sprocket: validity, round-trip,
     face-count deltas (thread/tooth survival)
  8. volume tolerance analysis from the measured known-good parts
  9. exact source citations (installed package file:line) for every defect

A zero/empty body count after re-import is ALWAYS recorded as a FAIL.

Outputs: phase21-sp1-results.json, phase21-sp1-summary.md, phase21-sp1-sources.txt
"""
import importlib
import importlib.metadata as md
import inspect
import json
import math
import platform
import re
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

import cadquery as cq

RESULTS = {
    "env": {},
    "source_citations": {},
    "parts": [],
    "washer_root_cause": {},
    "bearing_root_cause": {},
    "assembly_all_parts": {},
    "tolerance_analysis": {},
    "soma_comparison": {},
}

# Proposed STEP round-trip acceptance tolerance (justified in findings.md from
# the measured deviations of known-good analytic parts).
VOLUME_REL_TOL = 1e-4
BBOX_ABS_TOL_MM = 1e-3

STEP_DIR = Path("step_out")
STEP_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------- small helpers

def safe(fn, *a, **kw):
    try:
        return True, fn(*a, **kw), None
    except Exception as e:
        return False, None, f"{type(e).__name__}: {e}"


def enum_name(e):
    try:
        return e.name
    except Exception:
        return str(e)


def rel_delta(new, old):
    if not isinstance(new, (int, float)) or not isinstance(old, (int, float)):
        return None
    if old == 0:
        return None
    return abs(new - old) / abs(old)


def num(x):
    return x if isinstance(x, (int, float)) else None


def fmt(x, nd=4):
    return None if x is None else round(float(x), nd)


def shape_of(obj):
    """cadquery Workplane / Shape / cq_warehouse / SOMA _Part -> Shape"""
    if isinstance(obj, cq.Shape):
        return obj
    if hasattr(obj, "val") and callable(obj.val):
        v = obj.val()
        if isinstance(v, cq.Shape):
            return v
    if hasattr(obj, "shape") and isinstance(obj.shape, (cq.Shape, cq.Workplane)):
        s = obj.shape
        return s.val() if isinstance(s, cq.Workplane) else s
    return cq.Shape.cast(obj.wrapped) if hasattr(obj, "wrapped") else obj


def topo_counts(sh):
    ok, res, err = safe(lambda: {
        "solids": len(sh.Solids()), "shells": len(sh.Shells()),
        "faces": len(sh.Faces()), "wires": len(sh.Wires()),
        "edges": len(sh.Edges()), "vertices": len(sh.Vertices()),
    }, sh)
    return res if ok else {"error": err}


def face_type_summary(sh):
    """per surface-type: face count + total area (evidence for doubled faces,
    B-spline knurls, thread surfaces surviving STEP, ...)"""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    out = {}
    try:
        for f in sh.Faces():
            try:
                t = enum_name(BRepAdaptor_Surface(f.wrapped).GetType())
            except Exception:
                t = "?"
            try:
                a = f.Area()
            except Exception:
                a = 0.0
            rec = out.setdefault(t, {"count": 0, "area_mm2": 0.0})
            rec["count"] += 1
            rec["area_mm2"] = round(rec["area_mm2"] + a, 4)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    return out


def shape_stats(sh):
    st = {"shape_type": enum_name(sh.ShapeType())}
    ok, v, err = safe(sh.Volume)
    st["volume_mm3"] = fmt(v, 4) if ok else f"ERR {err}"
    ok, a, err = safe(sh.Area)
    st["area_mm2"] = fmt(a, 4) if ok else f"ERR {err}"
    ok, bb, err = safe(sh.BoundingBox)
    if ok:
        st["bbox_mm"] = [fmt(bb.xlen, 3), fmt(bb.ylen, 3), fmt(bb.zlen, 3)]
        st["bbox_center"] = [fmt(bb.center.x, 3), fmt(bb.center.y, 3), fmt(bb.center.z, 3)]
    else:
        st["bbox_mm"] = f"ERR {err}"
    ok, val, err = safe(sh.isValid)
    st["valid_whole"] = val if ok else f"ERR {err}"
    st["topo"] = topo_counts(sh)
    # per-solid validity (never trust the whole alone)
    solids = []
    try:
        for i, s in enumerate(sh.Solids()):
            okv, v, _ = safe(s.Volume)
            oka, a, _ = safe(s.Area)
            okx, val, _ = safe(s.isValid)
            solids.append({
                "index": i,
                "volume_mm3": fmt(v, 4) if okv else None,
                "area_mm2": fmt(a, 4) if oka else None,
                "valid": val if okx else None,
                "faces": len(s.Faces()) if okv else None,
            })
    except Exception as e:
        solids = [{"error": f"{type(e).__name__}: {e}"}]
    st["solids_detail"] = solids
    st["all_solids_valid"] = all(s.get("valid") for s in solids) if solids else False
    st["face_types"] = face_type_summary(sh)
    return st


def brepcheck_report(sh):
    """Walk every sub-shape with BRepCheck_Analyzer and collect the error
    categories (e.g. BRepCheck_SelfIntersectingWire)."""
    out = {"whole_valid": None, "status_counts": {}, "examples": []}
    try:
        from OCP.BRepCheck import BRepCheck_Analyzer, BRepCheck_ListIteratorOfListOfStatus
    except Exception as e:
        out["error"] = f"import {e}"
        return out
    try:
        wrapped = sh.wrapped if hasattr(sh, "wrapped") else sh
        an = BRepCheck_Analyzer(wrapped)
        out["whole_valid"] = bool(an.IsValid())

        def statuses(res):
            lst = res.Status()
            try:
                for s in lst:
                    yield s
            except TypeError:
                it = BRepCheck_ListIteratorOfListOfStatus(lst)
                while it.More():
                    yield it.Value()
                    it.Next()

        from OCP.TopAbs import (TopAbs_VERTEX, TopAbs_EDGE, TopAbs_WIRE,
                                TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID)
        from OCP.TopExp import TopExp_Explorer
        kinds = [("vertex", TopAbs_VERTEX), ("edge", TopAbs_EDGE), ("wire", TopAbs_WIRE),
                 ("face", TopAbs_FACE), ("shell", TopAbs_SHELL), ("solid", TopAbs_SOLID)]
        counts = Counter()
        for kind, ta in kinds:
            exp = TopExp_Explorer(wrapped, ta)
            seen = 0
            while exp.More() and seen < 2000:
                sub = exp.Current()
                seen += 1
                try:
                    res = an.Result(sub)
                except Exception:
                    exp.Next()
                    continue
                if res is not None:
                    try:
                        for s in statuses(res):
                            nm = enum_name(s)
                            if nm and "NoError" not in nm:
                                counts[f"{kind}:{nm}"] += 1
                                if len(out["examples"]) < 60:
                                    out["examples"].append({"shape": kind, "status": nm})
                    except Exception:
                        pass
                exp.Next()
        out["status_counts"] = dict(counts)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-400:]}"
    return out


STEP_TOKENS = [
    "MANIFOLD_SOLID_BREP", "BREP_WITH_VOIDS", "CLOSED_SHELL", "OPEN_SHELL",
    "ADVANCED_FACE", "B_SPLINE_SURFACE", "CYLINDRICAL_SURFACE", "CONICAL_SURFACE",
    "TOROIDAL_SURFACE", "SURFACE_OF_REVOLUTION", "SURFACE_OF_LINEAR_EXTRUSION",
    "NEXT_ASSEMBLY_USAGE_OCCURRENCE",
]


def step_text_stats(path):
    try:
        txt = Path(path).read_text(errors="ignore")
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    counts = {t: txt.count(t) for t in STEP_TOKENS}
    counts["PLANE_entity"] = len(re.findall(r"\bPLANE\(", txt))
    names = re.findall(r"PRODUCT\('([^']*)'", txt)
    return {"bytes": Path(path).stat().st_size, "token_counts": counts,
            "product_names": names}


def step_read_status(path):
    """raw STEPControl_Reader counts - what the OCCT reader actually sees"""
    out = {}
    try:
        from OCP.STEPControl import STEPControl_Reader
        r = STEPControl_Reader()
        st = r.ReadFile(str(path))
        out["read_status"] = enum_name(st)
        out["roots_for_transfer"] = r.NbRootsForTransfer()
        out["transferred_roots"] = r.TransferRoots()
        out["nb_shapes"] = r.NbShapes()
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def xcaf_walk(path):
    """Re-import through STEPCAFControl and report names + assembly structure"""
    out = {"ok": False, "error": None, "tree": [], "flat_names": []}
    try:
        from OCP.STEPCAFControl import STEPCAFControl_Reader
        from OCP.TDocStd import TDocStd_Document
        from OCP.TCollection import TCollection_ExtendedString
        from OCP.XCAFDoc import XCAFDoc_DocumentTool
        from OCP.TDF import TDF_LabelSequence
        from OCP.TDataStd import TDataStd_Name

        doc = TDocStd_Document(TCollection_ExtendedString("doc"))
        rd = STEPCAFControl_Reader()
        rd.SetNameMode(True)
        rd.SetColorMode(True)
        rd.ReadFile(str(path))
        rd.Transfer(doc)
        st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
        labels = TDF_LabelSequence()
        st.GetFreeShapes(labels)

        def label_name(lab):
            try:
                attr = TDataStd_Name()
                if lab.FindAttribute(TDataStd_Name.GetID_s(), attr):
                    return str(attr.Get().ToExtString())
            except Exception:
                pass
            return None

        def label_shape(lab):
            try:
                s = st.GetShape_s(lab)
                return None if s is None or s.IsNull() else s
            except Exception:
                return None

        def walk(lab, depth=0):
            node = {"name": label_name(lab), "children": []}
            s = label_shape(lab)
            if s is not None:
                try:
                    sh = cq.Shape.cast(s)
                    node["stats"] = {
                        "shape_type": enum_name(sh.ShapeType()),
                        "volume_mm3": fmt(sh.Volume(), 4),
                        "solids": len(sh.Solids()),
                        "faces": len(sh.Faces()),
                        "valid": sh.isValid(),
                    }
                except Exception as e:
                    node["stats_error"] = f"{type(e).__name__}: {e}"
            if node["name"]:
                out["flat_names"].append(node["name"])
            if depth < 6:
                seq = TDF_LabelSequence()
                got = False
                for getter in ("GetComponents_s", "GetComponents"):
                    try:
                        getattr(st, getter)(lab, seq)
                        got = True
                        break
                    except Exception:
                        continue
                if got:
                    for i in range(1, seq.Length() + 1):
                        if len(out["flat_names"]) < 100:
                            node["children"].append(walk(seq.Value(i), depth + 1))
            return node

        for i in range(1, labels.Length() + 1):
            out["tree"].append(walk(labels.Value(i)))
        out["ok"] = True
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-400:]}"
    return out


def export_shape_step(sh, path):
    """Export path (a): Shape.exportStep of a single solid/compound."""
    t0 = time.perf_counter()
    used = None
    err = None
    if hasattr(sh, "exportStep") and callable(sh.exportStep):
        try:
            sh.exportStep(str(path))
            used = "Shape.exportStep"
        except Exception as e:
            err = f"Shape.exportStep: {type(e).__name__}: {e}"
    if used is None:
        try:
            cq.exporters.export(cq.Workplane().add(sh), str(path),
                                exportType=cq.exporters.ExportTypes.STEP)
            used = "cq.exporters.export"
        except Exception as e:
            err = (err or "") + f" | cq.exporters.export: {type(e).__name__}: {e}"
    dt = round(time.perf_counter() - t0, 3)
    return used, dt, err


def assembly_export(shapes_with_names, path):
    """Export path (b): cq.Assembly with named parts."""
    a = cq.Assembly()
    for name, sh in shapes_with_names:
        a.add(sh, name=name, color=cq.Color(0.75, 0.75, 0.75, 1.0))
    t0 = time.perf_counter()
    err = None
    if hasattr(a, "export"):
        try:
            a.export(str(path))
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
    else:  # pragma: no cover - cadquery 2.8 has export
        a.save(str(path))
    dt = round(time.perf_counter() - t0, 3)
    return dt, err


def reimport_stats(path):
    """Re-import a STEP file and report body counts + stats.
    Zero/empty bodies -> explicit failure flag."""
    out = {"solids_after": 0, "empty_after": True, "fail_reasons": []}
    t0 = time.perf_counter()
    ok, wp, err = safe(cq.importers.importStep, str(path))
    out["import_seconds"] = round(time.perf_counter() - t0, 3)
    if not ok:
        out["import_error"] = err
        out["fail_reasons"].append(f"import failed: {err}")
        return out
    # body count straight from the workplane (robust for empty compounds)
    ok_solids, solids, err_solids = safe(lambda: wp.solids().vals())
    out["solids_after"] = len(solids) if ok_solids else 0
    out["empty_after"] = out["solids_after"] == 0
    if out["empty_after"]:
        out["fail_reasons"].append("zero/empty body count after re-import")
    ok_val, sh, err_val = safe(lambda: wp.val())
    if ok_val:
        out["after"] = shape_stats(sh)
    else:
        out["after"] = {"empty": True, "val_error": err_val}
    out["step_text"] = step_text_stats(path)
    out["step_reader"] = step_read_status(path)
    out["xcaf"] = xcaf_walk(path)
    return out


def gate(before, rt):
    """Acceptance gate for one round-trip record."""
    reasons = []
    sb = before.get("topo", {}).get("solids") if isinstance(before.get("topo"), dict) else None
    sa = rt.get("solids_after")
    rt["solids_before"] = sb
    if sa == 0 or rt.get("empty_after"):
        reasons.append("FAIL: zero/empty body count after re-import")
    if sb is not None and sa is not None and sa != sb:
        reasons.append(f"body count changed: {sb} -> {sa}")
    after = rt.get("after") or {}
    if after.get("all_solids_valid") is False:
        reasons.append("invalid solid(s) after re-import")
    if before.get("valid_whole") is False:
        reasons.append("source shape invalid before export")
    dv = rt.get("deltas", {}).get("volume_rel")
    if dv is not None and dv > VOLUME_REL_TOL:
        reasons.append(f"volume rel delta {dv:.2e} > {VOLUME_REL_TOL:.0e}")
    db = rt.get("deltas", {}).get("bbox_abs_max_mm")
    if db is not None and db > BBOX_ABS_TOL_MM:
        reasons.append(f"bbox delta {db:.2e} mm > {BBOX_ABS_TOL_MM:.0e} mm")
    rt["gate_pass"] = not reasons
    rt["gate_reasons"] = reasons
    return rt


def roundtrip_record(sh, before, name, tag, path_a=True, path_b=True):
    """Run both STEP export paths and compare before/after."""
    rec = {"part": name, "tag": tag}
    base_stats = before

    if path_a:
        pa = STEP_DIR / f"{tag}_a.step"
        used, dt, err = export_shape_step(sh, pa)
        a = {"export_method": used, "export_seconds": dt, "export_error": err}
        if used:
            a.update(reimport_stats(pa))
            a["deltas"] = {
                "volume_rel": rel_delta(num((a.get("after") or {}).get("volume_mm3")),
                                        num(base_stats.get("volume_mm3"))),
                "area_rel": rel_delta(num((a.get("after") or {}).get("area_mm2")),
                                      num(base_stats.get("area_mm2"))),
                "bbox_abs_max_mm": bbox_delta(base_stats, a.get("after") or {}),
                "faces_before_after": [
                    base_stats.get("topo", {}).get("faces"),
                    (a.get("after") or {}).get("topo", {}).get("faces"),
                ],
            }
            gate(base_stats, a)
        else:
            a["gate_pass"] = False
            a["gate_reasons"] = [f"FAIL: STEP export failed - {err} (no geometry to export)"]
        rec["roundtrip_a_shape_exportStep"] = a

    if path_b:
        pb = STEP_DIR / f"{tag}_b.step"
        dt, err = assembly_export([(name, sh)], pb)
        b = {"export_seconds": dt, "export_error": err}
        if not err:
            b.update(reimport_stats(pb))
            b["deltas"] = {
                "volume_rel": rel_delta(num((b.get("after") or {}).get("volume_mm3")),
                                        num(base_stats.get("volume_mm3"))),
                "area_rel": rel_delta(num((b.get("after") or {}).get("area_mm2")),
                                      num(base_stats.get("area_mm2"))),
                "bbox_abs_max_mm": bbox_delta(base_stats, b.get("after") or {}),
                "faces_before_after": [
                    base_stats.get("topo", {}).get("faces"),
                    (b.get("after") or {}).get("topo", {}).get("faces"),
                ],
            }
            names = (b.get("xcaf") or {}).get("flat_names") or []
            b["names_survived"] = name in names
            b["names_found"] = names[:20]
            gate(base_stats, b)
        rec["roundtrip_b_assembly"] = b
    return rec


def bbox_delta(before, after):
    bb1, bb2 = before.get("bbox_mm"), after.get("bbox_mm")
    if not (isinstance(bb1, list) and isinstance(bb2, list)):
        return None
    return round(max(abs(x - y) for x, y in zip(bb1, bb2)), 6)


# ---------------------------------------------------------------- source citations

def dump_sources():
    """Record exact installed file:line for the construction code under test."""
    cites = {}
    try:
        import cq_warehouse
        root = Path(cq_warehouse.__file__).parent
        RESULTS["env"]["cq_warehouse_path"] = str(root)
    except Exception as e:
        RESULTS["env"]["cq_warehouse_path"] = f"ERR {e}"
        root = None

    targets = []
    try:
        from cq_warehouse import fastener as F
        targets += [
            ("cq_warehouse.fastener.Washer.__init__", F.Washer.__init__),
            ("cq_warehouse.fastener.Washer.make_washer", F.Washer.make_washer),
            ("cq_warehouse.fastener.Washer.default_washer_profile", F.Washer.default_washer_profile),
            ("cq_warehouse.fastener.Washer.default_countersink_profile", F.Washer.default_countersink_profile),
            ("cq_warehouse.fastener.PlainWasher", F.PlainWasher),
            ("cq_warehouse.fastener.ChamferedWasher.washer_profile", F.ChamferedWasher.washer_profile),
            ("cq_warehouse.fastener.CheeseHeadWasher.washer_profile", F.CheeseHeadWasher.washer_profile),
            ("cq_warehouse.fastener.HexNut", F.HexNut),
            ("cq_warehouse.fastener.SocketHeadCapScrew", F.SocketHeadCapScrew),
            ("cq_warehouse.fastener.HeatSetNut.make_nut", F.HeatSetNut.make_nut),
            ("cq_warehouse.fastener.HeatSetNut.knurled_cylinder_faces", F.HeatSetNut.knurled_cylinder_faces),
        ]
    except Exception as e:
        cites["fastener_import_error"] = str(e)
    try:
        from cq_warehouse import bearing as B
        targets += [
            ("cq_warehouse.bearing.Bearing.__init__", B.Bearing.__init__),
            ("cq_warehouse.bearing.Bearing.make_bearing", B.Bearing.make_bearing),
            ("cq_warehouse.bearing.Bearing.default_inner_race_section", B.Bearing.default_inner_race_section),
            ("cq_warehouse.bearing.Bearing.default_outer_race_section", B.Bearing.default_outer_race_section),
            ("cq_warehouse.bearing.Bearing.default_roller", B.Bearing.default_roller),
            ("cq_warehouse.bearing.Bearing.default_cap", B.Bearing.default_cap),
        ]
    except Exception as e:
        cites["bearing_import_error"] = str(e)
    try:
        from cq_warehouse.thread import IsoThread
        targets.append(("cq_warehouse.thread.IsoThread.__init__", IsoThread.__init__))
    except Exception as e:
        cites["thread_import_error"] = str(e)
    try:
        from cq_warehouse.sprocket import Sprocket
        targets.append(("cq_warehouse.sprocket.Sprocket.__init__", Sprocket.__init__))
    except Exception as e:
        cites["sprocket_import_error"] = str(e)
    # cadquery construction path used by the washer/bearing profiles
    targets += [
        ("cadquery.cq.Workplane.revolve", cq.Workplane.revolve),
        ("cadquery.cq.Workplane._revolve", cq.Workplane._revolve),
        ("cadquery.cq.Workplane._fuseWithBase", cq.Workplane._fuseWithBase),
    ]
    try:
        from cadquery.occ_impl.shapes import Solid as CQSolid, Face as CQFace
        targets += [
            ("cadquery.occ_impl.shapes.Solid.revolve", CQSolid.revolve),
            ("cadquery.occ_impl.shapes.Face.makeFromWires", CQFace.makeFromWires),
        ]
    except Exception as e:
        cites["cq_shapes_import_error"] = str(e)

    for label, obj in targets:
        try:
            lines, start = inspect.getsourcelines(obj)
            src = "".join(lines[:120])
            cites[label] = {
                "file": inspect.getsourcefile(obj),
                "line_start": start,
                "line_end": start + len(lines) - 1,
                "source": src,
            }
        except Exception as e:
            cites[label] = {"error": f"{type(e).__name__}: {e}"}
    RESULTS["source_citations"] = cites
    return cites


# ---------------------------------------------------------------- part creation

def pick_size(cls, ftype, candidates, prefix):
    """Return (chosen_size, all_sizes). Exact candidates first, then prefix."""
    ok, sizes, err = safe(lambda: sorted(cls.sizes(ftype)))
    if not ok:
        return None, f"ERR {err}"
    for c in candidates:
        if c in sizes:
            return c, sizes
    for s in sizes:
        if s == prefix or s.startswith(prefix + "-") or s.startswith(prefix + "."):
            return s, sizes
    return (sizes[0] if sizes else None), sizes


def build_kwargs(cls, base):
    """Only pass kwargs the constructor accepts; record the exact call."""
    params = inspect.signature(cls.__init__).parameters
    kw = {k: v for k, v in base.items() if k in params}
    return kw


def create_part(name, cls, kwargs, records):
    kw = build_kwargs(cls, kwargs)  # drop kwargs the constructor does not accept
    t0 = time.perf_counter()
    ok, obj, err = safe(lambda: cls(**kw))
    dt = round(time.perf_counter() - t0, 3)
    rec = {"part": name, "class": cls.__name__, "call": f"{cls.__name__}({kw})",
           "requested_kwargs": kwargs,
           "create_ok": ok, "create_seconds": dt, "create_error": err}
    if ok:
        try:
            sh = shape_of(obj)
            rec["before"] = shape_stats(sh)
        except Exception as e:
            rec["before"] = {"error": f"{type(e).__name__}: {e}"}
            sh = None
        rec["_shape"] = sh
        rec["_obj"] = obj
    print(f"{'OK  ' if ok else 'FAIL'} create {name} {dt}s {err or ''}")
    records.append(rec)
    return rec


# ---------------------------------------------------------------- washer root cause

def analytic_washer_volume(d1, d2, h):
    return math.pi / 4.0 * (d2 ** 2 - d1 ** 2) * h


def analytic_washer_area(d1, d2, h):
    return 2 * math.pi / 4.0 * (d2 ** 2 - d1 ** 2) + math.pi * d1 * h + math.pi * d2 * h


def washer_controls(d1, d2, h):
    """Control experiments to localize the PlainWasher defect:
    is it the profile/revolve construction or a boolean?"""
    out = {}
    d1r, d2r = d1 / 2.0, d2 / 2.0

    # C1: extrude control (no revolve, no boolean of profiles)
    ok, res, err = safe(lambda: cq.Workplane("XY").circle(d2r).circle(d1r).extrude(h))
    out["C1_extrude_annulus"] = {
        "ok": ok, "error": err,
        "stats": shape_stats(shape_of(res)) if ok else None,
    }

    # C2: exact cq_warehouse construction pattern (default axis revolve)
    def build_profile():
        return (cq.Workplane("XZ")
                .moveTo(d1r, 0).hLineTo(d2r).vLineTo(h).hLineTo(d1r).close())

    ok, wp, err = safe(build_profile)
    if ok:
        out["C2_profile_wire_count"] = len(wp.wires().vals())
        out["C2_profile_edge_count"] = len(wp.edges().vals())
        wv = wp.wires().vals()
        if wv:
            okf, face, errf = safe(cq.Face.makeFromWires, wv[0])
            if okf:
                out["C2_face_from_wire_area_mm2"] = fmt(face.Area(), 4)
                out["C2_expected_face_area_mm2"] = fmt((d2r - d1r) * h, 4)
                # C3: revolve that single explicit face around the Z axis
                okr, solid, errr = safe(
                    cq.Solid.revolve, face, 360.0,
                    cq.Vector(0, 0, 0), cq.Vector(0, 0, 1))
                out["C3_face_revolve_explicit_axis"] = {
                    "ok": okr, "error": errr,
                    "stats": shape_stats(shape_of(solid)) if okr else None,
                }

    # C4: the exact call cq_warehouse performs (toPending().revolve() with
    #     cadquery's default axis), instrumented
    ok, wp2, err = safe(build_profile)
    if ok:
        wp2 = wp2.toPending()
        out["C4_pending_wires_after_toPending"] = len(wp2.ctx.pendingWires)
        ok2, res2, err2 = safe(lambda: wp2.revolve())
        out["C4_exact_cq_call_revolve"] = {
            "ok": ok2, "error": err2,
            "stats": shape_stats(shape_of(res2)) if ok2 else None,
        }

    # C5: same revolve but combine=False (no fuse-with-base / no clean)
    ok, wp3, err = safe(build_profile)
    if ok:
        ok2, res3, err2 = safe(lambda: wp3.toPending().revolve(combine=False))
        out["C5_revolve_combine_false"] = {
            "ok": ok2, "error": err2,
            "stats": shape_stats(shape_of(res3)) if ok2 else None,
        }

    # C6: inspection of what the real instance returns from make_washer()
    return out


def washer_instance_probe(inst, d1, d2, h):
    """Deep-inspect the shape actually produced by cq_warehouse."""
    out = {"analytic_volume_mm3": fmt(analytic_washer_volume(d1, d2, h), 4),
           "analytic_area_mm2": fmt(analytic_washer_area(d1, d2, h), 4)}
    ok, wp, err = safe(inst.make_washer)
    if ok:
        sh = shape_of(wp)
        out["make_washer_stats"] = shape_stats(sh)
        mv = num(out["make_washer_stats"].get("volume_mm3"))
        ma = num(out["make_washer_stats"].get("area_mm2"))
        av = analytic_washer_volume(d1, d2, h)
        aa = analytic_washer_area(d1, d2, h)
        out["measured_over_analytic_volume"] = fmt(mv / av, 6) if mv else None
        out["measured_over_analytic_area"] = fmt(ma / aa, 6) if ma else None
        out["brepcheck"] = brepcheck_report(sh)
        # wire-per-face check: a doubled profile shows up as faces with >1 wire
        multi_wire = []
        for i, f in enumerate(sh.Faces()):
            ws = f.Wires()
            if len(ws) != 1:
                multi_wire.append({"face": i, "wires": len(ws),
                                   "wire_lengths": [fmt(w.Length(), 4) for w in ws]})
        out["faces_with_multiple_wires"] = multi_wire
        # topological duplicates: two identical solids in one compound?
        vols = [fmt(s.Volume(), 4) for s in sh.Solids()]
        out["solid_volumes_mm3"] = vols
    else:
        out["make_washer_error"] = err
    return out


def rel_delta_abs_ratio(a, b):
    if not b:
        return None
    return a / b


# ---------------------------------------------------------------- bearing root cause

def bearing_components(inst):
    """Rebuild the bearing's components as separate solids using the
    instance's own section/roller methods (mirrors make_bearing)."""
    comps = {}
    try:
        outer = (cq.Workplane("XZ").add(inst.outer_race_section().val())
                 .toPending().revolve())
        comps["outer_race"] = shape_of(outer)
    except Exception as e:
        comps["outer_race"] = f"ERR {type(e).__name__}: {e}"
    try:
        inner = (cq.Workplane("XZ").add(inst.inner_race_section().val())
                 .toPending().revolve())
        comps["inner_race"] = shape_of(inner)
    except Exception as e:
        comps["inner_race"] = f"ERR {type(e).__name__}: {e}"
    try:
        B = inst.bearing_dict["B"]
        count = int(inst.roller_count)
        locs = cq.Workplane("XY").polarArray(
            inst.race_center_radius, 0, 360, count).vals()
        rollers = []
        for loc in locs:
            rollers.append(inst.roller().located(
                loc * cq.Location(cq.Vector(0, 0, B / 2))))
        comps["rollers"] = rollers
        comps["roller_count"] = count
    except Exception as e:
        comps["rollers"] = f"ERR {type(e).__name__}: {e}"
    try:
        if inst.method_exists("cap"):
            cap1 = shape_of(inst.cap())
            cap2 = shape_of(inst.cap().mirror("XY").val().translate(
                (0, 0, inst.bearing_dict["B"])))
            comps["caps"] = [cap1, cap2]
    except Exception as e:
        comps["caps"] = f"ERR {type(e).__name__}: {e}"
    try:
        if inst.method_exists("cage"):
            comps["cage"] = shape_of(inst.cage())
    except Exception as e:
        comps["cage"] = f"ERR {type(e).__name__}: {e}"
    return comps


def bearing_probe(inst, tag):
    """Fused-vs-separate evidence for one bearing."""
    out = {}
    sh = shape_of(inst)
    out["fused_stats"] = shape_stats(sh)
    comps = bearing_components(inst)
    comp_report = {}
    total = 0.0
    named = []
    for k, v in comps.items():
        if k in ("roller_count",) or isinstance(v, (int, float)):
            comp_report[k] = v
            continue
        if isinstance(v, str):
            comp_report[k] = v
            continue
        if isinstance(v, list):
            lst = []
            for j, s in enumerate(v):
                st = shape_stats(s)
                lst.append(st)
                if isinstance(st.get("volume_mm3"), (int, float)):
                    total += st["volume_mm3"]
            comp_report[k] = lst
        else:
            st = shape_stats(v)
            comp_report[k] = st
            if isinstance(st.get("volume_mm3"), (int, float)):
                total += st["volume_mm3"]
            named.append((k, v))
    # rollers as one named compound for the assembly
    if isinstance(comps.get("rollers"), list):
        try:
            rc = cq.Compound.makeCompound(comps["rollers"])
            named.append(("rollers", rc))
        except Exception:
            pass
    if isinstance(comps.get("caps"), list):
        try:
            named.append(("caps", cq.Compound.makeCompound(comps["caps"])))
        except Exception:
            pass
    out["components"] = comp_report
    fv = out["fused_stats"].get("volume_mm3")
    out["sum_component_volumes_mm3"] = fmt(total, 4)
    if isinstance(fv, (int, float)):
        out["interference_volume_mm3"] = fmt(total - fv, 4)
        out["sum_over_fused"] = fmt(total / fv if fv else None, 6)
    out["fused_solids_count"] = out["fused_stats"].get("topo", {}).get("solids")

    # path (a): export the fused shape
    pa = STEP_DIR / f"{tag}_fused_a.step"
    used, dt, err = export_shape_step(sh, pa)
    a = {"export_method": used, "export_seconds": dt, "export_error": err}
    if used:
        a.update(reimport_stats(pa))
        a["deltas"] = {
            "volume_rel": rel_delta(num((a.get("after") or {}).get("volume_mm3")), num(fv)),
            "bbox_abs_max_mm": bbox_delta(out["fused_stats"], a.get("after") or {}),
        }
        gate(out["fused_stats"], a)
    out["roundtrip_fused_a"] = a

    # path (b): export the SEPARATE components as a named assembly
    pb = STEP_DIR / f"{tag}_components_b.step"
    dt, err = assembly_export(named, pb)
    b = {"export_seconds": dt, "export_error": err, "names_in": [n for n, _ in named]}
    if not err:
        b.update(reimport_stats(pb))
        names = (b.get("xcaf") or {}).get("flat_names") or []
        b["names_found"] = names[:30]
        b["names_survived"] = sorted(set(n for n, _ in named) & set(names))
        tree = (b.get("xcaf") or {}).get("tree") or []
        b["xcaf_tree_summary"] = tree[:10]
    out["roundtrip_components_b"] = b
    return out


# ---------------------------------------------------------------- main sections

def env_info():
    e = {"python": sys.version.split()[0], "platform": platform.platform()}
    for pkg in ("cadquery", "cadquery-ocp", "cadquery-ocp-proxy", "cq-warehouse",
                "multimethod", "ezdxf", "numpy"):
        try:
            e[pkg] = md.version(pkg)
        except Exception:
            e[pkg] = "not installed"
    RESULTS["env"] = e
    print("## Environment", json.dumps(e))


def discover_bearings():
    from cq_warehouse.bearing import Bearing
    out = {}
    classes = list(Bearing.__subclasses__())
    for cls in classes:
        entry = {}
        for t in sorted(cls.types()):
            try:
                entry[t] = cls.sizes(t)
            except Exception as ex:
                entry[t] = f"ERR {ex}"
        out[cls.__name__] = entry
    # module-level discovery helper if present
    mod = sys.modules.get("cq_warehouse.bearing")
    modlevel = {}
    for attr in ("types", "bearing_types"):
        if hasattr(mod, attr):
            try:
                modlevel[attr] = str(getattr(mod, attr)())[:500]
            except Exception as ex:
                modlevel[attr] = f"ERR {ex}"
    out["_module_level"] = modlevel
    return out


def smallest_bearing_size(cls, ftype):
    sizes = cls.sizes(ftype)
    def key(s):
        nums = re.findall(r"\d+(?:\.\d+)?", s)
        return tuple(float(n) for n in nums) if nums else (9e9,)
    return sorted(sizes, key=key)[0], sizes


def run_parts():
    from cq_warehouse.fastener import (SocketHeadCapScrew, HexNut, PlainWasher,
                                       ChamferedWasher, CheeseHeadWasher, HeatSetNut)
    from cq_warehouse.thread import IsoThread
    from cq_warehouse.sprocket import Sprocket

    parts = RESULTS["parts"]

    # 1. SocketHeadCapScrew iso4762 M6-1 x 20 (same call as Phase 2 baseline)
    r = create_part("SocketHeadCapScrew iso4762 M6-1 x20", SocketHeadCapScrew,
                    {"size": "M6-1", "length": 20.0, "fastener_type": "iso4762",
                     "simple": True}, parts)
    screw = r

    # 2. HexNut iso4032 M6-1
    r = create_part("HexNut iso4032 M6-1", HexNut,
                    {"size": "M6-1", "fastener_type": "iso4032", "simple": True}, parts)
    nut = r

    # 3. Washers: all 3 subclasses x M6 + M10
    washer_specs = [
        ("PlainWasher", PlainWasher, "iso7089"),
        ("ChamferedWasher", ChamferedWasher, "iso7090"),
        ("CheeseHeadWasher", CheeseHeadWasher, "iso7092"),
    ]
    washer_recs = []
    for wcls_name, wcls, wtype in washer_specs:
        for pref, cands in (("M6", ("M6-1", "M6")), ("M10", ("M10-1.5", "M10"))):
            size, sizes = pick_size(wcls, wtype, cands, pref)
            tag = f"{wcls_name}_{wtype}_{pref}"
            r = create_part(f"{wcls_name} {wtype} {size}", wcls,
                            {"size": size, "fastener_type": wtype, "simple": True},
                            parts)
            r["all_sizes"] = sizes
            washer_recs.append((tag, size, wtype, wcls_name, wcls, r))

    # 4. HeatSetNut Hilitchi M3-0.5-8 (simple and threaded)
    hs_recs = []
    for simple in (True, False):
        r = create_part(f"HeatSetNut Hilitchi M3-0.5-8 simple={simple}", HeatSetNut,
                        {"size": "M3-0.5-8", "fastener_type": "Hilitchi",
                         "simple": simple}, parts)
        hs_recs.append((f"heatset_simple_{simple}", r))

    # 5. All bearing classes, smallest size each
    inv = discover_bearings()
    RESULTS["bearing_inventory"] = inv
    bearing_recs = []
    from cq_warehouse.bearing import Bearing
    for cls in Bearing.__subclasses__():
        ftype = sorted(cls.types())[0]
        size, sizes = smallest_bearing_size(cls, ftype)
        r = create_part(f"{cls.__name__} {ftype} {size}", cls,
                        {"size": size, "bearing_type": ftype}, parts)
        r["all_sizes"] = sizes
        bearing_recs.append((cls.__name__, size, r))

    # 6. IsoThread M6-1 both modes
    th_simple = create_part("IsoThread M6x10 simple=True", IsoThread,
                            {"major_diameter": 6.0, "pitch": 1.0, "length": 10.0,
                             "external": True, "simple": True}, parts)
    th_threaded = create_part("IsoThread M6x10 simple=False (real thread)", IsoThread,
                              {"major_diameter": 6.0, "pitch": 1.0, "length": 10.0,
                               "external": True, "simple": False}, parts)

    # 7. Sprocket 18 teeth
    sprocket = create_part("Sprocket num_teeth=18", Sprocket,
                           {"num_teeth": 18}, parts)

    return (screw, nut, washer_recs, hs_recs, bearing_recs,
            th_simple, th_threaded, sprocket)


def run_roundtrips(all_recs):
    """Per-part round-trips on both export paths."""
    roundtrips = []
    for r in all_recs:
        sh = r.get("_shape")
        if sh is None:
            why = "no shape: " + ("null shape by design (IsoThread simple=True)"
                                  if r.get("no_geometry_by_design")
                                  else str(r.get("create_error") or
                                           (r.get("before") or {}).get("error", "unknown")))
            roundtrips.append({"part": r["part"], "skipped": why})
            continue
        before = r.get("before") or {}
        tag = re.sub(r"[^A-Za-z0-9]+", "_", r["part"])[:60]
        try:
            rt = roundtrip_record(sh, before, r["part"], tag)
        except Exception as e:
            rt = {"part": r["part"], "error": f"{type(e).__name__}: {e}\n{traceback.format_exc()[-500:]}"}
        roundtrips.append(rt)
        a = rt.get("roundtrip_a_shape_exportStep") or {}
        b = rt.get("roundtrip_b_assembly") or {}
        print(f"RT   {r['part']}: A solids {a.get('solids_after')} pass={a.get('gate_pass')} | "
              f"B solids {b.get('solids_after')} pass={b.get('gate_pass')}")
    RESULTS["roundtrips"] = roundtrips
    return roundtrips


def run_washer_root_cause(washer_recs):
    rc = {}
    for tag, size, wtype, wcls_name, wcls, r in washer_recs:
        obj = r.get("_obj")
        entry = {"size": size, "fastener_type": wtype, "class": wcls_name}
        if obj is None:
            entry["error"] = r.get("create_error")
            rc[tag] = entry
            continue
        try:
            d1, d2, h = (float(obj.washer_data[p]) for p in ("d1", "d2", "h"))
            entry["csv_params_mm"] = {"d1": d1, "d2": d2, "h": h}
            entry["analytic_volume_mm3"] = fmt(analytic_washer_volume(d1, d2, h), 4)
            entry["analytic_area_mm2"] = fmt(analytic_washer_area(d1, d2, h), 4)
            entry["probe"] = washer_instance_probe(obj, d1, d2, h)
            bv = num(entry["probe"].get("make_washer_stats", {}).get("volume_mm3"))
            if bv:
                entry["measured_volume_mm3"] = bv
                entry["measured_over_analytic"] = fmt(
                    bv / analytic_washer_volume(d1, d2, h), 6)
            # controls only for M6 and M10 plain-family (cheap)
            entry["controls"] = washer_controls(d1, d2, h)
        except Exception as e:
            entry["error"] = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-400:]}"
        rc[tag] = entry
    RESULTS["washer_root_cause"] = rc
    return rc


def run_bearing_root_cause(bearing_recs):
    rc = {}
    for cls_name, size, r in bearing_recs:
        inst = r.get("_obj")
        entry = {"size": size, "class": cls_name}
        if inst is None:
            entry["error"] = r.get("create_error")
            rc[cls_name] = entry
            continue
        try:
            entry.update(bearing_probe(inst, f"bearing_{cls_name}"))
        except Exception as e:
            entry["error"] = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-500:]}"
        rc[cls_name] = entry
    RESULTS["bearing_root_cause"] = rc
    return rc


def run_assembly_all(all_recs):
    named = []
    for i, r in enumerate(all_recs):
        sh = r.get("_shape")
        if sh is None:
            continue
        try:
            named.append((r["part"], sh.moved(cq.Location(cq.Vector(80 * i, 0, 0)))))
        except Exception:
            named.append((r["part"], sh))
    if not named:
        RESULTS["assembly_all_parts"] = "skipped: no shapes"
        return
    path = STEP_DIR / "all_parts.step"
    dt, err = assembly_export(named, path)
    rec = {"parts_in": len(named), "names_in": [n for n, _ in named],
           "export_seconds": dt, "export_error": err}
    if not err:
        rec.update(reimport_stats(path))
        rec["expected_names"] = [n for n, _ in named]
        rec["names_found"] = ((rec.get("xcaf") or {}).get("flat_names") or [])[:60]
        rec["names_survived_count"] = len(
            set(rec["expected_names"]) & set(rec["names_found"]))
    RESULTS["assembly_all_parts"] = rec


def run_tolerance_analysis(roundtrips):
    rows = []
    for rt in roundtrips:
        for key in ("roundtrip_a_shape_exportStep", "roundtrip_b_assembly"):
            sub = rt.get(key)
            if not isinstance(sub, dict):
                continue
            d = sub.get("deltas") or {}
            rows.append({
                "part": rt.get("part"), "path": key[-1],
                "volume_rel": d.get("volume_rel"),
                "area_rel": d.get("area_rel"),
                "bbox_abs_max_mm": d.get("bbox_abs_max_mm"),
                "faces_before_after": d.get("faces_before_after"),
                "solids_before_after": [
                    sub.get("solids_before"),
                    sub.get("solids_after")],
                "gate_pass": sub.get("gate_pass"),
            })
    good = [r for r in rows if r["gate_pass"] and r["volume_rel"] is not None]
    vals = sorted(r["volume_rel"] for r in good)
    RESULTS["tolerance_analysis"] = {
        "proposed_volume_rel_tol": VOLUME_REL_TOL,
        "proposed_bbox_abs_tol_mm": BBOX_ABS_TOL_MM,
        "rows": rows,
        "passing_volume_rel_deltas": vals,
        "max_passing_volume_rel": vals[-1] if vals else None,
        "note": ("max deviation among parts that pass the gate is the empirical "
                 "floor; the proposed tolerance must sit above it with margin"),
    }


def run_soma_comparison():
    soma_py = Path("soma-src/python")
    soma_py = soma_py if soma_py.exists() else Path("../soma-src/python")
    res = {}
    try:
        sys.path.insert(0, str(soma_py.resolve()))
        import soma.fasteners as sf
        res["loader"] = "package import"
    except Exception as e:
        res["loader"] = f"FAIL {e}"
        RESULTS["soma_comparison"] = res
        return
    for label, thunk in (
        ("SOMA Washer ISO 7089 M6", lambda: sf.Washer("ISO 7089", "M6", at=(0, 0, 0))),
        ("SOMA Washer ISO 7089 M10", lambda: sf.Washer("ISO 7089", "M10", at=(0, 0, 0))),
    ):
        ok, p, err = safe(thunk)
        if ok:
            ok2, st, err2 = safe(lambda: shape_stats(shape_of(p)))
            res[label] = st if ok2 else {"error": err2}
        else:
            res[label] = {"error": err}
    RESULTS["soma_comparison"] = res


# ---------------------------------------------------------------- main

def write_summary():
    """Compact markdown table written to phase21-sp1-summary.md"""
    L = []
    L.append("# Phase 2.1 SP1 geometry QA - auto summary")
    L.append("")
    e = RESULTS["env"]
    L.append(f"python {e.get('python')} | cadquery {e.get('cadquery')} | "
             f"cadquery-ocp {e.get('cadquery-ocp')} | cq-warehouse {e.get('cq-warehouse')} | "
             f"run {e.get('total_run_seconds')}s")
    L.append("")
    L.append("## Creation + validity")
    L.append("")
    L.append("| part | ok | s | solids | valid whole | all solids valid | volume mm3 | bbox mm |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in RESULTS["parts"]:
        b = r.get("before") or {}
        topo = b.get("topo") or {}
        L.append("| {p} | {ok} | {s} | {so} | {vw} | {av} | {v} | {bb} |".format(
            p=r["part"], ok=r.get("create_ok"), s=r.get("create_seconds"),
            so=topo.get("solids", "-"), vw=b.get("valid_whole", "-"),
            av=b.get("all_solids_valid", "-"), v=b.get("volume_mm3", "-"),
            bb=b.get("bbox_mm", "-")))
    L.append("")
    L.append("## STEP round-trip (A = Shape.exportStep, B = cq.Assembly named)")
    L.append("")
    L.append("| part | path | solids in->out | dV rel | dA rel | dBBox mm | faces in->out | valid after | gate | reasons |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for rt in RESULTS.get("roundtrips", []):
        if "skipped" in rt:
            L.append(f"| {rt['part']} | - | - | - | - | - | - | - | SKIP | {rt['skipped']} |")
            continue
        for key, lbl in (("roundtrip_a_shape_exportStep", "A"), ("roundtrip_b_assembly", "B")):
            sub = rt.get(key)
            if not isinstance(sub, dict):
                continue
            d = sub.get("deltas") or {}
            after = sub.get("after") or {}
            L.append("| {p} | {l} | {si}->{so} | {dv} | {da} | {db} | {f} | {v} | {g} | {rs} |".format(
                p=rt.get("part"), l=lbl, si=sub.get("solids_before", "?"),
                so=sub.get("solids_after", "?"), dv=d.get("volume_rel"),
                da=d.get("area_rel"), db=d.get("bbox_abs_max_mm"),
                f=d.get("faces_before_after"), v=after.get("all_solids_valid"),
                g=sub.get("gate_pass"), rs="; ".join(sub.get("gate_reasons") or [])))
    L.append("")
    L.append("## Washer root cause")
    L.append("")
    L.append("| washer | d1,d2,h mm | analytic V | measured V | ratio | valid | brepcheck errors |")
    L.append("|---|---|---|---|---|---|---|")
    for tag, w in RESULTS.get("washer_root_cause", {}).items():
        probe = w.get("probe") or {}
        bc = probe.get("brepcheck") or {}
        L.append("| {t} | {p} | {av} | {mv} | {r} | {v} | {e} |".format(
            t=tag, p=w.get("csv_params_mm"), av=w.get("analytic_volume_mm3"),
            mv=w.get("measured_volume_mm3"), r=w.get("measured_over_analytic"),
            v=(probe.get("make_washer_stats") or {}).get("valid_whole"),
            e=bc.get("status_counts")))
    L.append("")
    L.append("## Bearing root cause")
    L.append("")
    L.append("| bearing | size | fused solids | fused V | sum comps | sum/fused | solids after A | dV rel A | gate A | names survived B |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for name, b in RESULTS.get("bearing_root_cause", {}).items():
        a = b.get("roundtrip_fused_a") or {}
        bb = b.get("roundtrip_components_b") or {}
        L.append("| {n} | {s} | {fs} | {fv} | {sc} | {r} | {sa} | {dv} | {g} | {ns} |".format(
            n=name, s=b.get("size"), fs=b.get("fused_solids_count"),
            fv=(b.get("fused_stats") or {}).get("volume_mm3"),
            sc=b.get("sum_component_volumes_mm3"), r=b.get("sum_over_fused"),
            sa=a.get("solids_after"), dv=(a.get("deltas") or {}).get("volume_rel"),
            g=a.get("gate_pass"), ns=bb.get("names_survived")))
    ta = RESULTS.get("tolerance_analysis") or {}
    L.append("")
    L.append("## Tolerance")
    L.append("")
    L.append(f"proposed: volume rel <= {ta.get('proposed_volume_rel_tol')}, "
             f"bbox <= {ta.get('proposed_bbox_abs_tol_mm')} mm")
    L.append(f"max passing volume rel delta: {ta.get('max_passing_volume_rel')}")
    L.append(f"passing deltas: {ta.get('passing_volume_rel_deltas')}")
    Path("phase21-sp1-summary.md").write_text("\n".join(L), encoding="utf-8")


def main():
    t_start = time.perf_counter()
    env_info()
    dump_sources()

    (screw, nut, washer_recs, hs_recs, bearing_recs,
     th_simple, th_threaded, sprocket) = run_parts()

    all_recs = [r for r in RESULTS["parts"] if r.get("_shape") is not None]
    # IsoThread simple=True intentionally has no solid: record explicitly
    for r in RESULTS["parts"]:
        if "simple=True" in r["part"] and r.get("class") == "IsoThread":
            r["no_geometry_by_design"] = (
                "IsoThread(simple=True) sets self.wrapped = TopoDS_Shape() "
                "(null shape) - calculation-only object, cannot be exported; "
                "see source citation cq_warehouse.thread.IsoThread.__init__")

    def step(label, fn):
        try:
            return fn()
        except Exception as e:
            RESULTS.setdefault("section_errors", {})[label] = (
                f"{type(e).__name__}: {e}\n{traceback.format_exc()[-600:]}")
            print(f"SECTION FAIL {label}: {type(e).__name__}: {e}")
            return None

    roundtrips = step("roundtrips", lambda: run_roundtrips(all_recs)) or []
    step("washer_root_cause", lambda: run_washer_root_cause(washer_recs))
    step("bearing_root_cause", lambda: run_bearing_root_cause(bearing_recs))
    step("assembly_all", lambda: run_assembly_all(all_recs))
    step("tolerance", lambda: run_tolerance_analysis(roundtrips))
    step("soma_comparison", run_soma_comparison)

    RESULTS["env"]["total_run_seconds"] = round(time.perf_counter() - t_start, 2)

    # scrub private keys before serialization
    for r in RESULTS["parts"]:
        r.pop("_shape", None)
        r.pop("_obj", None)

    Path("phase21-sp1-results.json").write_text(
        json.dumps(RESULTS, indent=2, default=str), encoding="utf-8")

    # sources as standalone text for easy citation reading
    lines = []
    for label, c in RESULTS["source_citations"].items():
        if "file" in c:
            lines.append(f"===== {label} @ {c['file']}:{c['line_start']}-{c['line_end']} =====")
            lines.append(c.get("source", ""))
        else:
            lines.append(f"===== {label} ===== {c}")
    Path("phase21-sp1-sources.txt").write_text("\n".join(lines), encoding="utf-8")

    write_summary()

    print(f"\n## Done in {RESULTS['env']['total_run_seconds']}s - "
          f"results written to phase21-sp1-results.json")


if __name__ == "__main__":
    main()
