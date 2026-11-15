#!/bin/sh
# Rebuild every analysed field on the releases IRSA serves now (DR1 + QR3), then redo the named targets' extra
# measurements, the automatic searches and the validation exports. Snapshot first:
#   python scripts/rebuild_release.py snapshot qr2qr3
# The simulated Planet X field is a fixed test case and is not rebuilt.
# Python: $PYTHON, else .venv/bin/python (Linux) or .venv/Scripts/python (Windows Git Bash).
cd "$(dirname "$0")/.." || exit 1
export PYTHONUNBUFFERED=1 SX_INSECURE=1
if [ -n "$PYTHON" ]; then PY=$PYTHON
elif [ -x .venv/bin/python ]; then PY=.venv/bin/python
else PY=.venv/Scripts/python
fi
L=logs/release
mkdir -p "$L"
echo builds > "$L/stage.txt"
printf '%s\n' barnard epsindi wise0855 rwaur rdra cybele taurus q043p280+16p853s15 q183p200-01p400 |
  PY="$PY" L="$L" xargs -P 3 -I{} sh -c '"$PY" scripts/rebuild_release.py build {} > "$L/build_{}.log" 2>&1'
echo targets > "$L/stage.txt"
"$PY" scripts/psf_targets.py > "$L/psf_targets.log" 2>&1
"$PY" scripts/bd_targets.py > "$L/bd_targets.log" 2>&1
"$PY" scripts/external_checks.py > "$L/external_checks.log" 2>&1
echo searches > "$L/stage.txt"
"$PY" scripts/pm_search.py > "$L/pm_search.log" 2>&1
"$PY" scripts/pm_search.py --validate > "$L/xepoch.log" 2>&1
"$PY" scripts/var_search.py > "$L/var_search.log" 2>&1
"$PY" scripts/export_validation_detail.py > "$L/export_detail.log" 2>&1
echo DONE > "$L/stage.txt"
