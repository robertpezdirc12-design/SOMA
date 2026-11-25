#!/usr/bin/env python3
"""Phase 21 / Specialist 3 (Windows compatibility): compact cq_warehouse 0.8.0
geometry suite for the SOMA pinned stack (cadquery 2.8.0, cadquery-ocp 7.9.3.1.1).

Runs only on GitHub-hosted runners (windows-latest / ubuntu-latest) through a
temporary workflow on fork branch test/phase21-windows. Evidence gathering only:
nothing here integrates cq_warehouse into SOMA.

The part-selection helpers (pick_type / first_sizes / try_variants) are copied
verbatim from the accepted Phase 2 POC (poc/phase2_poc.py) so the created
variants match the Linux baseline results/phase2-results.json exactly.

For every part:
  * creation success + wall time
  * isValid() of the whole shape and of every solid
  * solid count before and after a STEP export + re-import
  * volume / area / bounding box before and after, with relative deltas
  * round-trip verdict (0 bodies after re-import = FAIL)

Writes the results JSON and prints a summary table.
"""
import argparse
import importlib.metadata as md
import inspect
import json
import os
import platform
import sys
import time
from pathlib import Path

# --- accepted Linux baseline: Phase 2 POC, ubuntu-latest (run 45709469808) -------
# Values as recorded in results/phase2-results.json (volume/bbox rounded to 3
# decimals there, so cross-platform comparison against it has a ~1e-6 floor;
# the same-script linux job in this workflow provides full-precision comparison).
BASELINE = {
    "source": "results/phase2-results.json (Phase 2 POC, ubuntu-latest, run 45709469808)",
    "env": {
        "python": "3.12.16",
        "cadquery": "2.8.0",
        "cadquery-ocp": "7.9.3.1.1",
        "cadquery-ocp-proxy": "7.9.3.1.1",
        "cq-warehouse": "0.8.0",
    },
    "parts": {
        "screw": {"variant": "SocketHeadCapScrew(M6-1, 20.0)", "volume_mm3": 805.724,
                  "bbox_mm": [10.22, 10.22, 26.0], "valid": True},
        "nut": {"variant": "HexNut(M6-1, None)", "volume_mm3": 302.298,
                "bbox_mm": [11.545, 10.0, 5.2], "valid": True},
        "washer": {"variant": "direct", "volume_mm3": 291.339,
                   "bbox_mm": [12.0, 12.0, 1.8], "valid": False},
        "heatset": {"variant": "direct", "volume_mm3": 97.053,
                    "bbox_mm": [8.0, 8.0, 10.0], "valid": True},
        "bearing": {"variant": "direct", "volume_mm3": 253.382,
                    "bbox_mm": [13.0, 13.0, 3.5], "valid": True},
        "thread_real": {"variant": "M6x10 threaded", "volume_mm3": 38.017,
                        "bbox_mm": [6.0, 6.0, 9.875], "valid": True},
        "sprocket": {"variant": "18 teeth", "volume_mm3": 8341.642,
                     "bbox_mm": [77.105, 76.531, 2.134], "valid": True},
    },
    "roundtrip_rel_delta_volume": {
        "screw": 1.03e-13, "nut": 1.45e-11, "washer": 1.00,
        "heatset": 2.88e-05, "bearing": 9.79e-02,
    },
}

RESULTS = {
    "suite": "phase21-sp3-windows-geometry",
    "os_tag": None,
    "env": {},
    "attempts": {},
    "parts": {},
    "roundtrip": {},
    "baseline_comparison": {},
    "verdict": {},
}

PIN_SHA = "a307044f91c9cc5433fde92cb1fa145c01b2bde7"
PIN_URL = f"git+https://github.com/gumyr/cq_warehouse.git@{PIN_SHA}"


# --- helpers copied verbatim from poc/phase2_poc.py -------------------------------

def pick_type(cls, prefer=("iso", "din")):
    """Prefer metric ISO/DIN fastener types (sets sort imperial 'asme' first)."""
    types = sorted(cls.types())
    for p in prefer:
        for t in types:
            if p in t.lower():
                return t, types
    return (types[0] if types else None), types


def first_sizes(cls, fastener_type, prefer="M6"):
    sizes = sorted(cls.sizes(fastener_type))
    for s in sizes:
        if s.startswith(prefer):
            return s, sizes
    for s in sizes:
        if s.startswith("M"):
            return s, sizes
    return (sizes[0] if sizes else None), sizes


def try_variants(name, variants):
    """Try (label, callable) variants; record every attempt, return the first success."""
    RESULTS["attempts"].setdefault(name, [])
    for label, thunk in variants:
        t0 = time.perf_counter()
        try:
            out = thunk()
            dt = round(time.perf_counter() - t0, 4)
            RESULTS["attempts"][name].append({"variant": label, "ok": True, "seconds": dt})
            print(f"OK   {name} [{label}] {dt}s")
            return out
        except Exception as e:
            dt = round(time.perf_counter() - t0, 4)
            RESULTS["attempts"][name].append(
                {"variant": label, "ok": False, "seconds": dt,
                 "error": f"{type(e).__name__}: {e}"})
            print(f"FAIL {name} [{label}] {type(e).__name__}: {e}")
    return None


# --- measurement -------------------------------------------------------------------

def shape_of(obj):
    return obj.val() if hasattr(obj, "val") else obj


def part_stats(obj):
    """volume / area / bbox / validity of the whole shape and of every solid."""
    sh = shape_of(obj)
    out = {}
    try:
        out["solids"] = len(sh.Solids())
    except Exception as e:
        out["solids"] = None
        out["solids_error"] = f"{type(e).__name__}: {e}"
    try:
        out["solid_valid"] = [bool(s.isValid()) for s in sh.Solids()]
    except Exception as e:
        out["solid_valid"] = None
    try:
        out["valid"] = bool(sh.isValid())
    except Exception as e:
        out["valid"] = None
        out["valid_error"] = f"{type(e).__name__}: {e}"
    try:
        out["volume_mm3"] = float(sh.Volume())
    except Exception as e:
        out["volume_mm3"] = None
        out["volume_error"] = f"{type(e).__name__}: {e}"
    try:
        out["area_mm2"] = float(sh.Area())
    except Exception as e:
        out["area_mm2"] = None
        out["area_error"] = f"{type(e).__name__}: {e}"
    try:
        bb = sh.BoundingBox()
        out["bbox_mm"] = [float(bb.xlen), float(bb.ylen), float(bb.zlen)]
    except Exception as e:
        out["bbox_mm"] = None
        out["bbox_error"] = f"{type(e).__name__}: {e}"
    return out


def rel_delta(a, b):
    if a is None or b is None or a == 0:
        return None
    return abs(b - a) / abs(a)


# --- environment -------------------------------------------------------------------

def env_info():
    e = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "executable": sys.executable,
    }
    for pkg in ("cadquery", "cadquery-ocp", "cadquery-ocp-proxy", "cq-warehouse",
                "multimethod", "ezdxf", "numpy"):
        try:
            e[pkg] = md.version(pkg)
        except Exception:
            e[pkg] = "not installed"
    # provenance of the cq_warehouse install (written by sp3_verify_install.py)
    install_file = Path(os.environ.get("SP3_INSTALL_JSON", "sp3-install.json"))
    if install_file.is_file():
        try:
            e["install"] = json.loads(install_file.read_text(encoding="utf-8"))
        except Exception as ex:
            e["install"] = f"unreadable: {ex}"
    else:
        e["install"] = "sp3-install.json not found"
    RESULTS["env"] = e
    print("## Environment")
    print(json.dumps(e, indent=2))

    # pin checks
    v = RESULTS["verdict"]
    v["versions_match_pins"] = (
        e["cadquery"] == "2.8.0"
        and e["cadquery-ocp"] == "7.9.3.1.1"
        and e["cadquery-ocp-proxy"] == "7.9.3.1.1"
        and e["cq-warehouse"] == "0.8.0"
    )
    v["cq_warehouse_commit_pinned"] = None
    inst = e.get("install")
    if isinstance(inst, dict):
        v["cq_warehouse_commit_pinned"] = inst.get("commit_matches_pin")
        v["install_method"] = inst.get("method")


# --- creation ----------------------------------------------------------------------

def creation_tests():
    from cq_warehouse.fastener import SocketHeadCapScrew, HexNut, PlainWasher, HeatSetNut
    from cq_warehouse.bearing import SingleRowDeepGrooveBallBearing

    parts = {}

    def record(name, obj):
        if obj is None:
            RESULTS["parts"][name] = {"ok": False}
            return
        rec = {"ok": True, "seconds": RESULTS["attempts"][name][-1]["seconds"]}
        rec.update(part_stats(obj))
        RESULTS["parts"][name] = rec
        parts[name] = obj

    # 1. SocketHeadCapScrew iso4762 M6-1 x 20 (brief spec; matches baseline variant)
    screw = try_variants("screw", [
        ("SocketHeadCapScrew(size='M6-1', length=20.0, fastener_type='iso4762', simple=True)",
         lambda: SocketHeadCapScrew(size="M6-1", length=20.0,
                                    fastener_type="iso4762", simple=True)),
    ])
    record("screw", screw)

    # 2. HexNut iso4032 M6-1 (brief spec; matches baseline variant)
    nut = try_variants("nut", [
        ("HexNut(size='M6-1', fastener_type='iso4032', simple=True)",
         lambda: HexNut(size="M6-1", fastener_type="iso4032", simple=True)),
    ])
    record("nut", nut)

    # 3. PlainWasher iso7089 'M6-1' (brief spec) -> the brief's size string is
    #    size-pitch notation; Washer sizes are plain 'M6' (float(size[1:]) in
    #    Washer.__init__). Try the brief spec first and document the outcome.
    wash_cls = PlainWasher
    t_wash, wash_types = pick_type(wash_cls)
    size_wash, wash_sizes = first_sizes(wash_cls, t_wash)
    RESULTS["attempts"]["washer_meta"] = {"types": wash_types,
                                          "sizes_sample": wash_sizes[:10],
                                          "first_sizes_pick": size_wash}
    washer = try_variants("washer", [
        ("PlainWasher(size='M6-1', fastener_type='iso7089')  [brief spec]",
         lambda: PlainWasher(size="M6-1", fastener_type="iso7089")),
        ("PlainWasher(size='M6', fastener_type='iso7089')",
         lambda: PlainWasher(size="M6", fastener_type="iso7089")),
        ("PlainWasher(size=first_sizes_pick, fastener_type='iso7089')",
         lambda: PlainWasher(size=size_wash, fastener_type="iso7089")),
    ])
    record("washer", washer)

    # 4. HeatSetNut (brief gives no spec: replicate baseline pick_type/first_sizes)
    hs_cls = HeatSetNut
    t_hs, hs_types = pick_type(hs_cls)
    size_hs, hs_sizes = first_sizes(hs_cls, t_hs)
    RESULTS["attempts"]["heatset_meta"] = {"types": hs_types,
                                           "sizes_sample": hs_sizes[:10],
                                           "picked_type": t_hs, "picked_size": size_hs}
    hs = try_variants("heatset", [
        (f"HeatSetNut(size={size_hs!r}, fastener_type={t_hs!r}, simple=True)",
         lambda: HeatSetNut(size=size_hs, fastener_type=t_hs, simple=True)),
    ])
    record("heatset", hs)

    # 5. Bearing: baseline-comparable pick (SKT type, first size starting 'M6')
    #    AND the smallest bearing of the type (brief: "one bearing (smallest)").
    b_cls = SingleRowDeepGrooveBallBearing
    b_types = sorted(b_cls.types())
    t_b = b_types[0]
    size_b, b_sizes = first_sizes(b_cls, t_b, prefer="M6")
    if not str(size_b).startswith("M"):
        size_b = next((s for s in b_sizes if s.startswith("M")), size_b)

    def size_key(s):
        # sizes are 'M<bore>-<OD>-<width>'; fall back to the raw string
        try:
            parts_ = [float(x) for x in str(s).lstrip("M").split("-")]
            return (0, tuple(parts_))
        except ValueError:
            return (1, str(s))

    size_smallest = min(b_sizes, key=size_key) if b_sizes else size_b
    RESULTS["attempts"]["bearing_meta"] = {
        "types": b_types, "sizes_count": len(b_sizes), "sizes_sample": b_sizes[:10],
        "baseline_pick_type": t_b, "baseline_pick_size": size_b,
        "smallest_size": size_smallest,
        "smallest_rule": "min by (bore, OD, width) parsed from 'M<bore>-<OD>-<width>'",
    }
    bearing = try_variants("bearing", [
        (f"SingleRowDeepGrooveBallBearing(size={size_b!r}, bearing_type={t_b!r})  [baseline pick]",
         lambda: SingleRowDeepGrooveBallBearing(size=size_b, bearing_type=t_b)),
    ])
    record("bearing", bearing)
    if size_smallest != size_b:
        bearing_s = try_variants("bearing_smallest", [
            (f"SingleRowDeepGrooveBallBearing(size={size_smallest!r}, bearing_type={t_b!r})  [smallest]",
             lambda: SingleRowDeepGrooveBallBearing(size=size_smallest, bearing_type=t_b)),
        ])
        record("bearing_smallest", bearing_s)

    return parts


def thread_tests():
    from cq_warehouse.thread import IsoThread
    parts = {}
    th = try_variants("thread_simple", [
        ("IsoThread(major_diameter=6.0, pitch=1.0, length=10.0, external=True, simple=True)",
         lambda: IsoThread(major_diameter=6.0, pitch=1.0, length=10.0,
                           external=True, simple=True)),
    ])
    if th is not None:
        rec = {"ok": True, "seconds": RESULTS["attempts"]["thread_simple"][-1]["seconds"]}
        rec.update(part_stats(th))
        RESULTS["parts"]["thread_simple"] = rec

    th2 = try_variants("thread_real", [
        ("IsoThread(major_diameter=6.0, pitch=1.0, length=10.0, external=True, simple=False)",
         lambda: IsoThread(major_diameter=6.0, pitch=1.0, length=10.0,
                           external=True, simple=False)),
    ])
    if th2 is not None:
        rec = {"ok": True, "seconds": RESULTS["attempts"]["thread_real"][-1]["seconds"]}
        rec.update(part_stats(th2))
        RESULTS["parts"]["thread_real"] = rec
        parts["thread_real"] = th2
    return parts


def sprocket_test():
    from cq_warehouse.sprocket import Sprocket
    sp = try_variants("sprocket", [
        ("Sprocket(num_teeth=18)  [bicycle-chain defaults]",
         lambda: Sprocket(num_teeth=18)),
    ])
    if sp is not None:
        rec = {"ok": True, "seconds": RESULTS["attempts"]["sprocket"][-1]["seconds"]}
        rec.update(part_stats(sp))
        RESULTS["parts"]["sprocket"] = rec
        return sp
    return None


# --- STEP round trip ----------------------------------------------------------------

def roundtrip_parts(parts):
    import cadquery as cq
    for name, obj in parts.items():
        sh = shape_of(obj)
        before = part_stats(sh)
        rec = {"before": before}
        step = f"sp3_rt_{name}.step"
        try:
            a = cq.Assembly()
            a.add(sh, name=name, color=cq.Color(0.8, 0.8, 0.8, 1.0))
            exporter = a.export if hasattr(a, "export") else a.save
            t0 = time.perf_counter()
            exporter(step)
            rec["export_seconds"] = round(time.perf_counter() - t0, 3)
            rec["step_bytes"] = os.path.getsize(step)
            t0 = time.perf_counter()
            wp = cq.importers.importStep(step)
            rec["import_seconds"] = round(time.perf_counter() - t0, 3)
            solids = wp.solids().vals()
            after = part_stats(wp.val())
            rec["after"] = after
            rec["solids_before"] = before.get("solids")
            rec["solids_out"] = len(solids)
            rec["solid_valid_after"] = [bool(s.isValid()) for s in solids]
            rec["roundtrip_pass"] = len(solids) > 0
            if not rec["roundtrip_pass"]:
                rec["fail_reason"] = "0 bodies after STEP re-import"
            rec["rel_delta_volume"] = rel_delta(before.get("volume_mm3"),
                                                after.get("volume_mm3"))
            rec["rel_delta_area"] = rel_delta(before.get("area_mm2"),
                                              after.get("area_mm2"))
            b0, b1 = before.get("bbox_mm"), after.get("bbox_mm")
            rec["rel_delta_bbox"] = (
                [rel_delta(x, y) for x, y in zip(b0, b1)]
                if b0 and b1 else None)
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"
            rec["roundtrip_pass"] = False
        RESULTS["roundtrip"][name] = rec
        v = "PASS" if rec.get("roundtrip_pass") else "FAIL"
        print(f"{v:4} STEP round-trip {name}: solids {rec.get('solids_before')}->"
              f"{rec.get('solids_out')}, rel dV={rec.get('rel_delta_volume')}")


# --- baseline comparison ------------------------------------------------------------

def baseline_compare():
    cmp_ = {}
    for name, base in BASELINE["parts"].items():
        got = RESULTS["parts"].get(name, {})
        entry = {"baseline": base, "this_run": {
            k: got.get(k) for k in ("volume_mm3", "bbox_mm", "valid", "solids")}}
        v = got.get("volume_mm3")
        entry["volume_rel_diff_vs_baseline"] = rel_delta(base["volume_mm3"], v)
        b0, b1 = base.get("bbox_mm"), got.get("bbox_mm")
        entry["bbox_rel_diff_vs_baseline"] = (
            [rel_delta(x, y) for x, y in zip(b0, b1)] if b0 and b1 else None)
        entry["valid_matches_baseline"] = got.get("valid") == base.get("valid")
        rt = RESULTS["roundtrip"].get(name, {})
        entry["roundtrip_rel_delta_volume"] = rt.get("rel_delta_volume")
        entry["baseline_roundtrip_rel_delta_volume"] = \
            BASELINE["roundtrip_rel_delta_volume"].get(name)
        cmp_[name] = entry
    RESULTS["baseline_comparison"] = cmp_
    print("## Baseline comparison (values in baseline rounded to 3 decimals)")
    for name, e in cmp_.items():
        print(f"  {name:12} dV={e['volume_rel_diff_vs_baseline']}  "
              f"valid_match={e['valid_matches_baseline']}")


# --- main ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="sp3-results.json")
    ap.add_argument("--os-tag", default=None)
    args = ap.parse_args()
    RESULTS["os_tag"] = args.os_tag or ("windows" if os.name == "nt" else "posix")

    t_start = time.perf_counter()
    env_info()

    t0 = time.perf_counter()
    import cadquery  # noqa: F401
    RESULTS["env"]["import_cadquery_seconds"] = round(time.perf_counter() - t0, 3)
    t0 = time.perf_counter()
    import cq_warehouse.fastener  # noqa: F401
    RESULTS["env"]["import_cq_warehouse_fastener_seconds"] = round(
        time.perf_counter() - t0, 3)

    parts = creation_tests()
    parts.update(thread_tests())
    sp = sprocket_test()
    if sp is not None:
        parts["sprocket"] = sp

    roundtrip_parts(parts)
    baseline_compare()

    RESULTS["env"]["total_run_seconds"] = round(time.perf_counter() - t_start, 2)

    n_ok = sum(1 for p in RESULTS["parts"].values() if p.get("ok"))
    n_fail = len(RESULTS["parts"]) - n_ok
    rt_fail = [k for k, r in RESULTS["roundtrip"].items() if not r.get("roundtrip_pass")]
    RESULTS["verdict"].update({
        "created_ok": n_ok,
        "created_failed": n_fail,
        "roundtrip_fail_parts": rt_fail,
        "suite_passed": n_fail == 0 and RESULTS["verdict"].get("versions_match_pins"),
    })
    print(f"\n## Summary: {n_ok} created, {n_fail} failed, "
          f"round-trip failures: {rt_fail or 'none'}, "
          f"run {RESULTS['env']['total_run_seconds']}s")

    Path(args.out).write_text(json.dumps(RESULTS, indent=2, default=str),
                              encoding="utf-8")
    print(f"results written to {args.out}")


if __name__ == "__main__":
    main()
