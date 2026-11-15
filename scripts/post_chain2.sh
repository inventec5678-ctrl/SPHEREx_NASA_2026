#!/bin/sh
# After discovery_chain.sh: re-stack every survey field and re-run the injection grids with the fixed linker
# (stationary groups first + full-fit check) and stacking (clipped frames, robust noise, confirmation).
# survey.py run skips the analysis when field.json exists, so only the search is repeated.
# Windows Git Bash: PYTHON=.venv/Scripts/python sh scripts/post_chain2.sh
cd "$(dirname "$0")/.." || exit 1
PY=${PYTHON:-python3}
export PYTHONUNBUFFERED=1 SX_INSECURE=1
while [ "$(cat logs/chain_stage.txt 2>/dev/null)" != DONE ]; do sleep 60; done
echo restack > logs/post_stage.txt
PY="$PY" xargs -P 4 -I{} sh -c '"$PY" scripts/survey.py run {} > logs/sv2_{}.log 2>&1' < logs/sv.txt
"$PY" scripts/survey.py summary > logs/sv_summary2.log 2>&1
echo grid > logs/post_stage.txt
"$PY" scripts/planetx_grid.py --out paper_evidence/planetx_grid.json > logs/grid_v4.log 2>&1
echo stackgrid > logs/post_stage.txt
"$PY" scripts/stack_grid.py --out paper_evidence/stack_grid.json > logs/stackgrid_v2.log 2>&1
for n in Makemake Haumea Eris; do "$PY" scripts/dwarf_test.py fit "$n" > "logs/fit2_$n.log" 2>&1; done
echo DONE > logs/post_stage.txt
