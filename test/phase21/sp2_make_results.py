#!/usr/bin/env python3
"""Phase 21 - Specialist 2: assemble results.json from the captured evidence files.

Usage: sp2_make_results.py <OUT_DIR> <PROJ_DIR> <CQW_SHA>
Reads flags.env + the logs written by sp2_env_test.sh, computes verdicts, writes OUT_DIR/results.json.
"""
import json
import re
import sys
from pathlib import Path

OUT = Path(sys.argv[1])
PROJ = Path(sys.argv[2])
CQW_SHA = sys.argv[3] if len(sys.argv) > 3 else ""


def flags():
    f = {}
    p = OUT / "flags.env"
    if p.is_file():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                f[k.strip()] = v.strip()
    return f


def read(name):
    p = OUT / name
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def first_json(name):
    t = read(name)
    if not t:
        return None
    try:
        return json.loads(t)
    except ValueError:
        return None


def pip_list(name):
    t = read(name) or ""
    out = {}
    for line in t.splitlines():
        if "==" in line:
            k, _, v = line.partition("==")
            out[k.strip().lower().replace("_", "-")] = v.strip()
    return out


F = flags()
b = lambda k: F.get(k) == "1"

# ---- environment mechanism (STEP 3) -----------------------------------------
soma_env_json = first_json("03-soma-env.json")
env_import_cqw_before = b("env_sees_cqw_before_install")
env_list_before = pip_list("03-env-pip-list-before.txt")
env_list_after = pip_list("04-env-pip-list-after.txt")

# ---- install (STEP 4) --------------------------------------------------------
direct_url = first_json("04-direct_url.json")
in_env_after = env_list_after.get("cq-warehouse") or env_list_after.get("cq_warehouse")

# ---- build / requirements (STEP 6) ------------------------------------------
req6 = read("06-requirements.txt")
req6b = read("06b-requirements-after-manual-pep508.txt")
git_url_in_req = bool(req6 and "git+" in req6)
sha_in_req = bool(req6 and CQW_SHA and CQW_SHA in req6)
pep508_survived = bool(req6b and "git+" in req6b and CQW_SHA in req6b)

# ---- reinstall (STEP 7) ------------------------------------------------------
reinstall_list = pip_list("07-env-pip-list-after-reinstall.txt")
in_env_reinstall = reinstall_list.get("cq-warehouse") or reinstall_list.get("cq_warehouse")
durl_reinstall = first_json("07-direct_url-after-reinstall.json")
reinstall_log = read("07-reinstall-install-missing.log") or ""
reinstall_ok = b("reinstall_pip_ok")

if not reinstall_ok:
    reinstall_source = "failed"
elif durl_reinstall and "git+" in json.dumps(durl_reinstall):
    reinstall_source = "git"
elif "files.pythonhosted.org" in reinstall_log or "pypi" in reinstall_log.lower():
    reinstall_source = "pypi"
elif in_env_reinstall:
    reinstall_source = "no-direct-url (consistent with an index/PyPI install)"
else:
    reinstall_source = "unknown"

# ---- PyPI (STEP 7) -----------------------------------------------------------
pypi = {"exists": b("pypi_exists"), "versions": [], "files": []}
pypi_json = first_json("07-pypi-cq-warehouse.json")
if pypi_json:
    pypi["versions"] = sorted(pypi_json.get("releases", {}).keys())
    for u in pypi_json.get("urls", []) or []:
        pypi["files"].append({k: u.get(k) for k in ("filename", "packagetype", "upload_time_iso_8601", "digests")})

# ---- base runtime / cleanliness (STEP 5, 8/9) --------------------------------
base_before = pip_list("base-before.txt")
base_final = pip_list("base-final.txt")
base_same_pkgs = set(base_before.items()) == set(base_final.items())

leaks = [l for l in (read("08-leak-outside-env.txt") or "").splitlines() if l.strip()]

results = {
    "task": "phase21-specialist2-environment-mechanism",
    "subject": {
        "package": "cq_warehouse",
        "version": "0.8.0",
        "install_pin": f"git+https://github.com/gumyr/cq_warehouse.git@{CQW_SHA}",
        "soma_commit_under_test": "cf8e629ef0dc1c2c54ee3fb62d50a208aa938c27",
    },
    "base_runtime": {
        "python": (read("00-python-version.txt") or "").strip(),
        "stack": (read("01-stack-versions.txt") or "").strip(),
        "pip_freeze_before": "base-before.txt",
        "unchanged_after_install": b("base_unchanged_after_install"),
        "unchanged_after_all_steps": b("base_unchanged_final") and base_same_pkgs,
        "cq_warehouse_in_base_after_install": b("cqw_in_base_after_install"),
        "cq_warehouse_in_base_final": b("cqw_in_base_final"),
    },
    "env_mechanism": {
        "created_via": "python -m soma env --project <proj> --json  (= env.ensure(), python/soma/env.py)",
        "ensure_result": first_json("03-env-ensure.json"),
        "soma_env_json": soma_env_json,
        "venv_with_pip": False,  # env.py:101 venv.EnvBuilder(with_pip=False) - pip comes from base via _soma_base.pth
        "env_sees_base_cadquery": b("env_sees_base_cadquery"),
        "env_sees_cq_warehouse_before_install": env_import_cqw_before,
        "env_packages_before_install": env_list_before,
    },
    "install_into_env": {
        "flow": "terminals.ts:20 PIP_PYTHON=<env>/bin/python -> `pip install <git pin>` (fallback: env python -m pip)",
        "terminal_flow_ok": b("install_terminal_flow_ok"),
        "installed_in_env": b("cqw_installed_in_env"),
        "version_in_env": in_env_after,
        "direct_url_json": direct_url,
        "direct_url_present": b("direct_url_present_after_install"),
    },
    "build": {
        "status_first_build": F.get("build_status"),
        "requirements_written": b("requirements_written"),
        "requirements_txt_exact_content": req6,
        "requirements_txt_contains_git_url": git_url_in_req,
        "requirements_txt_contains_pinned_sha": sha_in_req,
        "manual_pep508_line_survived_rebuild": pep508_survived,
        "requirements_after_manual_pep508_and_rebuild": req6b,
    },
    "reinstall_roundtrip": {
        "env_deleted_and_recreated": b("env_deleted") and b("env_recreated"),
        "flow": "replicated packages.ts:161-175 installMissing(): env python -m pip install -r .soma/env/restore-requirements.txt",
        "pip_install_ok": reinstall_ok,
        "version_installed": in_env_reinstall,
        "source": reinstall_source,
        "direct_url_present_after_reinstall": b("direct_url_present_after_reinstall"),
        "direct_url_json_after_reinstall": durl_reinstall,
        "same_files_as_git_install": b("same_files_after_reinstall"),
        "build_after_reinstall_status": F.get("build_after_reinstall_status"),
    },
    "pypi_state": pypi,
    "cleanliness": {
        "base_intact_after_env_removal": b("base_unchanged_final") and base_same_pkgs,
        "cq_warehouse_importable_in_base_final": b("cqw_in_base_final"),
        "files_outside_env_matching_cq_warehouse": leaks,
        "workspace_git_status": read("08-workspace-status.txt"),
    },
    "artifacts": sorted(p.name for p in OUT.iterdir() if p.is_file()),
}

# ---- verdicts / findings ------------------------------------------------------
findings = []

lost = (not git_url_in_req) and (not sha_in_req)
if req6 is not None and lost:
    findings.append({
        "id": "F1",
        "severity": "high",
        "title": "record_requirements() drops the git origin and commit SHA of VCS installs",
        "detail": (
            "requirements.txt records only `Name==version` (python/soma/env.py:181 builds "
            "`f\"{name}=={d.version}\"` from installed metadata; env.py:201/207 write exactly those lines). "
            "pip's direct_url.json (which holds url+commit_id for VCS installs) is never read. "
            f"Observed requirements.txt: {req6!r}; direct_url.json at install time: {json.dumps(direct_url)}"
        ),
        "evidence": ["06-requirements.txt", "04-direct_url.json", "python/soma/env.py:165-210"],
    })
if req6b is not None and not pep508_survived:
    findings.append({
        "id": "F2",
        "severity": "high",
        "title": "A manually preserved PEP 508 git line is overwritten by the next successful build",
        "detail": (
            "record_requirements() keeps an existing line only when its name is NOT installed in the env "
            "(python/soma/env.py:203). For an installed package the line is replaced with `Name==version` "
            f"(env.py:201). Observed after rebuild: {req6b!r}"
        ),
        "evidence": ["06b-requirements-after-manual-pep508.txt", "python/soma/env.py:201-207"],
    })
if reinstall_ok and reinstall_source == "pypi":
    findings.append({
        "id": "F3",
        "severity": "high",
        "title": "Reinstall restores 0.8.0 from PyPI instead of the pinned git commit (silent source change)",
        "detail": (
            "packages.ts:139-158 missingLines()/installMissing() reinstall exactly the recorded lines; with "
            "`cq_warehouse==0.8.0` pip resolves from the index. Same version string, different source than the "
            "evaluated commit a307044f. No direct_url.json in the restored env proves an index install."
        ),
        "evidence": ["07-reinstall-install-missing.log", "07-env-pip-list-after-reinstall.txt"],
    })
if not reinstall_ok:
    findings.append({
        "id": "F3",
        "severity": "high",
        "title": "Reinstall from requirements.txt FAILED - the env round-trip is broken",
        "detail": "See 07-reinstall-install-missing.log. With `cq_warehouse==0.8.0` pip can only resolve from an index; if the index lacks it, restore fails.",
        "evidence": ["07-reinstall-install-missing.log"],
    })

results["findings"] = findings
results["verdicts"] = {
    "install_via_soma_env_mechanism": "PASS" if (b("env_created") and b("cqw_installed_in_env") and not b("cqw_in_base_after_install")) else "FAIL",
    "base_runtime_untouched": "PASS" if (b("base_unchanged_after_install") and base_same_pkgs) else "FAIL",
    "source_sha_preservation_in_requirements_txt": "FAIL (origin lost)" if lost else "PASS",
    "reinstall_from_same_source_same_sha": "PASS" if (reinstall_ok and reinstall_source == "git" and b("same_files_after_reinstall")) else "FAIL",
    "env_removal_cleanliness": "PASS" if (base_same_pkgs and not b("cqw_in_base_final")) else "FAIL",
}

(OUT / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
print(json.dumps(results["verdicts"], indent=1))
