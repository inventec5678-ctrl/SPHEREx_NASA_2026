#!/bin/bash
# Push the current project (code, built front end, field data) to the GCP site and restart it:
#   bash deploy/push.sh            (run from the project root on the development machine, after `npm run build`;
#                                   on Windows run it from Git Bash or WSL with gcloud on PATH or in $GCLOUD)
# The VM keeps its own .venv, image cache and running quick looks; nothing there is deleted.
set -euo pipefail
cd "$(dirname "$0")/.."
G=${GCLOUD:-$(command -v gcloud || echo "$HOME/google-cloud-sdk/bin/gcloud")}
VM=${SX_VM:-spherex-web-l4}; ZONE=${SX_ZONE:-asia-northeast1-a}

# local-only material that the VM rebuilds or never needs: top-level paths, then names excluded at any depth
TOP=(.venv .git web/app/node_modules cache 'scratch*' logs var shots models/rb_cnn.train.pt models/test_scores.npz)
ANY=('*.pyc' __pycache__ .pytest_cache)
TAR_ARGS=()
for e in "${TOP[@]}"; do TAR_ARGS+=("--exclude=./$e"); done
for e in "${ANY[@]}"; do TAR_ARGS+=("--exclude=$e"); done

tar "${TAR_ARGS[@]}" -czf - . |
  "$G" compute ssh "$VM" --zone "$ZONE" --quiet --command "mkdir -p ~/spherex-web && tar xzf - -C ~/spherex-web &&
    cd ~/spherex-web && .venv/bin/pip install -q -r requirements.txt &&
    sudo systemctl restart spherex-web spherex-worker && sleep 3 &&
    curl -s -o /dev/null -w 'site: %{http_code}\n' http://127.0.0.1/"
