#!/bin/bash
set -euo pipefail

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

echo "Preparing the wine app..."
if [[ ! -x .venv/bin/python ]]; then
    python3 -m venv .venv
fi
.venv/bin/python -m pip install -r requirements.txt

mkdir -p "${HOME}/.config/systemd/user"
service_file="$(mktemp)"
trap 'rm -f "$service_file"' EXIT
sed "s|@APP_DIR@|$APP_DIR|g" systemd/wine-app.service > "$service_file"
install -m 0644 "$service_file" \
    "${HOME}/.config/systemd/user/wine-app.service"

systemctl --user daemon-reload
systemctl --user enable wine-app.service
systemctl --user restart wine-app.service
systemctl --user --no-pager status wine-app.service
