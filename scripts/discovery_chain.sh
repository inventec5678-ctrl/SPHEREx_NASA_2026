#!/bin/sh
# Dwarf-planet tests -> planet-X grid (new linker) -> stacking depth -> survey -> summary.
# Waits for logs/dw_done.txt (written when the dwarf-planet analyses finish), then runs the chain; progress in
# logs/chain_stage.txt. Run from anywhere; Windows Git Bash: PYTHON=.venv/Scripts/python sh scripts/discovery_chain.sh
cd "$(dirname "$0")/.." || exit 1
PY=${PYTHON:-python3}
export PYTHONUNBUFFERED=1 SX_INSECURE=1
mkdir -p logs
while [ ! -f logs/dw_done.txt ]; do sleep 60; done
for n in Makemake Haumea Eris; do
  "$PY" scripts/dwarf_test.py fit "$n" > "logs/fit_$n.log" 2>&1
  "$PY" scripts/dwarf_test.py stack "$n" > "logs/stack_$n.log" 2>&1
done
echo dwarfs > logs/chain_stage.txt
"$PY" scripts/planetx_grid.py --out paper_evidence/planetx_grid.json > logs/grid_v3.log 2>&1
echo grid > logs/chain_stage.txt
"$PY" scripts/stack_grid.py --out paper_evidence/stack_grid.json > logs/stackgrid.log 2>&1
echo stackgrid > logs/chain_stage.txt
# the survey field ids (also read by post_chain2.sh)
"$PY" -c "import json;[print(f['id']) for f in json.load(open('outputs/survey/plan.json'))['fields']]" > logs/sv.txt
PY="$PY" xargs -P 3 -I{} sh -c '"$PY" scripts/survey.py run {} > logs/sv_{}.log 2>&1' < logs/sv.txt
"$PY" scripts/survey.py summary > logs/sv_summary.log 2>&1
echo DONE > logs/chain_stage.txt
