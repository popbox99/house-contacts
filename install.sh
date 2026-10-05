#!/usr/bin/env bash
# Generic installer (Linux): housecontacts.py -> ~/.local/bin + a 2-hour systemd user timer.
# Config lives at ~/.config/house-contacts/config.json (see config.example.json).
# macOS/Windows: skip this script and schedule `housecontacts.py build` with
# launchd/cron (macOS) or Task Scheduler (Windows) instead.
set -euo pipefail
cd "$(dirname "$0")"

install -m 755 housecontacts.py ~/.local/bin/
install -m 644 house-contacts.service house-contacts.timer ~/.config/systemd/user/

CONFIG="$HOME/.config/house-contacts/config.json"
if [ ! -f "$CONFIG" ]; then
  echo "==> Writing default config (Thunderbird source)"
  mkdir -p "$(dirname "$CONFIG")"
  cat > "$CONFIG" <<'EOF'
{
  "out_path": "~/.local/share/house-contacts/contacts.json",
  "sources": [
    {"type": "thunderbird"}
  ]
}
EOF
fi

# Optional: if your bot appends new contacts to a vCard ledger, register it as a
# source so bot-added people merge into contacts.json automatically. Example:
#   {"type": "vcf", "path": "~/path/to/bot-added.vcf"}

echo "==> First build"
~/.local/bin/housecontacts.py build

systemctl --user daemon-reload
systemctl --user enable --now house-contacts.timer
systemctl --user list-timers house-contacts.timer --no-pager

echo
echo "==> contacts.json is written to the out_path in your config."
echo "    Put it wherever your bot (and your sync tool) can read it."
