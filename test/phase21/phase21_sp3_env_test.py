#!/usr/bin/env python3
"""Phase 21 / Specialist 3 (bonus): exercise SOMA's project-environment mechanism
(python/soma/env.py) on Windows.

Evidence only. Runs on a GitHub-hosted windows-latest runner against the pinned
SOMA sources (robertpezdirc8-prog/SOMA @ cf8e629ef0dc1c2c54ee3fb62d50a208aa938c27).

What this checks (the Windows-specific parts of the mechanism):
  1. env.ensure(project) creates <project>/.soma/env; on Windows the venv must
     contain Scripts\\python.exe (packages.ts builds the same path: WIN?'Scripts':'bin').
  2. env.py writes pip.ini (not pip.conf) with the base-constraints file:// URL,
     _soma_base.pth attaching the base site-packages, base-constraints.txt and
     soma-env.json - all with Windows path conventions.
  3. Installing the cq_warehouse commit pin through the app's terminal flow
     (PIP_PYTHON=<env>\\Scripts\\python.exe) lands the package in the project
     environment, not in the base runtime, and it imports from there.
  4. env.activate() makes the package visible to the base interpreter.
  5. Robustness probe: same flow for a project path containing a space
     (typical on Windows: C:\\Users\\First Last\\...).

Writes sp3-env-results.json and prints a summary.
"""
import argparse
import json
import os
import platform
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PIN_SHA = "a307044f91c9cc5433fde92cb1fa145c01b2bde7"
PIN_URL = f"git+https://github.com/gumyr/cq_warehouse.git@{PIN_SHA}"
ARCHIVE_URL = f"https://github.com/gumyr/cq_warehouse/archive/{PIN_SHA}.tar.gz"

RES = {"os": None, "checks": {}, "findings": []}


def run(cmd, env=None, cwd=None, timeout=900):
    p = subprocess.run(cmd, env=env, cwd=cwd, timeout=timeout,
                       capture_output=True, text=True)
    return {"cmd": [str(c) for c in cmd], "returncode": p.returncode,
            "stdout_tail": p.stdout[-2000:], "stderr_tail": p.stderr[-2000:]}


def env_python_of(env_dir):
    # same construction as app/src/main/packages.ts:24-25 (WIN ? 'Scripts' : 'bin')
    scripts = env_dir / ("Scripts" if os.name == "nt" else "bin")
    exe = "python.exe" if os.name == "nt" else "python"
    return scripts / exe, scripts


def install_pin_into_env(env_dir, workdir):
    """Emulate the app terminal flow (terminals.ts:18-21): VIRTUAL_ENV + PIP_PYTHON
    + env Scripts dir first on PATH; pip of the base interpreter does the install."""
    envp_python, scripts = env_python_of(env_dir)
    envp = dict(os.environ)
    envp["VIRTUAL_ENV"] = str(env_dir)
    envp["PIP_PYTHON"] = str(envp_python)
    envp["PATH"] = str(scripts) + os.pathsep + envp.get("PATH", "")

    rec = {"pip_python": str(envp_python)}
    t0 = time.perf_counter()
    r = run([sys.executable, "-m", "pip", "install", PIN_URL], env=envp)
    rec["primary"] = {"install_url": PIN_URL, **r}
    if r["returncode"] != 0:
        # fallback: exact-commit source archive (SHA is in the URL)
        tarball = Path(workdir) / f"cq_warehouse-{PIN_SHA}.tar.gz"
        try:
            urllib.request.urlretrieve(ARCHIVE_URL, tarball)
            r2 = run([sys.executable, "-m", "pip", "install", str(tarball)], env=envp)
            rec["fallback"] = {"install_url": ARCHIVE_URL,
                               "tarball": str(tarball), **r2}
            rec["method"] = "archive-fallback" if r2["returncode"] == 0 else "FAILED-both"
        except Exception as e:
            rec["fallback"] = f"download FAIL {type(e).__name__}: {e}"
            rec["method"] = "FAILED-both"
    else:
        rec["method"] = "git+https"
    rec["seconds"] = round(time.perf_counter() - t0, 2)
    return rec


IMPORT_PROBE = r"""
import importlib.metadata as md, json, os, sys
out = {}
try:
    import cq_warehouse
    out["version"] = md.version("cq-warehouse")
    out["module_file"] = cq_warehouse.__file__
    dist = md.distribution("cq-warehouse")
    out["dist_file"] = str(dist._path) if hasattr(dist, "_path") else None
    d = None
    for f in dist.files or []:
        if str(f).endswith("direct_url.json"):
            d = dist.locate_file(f)
            break
    out["direct_url"] = json.loads(d.read_text(encoding="utf-8")) if d else None
except Exception as e:
    out["error"] = f"{type(e).__name__}: {e}"
print(json.dumps(out))
"""


def import_from_env(env_dir):
    envp_python, _ = env_python_of(env_dir)
    r = run([str(envp_python), "-c", IMPORT_PROBE])
    rec = {"run": r}
    try:
        data = json.loads(r["stdout_tail"].strip().splitlines()[-1])
    except Exception:
        data = {"error": "probe produced no parseable output"}
    rec.update(data)
    mf = data.get("module_file")
    rec["in_project_env"] = bool(mf and os.path.normcase(str(mf)).startswith(
        os.path.normcase(str(env_dir))))
    return rec


def check_project(project, soma_python, workdir, label):
    sys.path.insert(0, str(soma_python))
    import soma.env as se  # noqa: E402

    out = {}
    res = se.ensure(str(project))
    out["ensure"] = res
    env_dir = Path(res.get("env", project / ".soma" / "env"))
    envp_python, scripts = env_python_of(env_dir)

    out["windows_paths"] = {
        "env_dir": str(env_dir),
        "env_python_expected": str(envp_python),
        "env_python_exists": envp_python.is_file(),
        "scripts_dir": str(scripts),
        "pyvenv_cfg_exists": (env_dir / "pyvenv.cfg").is_file(),
        "pip_ini_exists": (env_dir / "pip.ini").is_file(),
        "pip_conf_exists": (env_dir / "pip.conf").is_file(),
    }
    for fname in ("pip.ini", "_soma_base.pth", "base-constraints.txt",
                  "soma-env.json"):
        p = None
        if fname == "_soma_base.pth":
            sp = Path(res.get("site", env_dir / "Lib" / "site-packages"))
            p = sp / fname
        else:
            p = env_dir / fname
        try:
            out.setdefault("files", {})[fname] = {
                "path": str(p), "exists": p.is_file(),
                "content_head": p.read_text(encoding="utf-8")[:600] if p.is_file() else None,
            }
        except OSError as e:
            out.setdefault("files", {})[fname] = {"path": str(p), "error": str(e)}

    out["install"] = install_pin_into_env(env_dir, workdir)
    out["import_from_env"] = import_from_env(env_dir)

    # base interpreter + env.activate() must see the package (env.py:133)
    act_code = (
        "import json,sys;"
        f"sys.path.insert(0, {str(soma_python)!r});"
        "import soma.env as se;"
        f"se.activate({str(project)!r});"
        "import cq_warehouse, importlib.metadata as md;"
        "print(json.dumps({'file': cq_warehouse.__file__,"
        "'version': md.version('cq-warehouse')}))"
    )
    r = run([sys.executable, "-c", act_code])
    out["import_via_activate"] = {"run": r}
    try:
        out["import_via_activate"].update(
            json.loads(r["stdout_tail"].strip().splitlines()[-1]))
    except Exception:
        pass

    # cadquery must load through the .pth attachment (OCP DLL/pyd load on Windows)
    cad_code = (
        f"import sys; sys.path.insert(0, {str(soma_python)!r});"
        "import soma.env as se;"
        f"se.activate({str(project)!r});"
        "import cadquery; print('cadquery', cadquery.__version__)"
    )
    r = run([str(envp_python), "-c", cad_code])
    out["cadquery_via_env_python"] = {"run": r}

    out["ok"] = bool(out["windows_paths"]["env_python_exists"]
                     and out["install"]["method"] != "FAILED-both"
                     and out["import_from_env"].get("in_project_env")
                     and out["import_from_env"].get("version") == "0.8.0")
    RES["checks"][label] = out
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--soma-python", required=True,
                    help="path to <soma checkout>/python")
    ap.add_argument("--workdir", default=".")
    ap.add_argument("--out", default="sp3-env-results.json")
    args = ap.parse_args()

    soma_python = Path(args.soma_python).resolve()
    workdir = Path(args.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    RES["os"] = {"platform": platform.platform(), "os_name": os.name,
                 "python": sys.version.split()[0], "executable": sys.executable}
    RES["soma_python"] = str(soma_python)

    t0 = time.perf_counter()
    proj1 = workdir / "proj1"
    proj1.mkdir(parents=True, exist_ok=True)
    check_project(proj1, soma_python, workdir, "plain_path")

    # Windows robustness probe: project path containing a space
    proj2 = workdir / "proj with space"
    proj2.mkdir(parents=True, exist_ok=True)
    check_project(proj2, soma_python, workdir, "path_with_space")

    RES["total_seconds"] = round(time.perf_counter() - t0, 2)
    for label, out in RES["checks"].items():
        status = "OK " if out.get("ok") else "FAIL"
        print(f"{status} {label}: env_python={out['windows_paths']['env_python_exists']} "
              f"install={out['install']['method']} "
              f"in_env={out['import_from_env'].get('in_project_env')}")
        if not out.get("ok"):
            RES["findings"].append(
                f"{label}: ok=false (install={out['install']['method']}, "
                f"env_python={out['windows_paths']['env_python_exists']}, "
                f"in_env={out['import_from_env'].get('in_project_env')})")

    Path(args.out).write_text(json.dumps(RES, indent=2, default=str),
                              encoding="utf-8")
    print(f"results written to {args.out}")


if __name__ == "__main__":
    main()
