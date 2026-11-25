#!/usr/bin/env python3
"""Verify the installed stack against the exact pins and record provenance.

Writes sp3-install.json:
  * importlib.metadata versions of cadquery / cadquery-ocp / cadquery-ocp-proxy /
    cq-warehouse (+ multimethod, ezdxf, numpy)
  * direct_url.json of the cq-warehouse distribution (pip's record of where the
    package came from, including the VCS commit id for git+https installs)
  * whether the recorded commit equals the pinned commit a307044f... (tag v0.8.0)

Usage: python sp3_verify_install.py --method <git+https|archive> [--out FILE]
Exit code 0 always (verification outcome is reported in the JSON + stdout);
the workflow prints the JSON either way.
"""
import argparse
import importlib.metadata as md
import json
import re
from pathlib import Path

PIN_SHA = "a307044f91c9cc5433fde92cb1fa145c01b2bde7"
EXPECT = {
    "cadquery": "2.8.0",
    "cadquery-ocp": "7.9.3.1.1",
    "cadquery-ocp-proxy": "7.9.3.1.1",
    "cq-warehouse": "0.8.0",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", default="unknown")
    ap.add_argument("--out", default="sp3-install.json")
    args = ap.parse_args()

    res = {"method": args.method, "expected_versions": EXPECT,
           "expected_commit": PIN_SHA, "versions": {}}
    all_ok = True
    for pkg, want in EXPECT.items():
        try:
            got = md.version(pkg)
        except Exception as e:
            got = f"NOT INSTALLED ({type(e).__name__}: {e})"
        res["versions"][pkg] = {"expected": want, "installed": got,
                                "match": got == want}
        if got != want:
            all_ok = False
    for pkg in ("multimethod", "ezdxf", "numpy", "cadquery-proxy"):
        try:
            res["versions"][pkg] = {"installed": md.version(pkg)}
        except Exception:
            pass

    # provenance: direct_url.json is written by pip into the dist-info directory
    try:
        dist = md.distribution("cq-warehouse")
        info_dir = None
        for f in dist.files or []:
            if str(f).endswith("direct_url.json"):
                info_dir = Path(dist.locate_file(f)).parent
                break
        if info_dir is not None:
            raw = json.loads((info_dir / "direct_url.json").read_text(encoding="utf-8"))
            res["direct_url"] = raw
            commit = (raw.get("vcs_info") or {}).get("commit_id")
            if commit is None:
                # archive installs: the exact commit SHA is part of the source URL
                m = re.search(r"/([0-9a-f]{40})(?:\.tar\.gz)?", raw.get("url", ""))
                commit = m.group(1) if m else None
            res["recorded_commit"] = commit
            res["commit_matches_pin"] = commit == PIN_SHA
            if res["commit_matches_pin"] is False:
                all_ok = False
        else:
            res["direct_url"] = "direct_url.json not found in dist-info"
            res["commit_matches_pin"] = None
    except Exception as e:
        res["direct_url"] = f"FAIL {type(e).__name__}: {e}"
        res["commit_matches_pin"] = None

    res["all_pins_verified"] = all_ok and res.get("commit_matches_pin") is True
    Path(args.out).write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    print(json.dumps(res, indent=2, default=str))


if __name__ == "__main__":
    main()
