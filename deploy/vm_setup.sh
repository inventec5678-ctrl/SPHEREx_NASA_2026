#!/bin/bash
# Set up the SPHEREx Sky Change site on a GCP VM (Ubuntu, NVIDIA L4), run as the login user from the project root:
#   bash deploy/vm_setup.sh
# The web app (uvicorn on 127.0.0.1:8791) and the analysis worker run as system services; nginx serves port 80
# and forwards to the app. The built front end (web/app/dist) is copied from the development machine, so Node is
# not needed here.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd); USER_NAME=$(whoami)

apt_install() { sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$@" >/dev/null; }
sudo apt-get update -qq
apt_install nginx python3.12 python3.12-venv || apt_install nginx

# Python 3.12: the system's if present, otherwise one installed by uv (pip-installed for this user)
PY=$(command -v python3.12 || true)
if [ -z "$PY" ]; then
  python3 -m pip install -q --user uv
  ~/.local/bin/uv python install 3.12
  PY=$(~/.local/bin/uv python find 3.12)
fi
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

# image cache: SX_CACHE if given (e.g. an existing cache on this disk), else ./cache
CACHE=${SX_CACHE:-$ROOT/cache}
mkdir -p "$CACHE" logs var
sudo tee /etc/systemd/system/spherex-web.service >/dev/null <<EOF
[Unit]
Description=SPHEREx Sky Change web app (NASA Space Apps 2026)
After=network-online.target
Wants=network-online.target
[Service]
User=$USER_NAME
WorkingDirectory=$ROOT
ExecStart=$ROOT/.venv/bin/python -m uvicorn web.server:app --host 127.0.0.1 --port 8791 --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=on-failure
RestartSec=3
Environment=PYTHONUNBUFFERED=1
Environment=SX_CACHE=$CACHE
[Install]
WantedBy=multi-user.target
EOF
sudo tee /etc/systemd/system/spherex-worker.service >/dev/null <<EOF
[Unit]
Description=SPHEREx Sky Change analysis worker
After=network-online.target
[Service]
User=$USER_NAME
WorkingDirectory=$ROOT
ExecStart=$ROOT/.venv/bin/python web/worker.py
Restart=on-failure
RestartSec=10
Nice=10
Environment=PYTHONUNBUFFERED=1
Environment=SX_CACHE=$CACHE
Environment=OMP_NUM_THREADS=4
[Install]
WantedBy=multi-user.target
EOF
sudo tee /etc/nginx/sites-available/spherex >/dev/null <<'EOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    client_max_body_size 2m;
    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml;
    location / {
        proxy_pass http://127.0.0.1:8791;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header CF-Connecting-IP $remote_addr;   # the app reads this first; never trust a client-sent value
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }
}
EOF
# weekly "is there newer SPHEREx data?" check (scripts/update_fields.py): the unit files in deploy/ with this
# machine's project path and user substituted
sed -e "s#^WorkingDirectory=.*#WorkingDirectory=$ROOT#" \
    -e "s#^ExecStart=.*#ExecStart=$ROOT/.venv/bin/python scripts/update_fields.py#" \
    -e "/^\[Service\]/a User=$USER_NAME" \
    deploy/spherex-update.service | sudo tee /etc/systemd/system/spherex-update.service >/dev/null
sudo cp deploy/spherex-update.timer /etc/systemd/system/spherex-update.timer
sudo ln -sf /etc/nginx/sites-available/spherex /etc/nginx/sites-enabled/spherex
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl daemon-reload
sudo systemctl enable --now spherex-web spherex-worker spherex-update.timer
# enable --now does not restart services that are already running (e.g. when moving to a new project folder)
sudo systemctl restart spherex-web spherex-worker nginx
sleep 3
curl -s -o /dev/null -w "local check: %{http_code}\n" http://127.0.0.1/
