#!/usr/bin/env bash
# =============================================================================
# Phase 21 - Specialist 2 (SOMA environment/package mechanism)
#
# Proves that cq_warehouse 0.8.0 (pinned git commit a307044f91c9cc5433fde92cb1fa145c01b2bde7)
# can be installed AND reinstalled through SOMA's own project-environment mechanism:
#   - python/soma/env.py       ensure(), record_requirements(), requirements_path()
#   - app/src/main/packages.ts installMissing(), missingLines(), envPaths()
#   - app/src/main/terminals.ts terminalEnv()  (PIP_PYTHON redirect)
#
# Runs ONLY on GitHub-hosted runners (push trigger on branch test/phase21-env).
# Evidence only: this script creates a temporary test project under $RUNNER_TEMP,
# it does not change any SOMA code and downloads nothing to the user's computer.
#
# All logs and results.json are written to $RUNNER_TEMP/sp2out and uploaded as
# the workflow artifact "sp2-env-results".
# =============================================================================
set -u

: "${GITHUB_WORKSPACE:?this script must run on a GitHub Actions runner}"
OUT="${RUNNER_TEMP:-/tmp}/sp2out"
PROJ="${RUNNER_TEMP:-/tmp}/sp2proj"
rm -rf "$OUT" "$PROJ"
mkdir -p "$OUT" "$PROJ/.soma"

export PYTHONPATH="$GITHUB_WORKSPACE/python"
export PYTHONUTF8=1

CQW_SHA="a307044f91c9cc5433fde92cb1fa145c01b2bde7"
CQW_PIN="git+https://github.com/gumyr/cq_warehouse.git@${CQW_SHA}"
ENVDIR="$PROJ/.soma/env"
ENVPY="$ENVDIR/bin/python"

say()  { echo "[sp2] $*"; }
flag() { echo "$1=$2" >> "$OUT/flags.env"; }

# -----------------------------------------------------------------------------
say "STEP 1: base runtime = SOMA's pinned stack into the runner's Python 3.12"
python -VV > "$OUT/00-python-version.txt" 2>&1
pip install "pip==26.2.1" > "$OUT/01-pip-pin.log" 2>&1
if pip install -r "$GITHUB_WORKSPACE/python/requirements-base.txt" > "$OUT/01-base-install.log" 2>&1; then
  flag base_install_ok 1
  say "base install OK"
else
  flag base_install_ok 0
  say "BASE INSTALL FAILED - see 01-base-install.log"
  tail -20 "$OUT/01-base-install.log"
  exit 1
fi
python - <<'EOF' > "$OUT/01-stack-versions.txt" 2>&1
import importlib.metadata as m
for p in ("cadquery", "cadquery-ocp", "cadquery-ocp-proxy", "pip"):
    try:
        print(f"{p}=={m.version(p)}")
    except Exception as e:
        print(f"{p}: MISSING ({e})")
EOF
pip list --format=freeze > "$OUT/base-before.txt"

# -----------------------------------------------------------------------------
say "STEP 2: minimal SOMA project whose model imports cq_warehouse"
cat > "$PROJ/model.py" <<'EOF'
"""SP2 test model (phase 21): one cq_warehouse fastener registered as a SOMA part.

Mirrors app/resources/template/model.py (add_part API, python/soma/registry.py:69).
"""
import cadquery as cq
from soma import add_part
from cq_warehouse.fastener import SocketHeadCapScrew

screw = SocketHeadCapScrew(size="M6-1", length=12.0, fastener_type="iso4762")
add_part("Screw", screw, color=(0.75, 0.75, 0.8))
EOF
cat > "$PROJ/.soma/project.json" <<'EOF'
{
  "api": 1,
  "name": "sp2-env-test",
  "entry": "model.py"
}
EOF
flag project_created 1

# -----------------------------------------------------------------------------
say "STEP 3: create the project env with SOMA's OWN mechanism (soma env -> env.ensure())"
if python -m soma env --project "$PROJ" --json > "$OUT/03-env-ensure.json" 2> "$OUT/03-env-ensure.err"; then
  flag env_created 1
else
  flag env_created 0
  say "soma env FAILED"; cat "$OUT/03-env-ensure.err"
fi
cat "$OUT/03-env-ensure.json"
# evidence of what the mechanism wrote
ls -la "$ENVDIR" > "$OUT/03-env-dir-listing.txt" 2>&1
cat "$ENVDIR/soma-env.json"      > "$OUT/03-soma-env.json" 2>/dev/null
cat "$ENVDIR/_soma_base.pth"     > "$OUT/03-soma-base.pth" 2>/dev/null
cat "$ENVDIR/pip.conf"           > "$OUT/03-pip.conf" 2>/dev/null
head -30 "$ENVDIR/base-constraints.txt" > "$OUT/03-base-constraints-head.txt" 2>/dev/null
wc -l "$ENVDIR/base-constraints.txt"    >> "$OUT/03-base-constraints-head.txt" 2>/dev/null
"$ENVPY" -m pip config debug > "$OUT/03-pip-config-debug.txt" 2>&1
"$ENVPY" -m pip --version   > "$OUT/03-env-pip-version.txt" 2>&1
SITE=$("$ENVPY" -c "import sysconfig; print(sysconfig.get_path('purelib'))" 2>/dev/null)
echo "SITE=$SITE" >> "$OUT/flags.env"
ls "$SITE" > "$OUT/03-env-site-packages-before.txt" 2>&1

# env python must see base packages (via _soma_base.pth) but NOT cq_warehouse yet
if "$ENVPY" -c "import cadquery; print('cadquery OK', cadquery.__version__)" > "$OUT/03-env-import-cadquery.txt" 2>&1; then
  flag env_sees_base_cadquery 1
else
  flag env_sees_base_cadquery 0
fi
if "$ENVPY" -c "import cq_warehouse; print('cq_warehouse visible')" > "$OUT/03-env-import-cqw-before.txt" 2>&1; then
  flag env_sees_cqw_before_install 1
else
  flag env_sees_cqw_before_install 0   # expected: 0
fi
"$ENVPY" -m pip list --format=freeze > "$OUT/03-env-pip-list-before.txt" 2>&1

# -----------------------------------------------------------------------------
say "STEP 4: install cq_warehouse INTO the project env via the app's terminal flow (PIP_PYTHON)"
# app/src/main/terminals.ts:17-24 sets VIRTUAL_ENV and PIP_PYTHON to the project env,
# so a plain `pip install` lands in .soma/env and the base stays untouched.
export VIRTUAL_ENV="$ENVDIR"
export PIP_PYTHON="$ENVPY"
pip --version > "$OUT/04-pip-redirect-version.txt" 2>&1
if pip install "$CQW_PIN" > "$OUT/04-install-cqw-terminal-flow.log" 2>&1; then
  flag install_terminal_flow_ok 1
else
  flag install_terminal_flow_ok 0
  say "terminal-flow install failed; falling back to env python (packages.ts:171 style)"
fi
if "$ENVPY" -c "import cq_warehouse" > /dev/null 2>&1; then
  flag cqw_installed_in_env 1
else
  "${ENVPY}" -m pip install "$CQW_PIN" > "$OUT/04-install-cqw-envpython-fallback.log" 2>&1
  if "$ENVPY" -c "import cq_warehouse" > /dev/null 2>&1; then flag cqw_installed_in_env 1; else flag cqw_installed_in_env 0; fi
fi
unset PIP_PYTHON VIRTUAL_ENV

# capture the installed distribution's provenance (pip writes direct_url.json for VCS installs)
if ls "$SITE"/cq_warehouse-*.dist-info/direct_url.json > /dev/null 2>&1; then
  flag direct_url_present_after_install 1
  cat "$SITE"/cq_warehouse-*.dist-info/direct_url.json > "$OUT/04-direct_url.json"
else
  flag direct_url_present_after_install 0
fi
grep -E '^(Name|Version|Summary|Home-page):' "$SITE"/cq_warehouse-*.dist-info/METADATA > "$OUT/04-cqw-metadata.txt" 2>&1
find "$SITE/cq_warehouse" -type f 2>/dev/null | sort | xargs -r sha256sum > "$OUT/04-cqw-files-git-install.txt"
"$ENVPY" -m pip list --format=freeze > "$OUT/04-env-pip-list-after.txt" 2>&1
"$ENVPY" -c "import cq_warehouse; print(cq_warehouse.__file__)" > "$OUT/04-env-import-cqw.txt" 2>&1

# -----------------------------------------------------------------------------
say "STEP 5: base runtime must be unchanged after the install"
pip list --format=freeze > "$OUT/base-after-install.txt"
if diff "$OUT/base-before.txt" "$OUT/base-after-install.txt" > "$OUT/05-base-diff-after-install.txt"; then
  flag base_unchanged_after_install 1
else
  flag base_unchanged_after_install 0
fi
if python -c "import cq_warehouse" > "$OUT/05-base-import-cqw.txt" 2>&1; then
  flag cqw_in_base_after_install 1
else
  flag cqw_in_base_after_install 0   # expected: 0
fi

# -----------------------------------------------------------------------------
say "STEP 6: build the project (soma build -> build.py -> env.record_requirements)"
python -m soma build --project "$PROJ" --json > "$OUT/06-build.json" 2> "$OUT/06-build.err"
BUILD_STATUS=$(python -c "import json;print(json.load(open('$OUT/06-build.json')).get('status'))" 2>/dev/null || echo unreadable)
flag build_status "$BUILD_STATUS"
if [ -f "$PROJ/requirements.txt" ]; then
  flag requirements_written 1
  cp "$PROJ/requirements.txt" "$OUT/06-requirements.txt"
else
  flag requirements_written 0
fi

say "STEP 6b: does a manual PEP 508 git line survive a rebuild? (record_requirements overwrite test)"
cat > "$PROJ/requirements.txt" <<EOF
cq_warehouse @ ${CQW_PIN}
EOF
python -m soma build --project "$PROJ" --json > "$OUT/06b-build.json" 2> "$OUT/06b-build.err"
if [ -f "$PROJ/requirements.txt" ]; then
  cp "$PROJ/requirements.txt" "$OUT/06b-requirements-after-manual-pep508.txt"
fi

# -----------------------------------------------------------------------------
say "STEP 7: reinstall round-trip - delete .soma/env, rebuild env, reinstall from requirements.txt"
"$ENVPY" -m pip list --format=freeze > "$OUT/07-env-pip-list-pre-delete.txt" 2>&1
rm -rf "$ENVDIR"
flag env_deleted 1
python -m soma env --project "$PROJ" --json > "$OUT/07-env-ensure-2.json" 2> "$OUT/07-env-ensure-2.err"
if [ -x "$ENVPY" ]; then flag env_recreated 1; else flag env_recreated 0; fi

# replicate app/src/main/packages.ts:161-175 installMissing(): the fresh env is missing
# every non-base requirement, so restore-requirements.txt = the requirements lines;
# it installs with the env's python:  python -m pip install -r restore-requirements.txt
cp "$PROJ/requirements.txt" "$ENVDIR/restore-requirements.txt"
if ( cd "$PROJ" && "$ENVPY" -m pip install -r "$ENVDIR/restore-requirements.txt" ) > "$OUT/07-reinstall-install-missing.log" 2>&1; then
  flag reinstall_pip_ok 1
else
  flag reinstall_pip_ok 0
fi
"$ENVPY" -m pip list --format=freeze > "$OUT/07-env-pip-list-after-reinstall.txt" 2>&1
find "$SITE/cq_warehouse" -type f 2>/dev/null | sort | xargs -r sha256sum > "$OUT/07-cqw-files-reinstall.txt"
if ls "$SITE"/cq_warehouse-*.dist-info/direct_url.json > /dev/null 2>&1; then
  flag direct_url_present_after_reinstall 1
  cat "$SITE"/cq_warehouse-*.dist-info/direct_url.json > "$OUT/07-direct_url-after-reinstall.json"
else
  flag direct_url_present_after_reinstall 0   # expected 0 if reinstall came from PyPI
fi
if diff "$OUT/04-cqw-files-git-install.txt" "$OUT/07-cqw-files-reinstall.txt" > "$OUT/07-cqw-files.diff"; then
  flag same_files_after_reinstall 1
else
  flag same_files_after_reinstall 0
fi
# does the model still build after the reinstall?
python -m soma build --project "$PROJ" --json > "$OUT/07-build-after-reinstall.json" 2> "$OUT/07-build-after-reinstall.err"
flag build_after_reinstall_status "$(python -c "import json;print(json.load(open('$OUT/07-build-after-reinstall.json')).get('status'))" 2>/dev/null || echo unreadable)"

# what does PyPI actually serve for cq-warehouse?
if curl -sS --fail "https://pypi.org/pypi/cq-warehouse/json" -o "$OUT/07-pypi-cq-warehouse.json"; then
  flag pypi_exists 1
else
  flag pypi_exists 0
  rm -f "$OUT/07-pypi-cq-warehouse.json"
fi
python -m pip index versions cq-warehouse > "$OUT/07-pip-index-versions.txt" 2>&1

# -----------------------------------------------------------------------------
say "STEP 8/9: env removal cleanliness - base intact, nothing leaks outside the project dir"
rm -rf "$ENVDIR"
flag env_deleted_final 1
pip list --format=freeze > "$OUT/base-final.txt"
if diff "$OUT/base-before.txt" "$OUT/base-final.txt" > "$OUT/08-base-diff-final.txt"; then
  flag base_unchanged_final 1
else
  flag base_unchanged_final 0
fi
if python -c "import cq_warehouse" > "$OUT/08-base-import-cqw-final.txt" 2>&1; then
  flag cqw_in_base_final 1
else
  flag cqw_in_base_final 0   # expected: 0
fi
find "$HOME" "$PROJ" -maxdepth 8 \( -name '*cq_warehouse*' -o -name '*cq-warehouse*' \) 2>/dev/null \
  | grep -v "^${SITE:-/__none__}" | sort > "$OUT/08-leak-outside-env.txt" || true
git -C "$GITHUB_WORKSPACE" status --porcelain > "$OUT/08-workspace-status.txt" 2>&1

# -----------------------------------------------------------------------------
say "collect results.json"
python "$GITHUB_WORKSPACE/test/phase21/sp2_make_results.py" "$OUT" "$PROJ" "$CQW_SHA" > "$OUT/00-builder-stdout.txt" 2>&1
if [ -f "$OUT/results.json" ]; then
  say "results.json written"; cat "$OUT/results.json"
else
  say "results.json MISSING - see 00-builder-stdout.txt"
fi
say "done"
