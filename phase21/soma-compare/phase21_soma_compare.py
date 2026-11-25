"""Phase 2.1 Test B - direct SOMA vs cq_warehouse comparison (M6x20 screw, ISO 7089 M6 washer).

Runs on a throwaway GitHub-hosted runner under SOMA's pinned stack. Evidence only; no
integration code. Questions answered:
  1. Where does the 18.1% volume difference of the M6x20 socket-head screw come from
     (head, socket, shank, thread, under-head details)?
  2. Do the measured M6 washer dimensions match ISO 7089 nominal values, and do the two
     libraries' parameter tables agree?
"""
import json
import math
import sys
import time
import traceback
from pathlib import Path

RESULTS = {"test": "phase2.1-test-b-soma-comparison"}
STEP = 0.25  # mm z-resolution of the cross-section profile


def sh_of(part):
    sh = part.shape if hasattr(part, "shape") else part
    return sh.val() if hasattr(sh, "val") else sh


def stats(sh):
    bb = sh.BoundingBox()
    return {
        "volume_mm3": round(sh.Volume(), 4),
        "area_mm2": round(sh.Area(), 4),
        "faces": len(sh.Faces()),
        "solids": len(sh.Solids()),
        "valid": bool(sh.isValid()),
        "bbox_mm": [round(bb.xmin, 3), round(bb.xmax, 3), round(bb.ymin, 3),
                    round(bb.ymax, 3), round(bb.zmin, 3), round(bb.zmax, 3)],
    }


def slab_volume(sh, z0, z1):
    """Volume of the solid between planes z0 and z1 (axis = Z)."""
    import cadquery as cq
    bb = sh.BoundingBox()
    x, y = (bb.xmin + bb.xmax) / 2, (bb.ymin + bb.ymax) / 2
    w = (bb.xlen + bb.ylen)  # generous
    slab = cq.Workplane().box(w, w, (z1 - z0), centered=(True, True, False)).translate((x, y, z0))
    return sh.intersect(slab.val()).Volume()


def z_profile(sh, step=STEP):
    bb = sh.BoundingBox()
    z0, z1 = bb.zmin, bb.zmax
    out = []
    z = z0
    while z < z1 - 1e-9:
        ze = min(z + step, z1)
        try:
            v = slab_volume(sh, z, ze)
        except Exception:
            v = None
        out.append([round(z, 3), round(ze, 3), None if v is None else round(v / (ze - z), 3)])
        z = ze
    return out


def csv_row(path, size="M6"):
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        head = lines[0].split(",")
        for ln in lines[1:]:
            if ln.split(",")[0] == size:
                return dict(zip(head, ln.split(",")))
        return {"error": f"row {size} not found"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def screw_decomposition(label, sh):
    st = stats(sh)
    bb = sh.BoundingBox()
    z0, z1 = bb.zmin, bb.zmax
    total = sh.Volume()
    prof = z_profile(sh)
    # head end = the side whose first slabs have the larger area
    area_first = prof[0][2] or 0
    area_last = prof[-1][2] or 0
    head_at_bottom = area_first > area_last
    k_nom = 6.0  # ISO 4762 M6 head height (max)
    if head_at_bottom:
        head_v = slab_volume(sh, z0, z0 + k_nom)
        shank_v = slab_volume(sh, z0 + k_nom, z1)
        head_len, shank_len = k_nom, z1 - (z0 + k_nom)
    else:
        head_v = slab_volume(sh, z1 - k_nom, z1)
        shank_v = slab_volume(sh, z0, z1 - k_nom)
        head_len, shank_len = k_nom, (z1 - k_nom) - z0
    d_eq_head = math.sqrt(4 * head_v / (math.pi * head_len))
    d_eq_shank = math.sqrt(4 * shank_v / (math.pi * shank_len)) if shank_len > 0 else None
    # analytic references (ISO 4762 M6: dk=10 max, k=6 max, s=5, P=1)
    head_cyl = math.pi / 4 * 10.0 ** 2 * 6.0
    shank_cyl = math.pi / 4 * 6.0 ** 2 * shank_len
    d3 = 6.0 - 1.226869 * 1.0  # external thread minor dia (ISO 68 basic profile, P=1)
    shank_minor_cyl = math.pi / 4 * d3 ** 2 * shank_len
    return {
        "label": label,
        "stats": st,
        "head_at_bottom": head_at_bottom,
        "head_volume_mm3": round(head_v, 4),
        "shank_volume_mm3": round(shank_v, 4),
        "head_len_mm": round(head_len, 3),
        "shank_len_mm": round(shank_len, 3),
        "head_equivalent_diameter_mm": round(d_eq_head, 4),
        "shank_equivalent_diameter_mm": None if d_eq_shank is None else round(d_eq_shank, 4),
        "head_analytic_cylinder_d10_k6_mm3": round(head_cyl, 4),
        "head_void_vs_cylinder_mm3": round(head_cyl - head_v, 4),
        "shank_analytic_plain_d6_mm3": round(shank_cyl, 4),
        "shank_analytic_minor_d4773_mm3": round(shank_minor_cyl, 4),
        "z_profile": prof,
    }


def washer_decomposition(label, sh):
    st = stats(sh)
    bb = sh.BoundingBox()
    d2 = (bb.xlen + bb.ylen) / 2
    h = bb.zlen
    v = sh.Volume()
    d1 = math.sqrt(max(d2 ** 2 - 4 * v / (math.pi * h), 0.0))
    return {
        "label": label,
        "stats": st,
        "derived_d1_mm": round(d1, 4),
        "derived_d2_mm": round(d2, 4),
        "derived_h_mm": round(h, 4),
        "analytic_volume_from_derived_mm3": round(math.pi / 4 * (d2 ** 2 - d1 ** 2) * h, 4),
    }


def main():
    import cadquery as cq  # noqa
    soma_py = Path("soma-src/python")
    sys.path.insert(0, str(soma_py.resolve()))
    import soma.fasteners as sf

    from cq_warehouse.fastener import SocketHeadCapScrew, PlainWasher

    # ---- build parts ----
    parts = {}
    t0 = time.perf_counter()
    soma_screw = sf.Screw("ISO 4762", "M6", 20, at=(0, 0, 0))
    parts["soma_screw_s"] = round(time.perf_counter() - t0, 3)
    t0 = time.perf_counter()
    soma_washer = sf.Washer("ISO 7089", "M6", at=(0, 0, 0))
    parts["soma_washer_s"] = round(time.perf_counter() - t0, 3)

    # cq_warehouse: discover the exact size/type strings like the Phase 2 POC did
    import inspect

    def make(cls, **kw):
        params = inspect.signature(cls.__init__).parameters
        if "simple" in params:
            kw["simple"] = False
        return cls(**kw)

    screw_types = sorted(SocketHeadCapScrew.types())
    screw_type = next((t for t in screw_types if "iso4762" in t.lower()), screw_types[0])
    screw_sizes = sorted(SocketHeadCapScrew.sizes(screw_type))
    screw_size = next((s for s in screw_sizes if s.startswith("M6")), screw_sizes[0])
    t0 = time.perf_counter()
    cq_screw = make(SocketHeadCapScrew, size=screw_size, length=20.0,
                    fastener_type=screw_type)
    parts["cq_screw_s"] = round(time.perf_counter() - t0, 3)

    wash_types = sorted(PlainWasher.types())
    wash_type = next((t for t in wash_types if "iso7089" in t.lower()), wash_types[0])
    wash_sizes = sorted(PlainWasher.sizes(wash_type))
    wash_size = next((s for s in wash_sizes if s.startswith("M6")), wash_sizes[0])
    t0 = time.perf_counter()
    cq_washer = make(PlainWasher, size=wash_size, fastener_type=wash_type)
    parts["cq_washer_s"] = round(time.perf_counter() - t0, 3)

    RESULTS["creation"] = parts
    RESULTS["size_strings"] = {
        "cq_screw_type": screw_type, "cq_screw_size": screw_size,
        "cq_washer_type": wash_type, "cq_washer_size": wash_size,
        "soma_screw": 'Screw("ISO 4762", "M6", 20)', "soma_washer": 'Washer("ISO 7089", "M6")',
    }

    # ---- parameter tables ----
    import importlib.metadata as md
    cqw_path = Path(md.distribution("cq_warehouse").locate_file("cq_warehouse"))
    soma_data = soma_py / "soma" / "data" / "fasteners"
    RESULTS["csv"] = {
        "soma_socket_head_cap_M6": csv_row(soma_data / "socket_head_cap_parameters.csv"),
        "cq_socket_head_cap_M6": csv_row(cqw_path / "socket_head_cap_parameters.csv"),
        "soma_plain_washer_M6": csv_row(soma_data / "plain_washer_parameters.csv"),
        "cq_plain_washer_M6": csv_row(cqw_path / "plain_washer_parameters.csv"),
    }

    # ---- screw comparison / decomposition ----
    RESULTS["screw"] = {
        "soma": screw_decomposition("SOMA Screw ISO 4762 M6x20", sh_of(soma_screw)),
        "cq_warehouse": screw_decomposition("cq SocketHeadCapScrew M6-1x20", sh_of(cq_screw)),
    }
    sv = RESULTS["screw"]["soma"]["stats"]["volume_mm3"]
    cv = RESULTS["screw"]["cq_warehouse"]["stats"]["volume_mm3"]
    RESULTS["screw"]["comparison"] = {
        "volume_ratio_cq_over_soma": round(cv / sv, 6),
        "volume_diff_mm3": round(cv - sv, 4),
        "head_diff_mm3": round(RESULTS["screw"]["cq_warehouse"]["head_volume_mm3"]
                               - RESULTS["screw"]["soma"]["head_volume_mm3"], 4),
        "shank_diff_mm3": round(RESULTS["screw"]["cq_warehouse"]["shank_volume_mm3"]
                                - RESULTS["screw"]["soma"]["shank_volume_mm3"], 4),
    }

    # ---- washer comparison / decomposition ----
    RESULTS["washer"] = {
        "soma": washer_decomposition("SOMA Washer ISO 7089 M6", sh_of(soma_washer)),
        "cq_warehouse": washer_decomposition("cq PlainWasher iso7089 M6", sh_of(cq_washer)),
        "iso7089_nominal": {"d1_min_mm": 6.4, "d2_max_mm": 12.0, "h_nom_mm": 1.6},
    }

    Path("phase21-compare-results.json").write_text(
        json.dumps(RESULTS, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(RESULTS, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        RESULTS["fatal"] = traceback.format_exc()
        Path("phase21-compare-results.json").write_text(
            json.dumps(RESULTS, indent=1, ensure_ascii=False), encoding="utf-8")
        sys.exit(1)
