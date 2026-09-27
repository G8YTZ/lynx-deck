#!/usr/bin/env bash
# Install (or reinstall) the Lynx Deck service for the user running this
# script. Nothing is hard-coded: the username, group and paths come from the
# environment, so it does not matter whether the account is called pi, lynx or
# anything else.
#
#   ./scripts/install.sh
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="$(id -un)"
GROUP_NAME="$(id -gn)"
UNIT=/etc/systemd/system/lynx-deck.service

if [ "$USER_NAME" = "root" ]; then
  echo "Run this as the user the deck should run as, not as root." >&2
  echo "It will ask for sudo where it needs it." >&2
  exit 1
fi

echo "Installing Lynx Deck"
echo "  user:  $USER_NAME ($GROUP_NAME)"
echo "  repo:  $REPO"

# --- the things the deck needs ---------------------------------------------
missing=()
for cmd in mpv ffprobe python3 git; do
  command -v "$cmd" >/dev/null || missing+=("$cmd")
done
python3 -c "import yaml" 2>/dev/null || missing+=("python3-yaml")
python3 -c "import fastapi, uvicorn" 2>/dev/null || missing+=("python3-fastapi/uvicorn")
if [ ${#missing[@]} -gt 0 ]; then
  echo
  echo "Missing: ${missing[*]}"
  echo "Install them with:"
  echo "  sudo apt install -y git mpv ffmpeg python3-yaml python3-fastapi python3-uvicorn libdrm-tests"
  exit 1
fi

# --- config -----------------------------------------------------------------
if [ ! -f "$REPO/config/lynx_deck.yaml" ]; then
  cp "$REPO/config/lynx_deck.yaml.example" "$REPO/config/lynx_deck.yaml"
  echo "  created config/lynx_deck.yaml from the example"
fi

# The live config must not be tracked, or editing it blocks the update button.
if git -C "$REPO" ls-files --error-unmatch config/lynx_deck.yaml >/dev/null 2>&1; then
  git -C "$REPO" rm --cached -q config/lynx_deck.yaml
  grep -qxF 'config/lynx_deck.yaml' "$REPO/.gitignore" 2>/dev/null \
    || echo 'config/lynx_deck.yaml' >> "$REPO/.gitignore"
  echo "  untracked config/lynx_deck.yaml so updates are not blocked"
fi

# --- media folder -----------------------------------------------------------
MEDIA=$(grep -E '^media_dir:' "$REPO/config/lynx_deck.yaml" | head -1 \
        | sed 's/^media_dir:[[:space:]]*//; s/^"//; s/"$//' )
MEDIA=${MEDIA:-/srv/lynxdeck/media}
if [ ! -d "$MEDIA" ]; then
  sudo mkdir -p "$MEDIA"
  sudo chown -R "$USER_NAME:$GROUP_NAME" "$(dirname "$MEDIA")"
  echo "  created $MEDIA"
fi

# --- permissions for the maintenance buttons --------------------------------
sudo tee /etc/sudoers.d/lynxdeck >/dev/null <<EOF
$USER_NAME ALL=(root) NOPASSWD: /sbin/shutdown, /usr/bin/systemctl restart lynx-deck, /usr/sbin/rfkill
EOF
sudo chmod 440 /etc/sudoers.d/lynxdeck
echo "  granted reboot, shutdown, restart and rfkill without a password"

# --- the service ------------------------------------------------------------
sudo tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=Lynx Deck - networked media player
After=network-online.target
Wants=network-online.target

[Service]
User=$USER_NAME
Group=$GROUP_NAME
SupplementaryGroups=video render audio input
WorkingDirectory=$REPO
ExecStart=/usr/bin/python3 -m lynxdeck --config $REPO/config/lynx_deck.yaml
Restart=always
RestartSec=3
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now lynx-deck
echo "  service installed and started"
echo

if ! grep -q 'video=HDMI' /boot/firmware/cmdline.txt 2>/dev/null; then
  echo "NOTE: no HDMI mode is set at boot, so the monitor's own preference"
  echo "      wins - usually 60 Hz. For a 1080p25 or 1080p50 plant, add the"
  echo "      matching line to /boot/firmware/cmdline.txt (one line) and reboot:"
  echo
  echo "  sudo sed -i '1 s/\$/ video=HDMI-A-1:1920x1080@50e/' /boot/firmware/cmdline.txt"
  echo
fi

sleep 2
systemctl --no-pager status lynx-deck | head -6
echo
echo "Web interface: http://$(hostname):8080"
