#!/usr/bin/env bash
# SP3: install the exact pinned stack + cq_warehouse 0.8.0 commit pin.
# Works under Git Bash on windows-latest and on ubuntu-latest.
#
# Primary install:  pip install git+https://github.com/gumyr/cq_warehouse.git@<sha>
# Fallback (recorded as a FINDING if the primary fails, e.g. missing git or build
# backend issues): pip install of the GitHub source archive of the SAME commit
# https://github.com/gumyr/cq_warehouse/archive/<sha>.tar.gz - still an exact,
# verifiable commit pin (the SHA is in the URL), never a floating version.
set -uo pipefail

PIN_SHA=a307044f91c9cc5433fde92cb1fa145c01b2bde7
WORK="${RUNNER_TEMP:-$PWD}"
INSTALL_LOG="$WORK/sp3-install-full.log"
: > "$INSTALL_LOG"

python -m pip install --upgrade pip 2>&1 | tee -a "$INSTALL_LOG"

echo "== pinned base stack (python/requirements-base.txt) ==" | tee -a "$INSTALL_LOG"
python -m pip install "cadquery==2.8.0" "cadquery-ocp==7.9.3.1.1" "cadquery-ocp-proxy==7.9.3.1.1" 2>&1 | tee -a "$INSTALL_LOG"
BASE_RC=${PIPESTATUS[0]}

METHOD=""
echo "== cq_warehouse pin: git+https @ $PIN_SHA ==" | tee -a "$INSTALL_LOG"
if python -m pip install "git+https://github.com/gumyr/cq_warehouse.git@${PIN_SHA}" 2>&1 | tee -a "$INSTALL_LOG"; then
  METHOD="git+https"
else
  GIT_RC=${PIPESTATUS[0]}
  echo "== FINDING: git+https pinned install failed (rc=$GIT_RC); trying commit archive fallback ==" | tee -a "$INSTALL_LOG"
  ARCHIVE="$WORK/cq_warehouse-$PIN_SHA.tar.gz"
  curl -fsSL -o "$ARCHIVE" "https://github.com/gumyr/cq_warehouse/archive/${PIN_SHA}.tar.gz" 2>&1 | tee -a "$INSTALL_LOG"
  curl_rc=${PIPESTATUS[0]}
  if [ "$curl_rc" -eq 0 ]; then
    echo "archive sha256: $(sha256sum "$ARCHIVE" | cut -d' ' -f1)" | tee -a "$INSTALL_LOG"
    if python -m pip install "$ARCHIVE" 2>&1 | tee -a "$INSTALL_LOG"; then
      METHOD="archive-fallback"
    else
      METHOD="FAILED-both"
    fi
  else
    echo "== archive download failed (rc=$curl_rc) ==" | tee -a "$INSTALL_LOG"
    METHOD="FAILED-both"
  fi
fi

echo "== verify pins / provenance ==" | tee -a "$INSTALL_LOG"
python sp3-src/test/phase21/phase21_sp3_verify_install.py --method "$METHOD" 2>&1 | tee -a "$INSTALL_LOG"

echo "== pip list ==" | tee -a "$INSTALL_LOG"
pip list 2>&1 | tee -a "$INSTALL_LOG"

echo "BASE_STACK_RC=$BASE_RC METHOD=$METHOD" | tee -a "$INSTALL_LOG"
if [ "$METHOD" = "FAILED-both" ] || [ "$BASE_RC" -ne 0 ]; then
  exit 1
fi
