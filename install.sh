#!/usr/bin/env bash
# vaultdrop v2 installer
# Supports: Termux (Android), macOS, Arch/Ubuntu/Debian/Fedora/openSUSE
set -euo pipefail

VERSION="2.0.0"
INSTALL_DIR="${VAULTDROP_INSTALL_DIR:-$HOME/.local/share/vaultdrop}"
BIN_DIR="${VAULTDROP_BIN_DIR:-$HOME/.local/bin}"
DATA_DIR="${VAULTDROP_DIR:-$HOME/.vaultdrop}"

log()  { echo -e "\033[1;32m[vaultdrop]\033[0m $*"; }
warn() { echo -e "\033[1;33m[vaultdrop]\033[0m $*"; }
err()  { echo -e "\033[1;31m[vaultdrop]\033[0m $*" >&2; }

uninstall() {
  log "Uninstalling vaultdrop (data in $DATA_DIR is preserved)…"
  rm -f "$BIN_DIR/vaultdrop" "$BIN_DIR/vaultdrop-cli"
  rm -rf "$INSTALL_DIR"
  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user disable --now vaultdrop.service 2>/dev/null || true
    rm -f "$HOME/.config/systemd/user/vaultdrop.service"
  fi
  if [ -f "$HOME/Library/LaunchAgents/com.vaultdrop.server.plist" ]; then
    launchctl unload "$HOME/Library/LaunchAgents/com.vaultdrop.server.plist" 2>/dev/null || true
    rm -f "$HOME/Library/LaunchAgents/com.vaultdrop.server.plist"
  fi
  log "Uninstalled. Run 'rm -rf $DATA_DIR' if you also want to delete stored drops."
  exit 0
}

[ "${1:-}" = "--uninstall" ] && uninstall

# ── Detect environment ──────────────────────────────────────────────────
IS_TERMUX=0
[ -n "${TERMUX_VERSION:-}" ] && IS_TERMUX=1

OS="unknown"
case "$(uname -s)" in
  Darwin) OS="macos" ;;
  Linux)
    if [ "$IS_TERMUX" = "1" ]; then OS="termux";
    elif [ -f /etc/arch-release ]; then OS="arch";
    elif [ -f /etc/debian_version ]; then OS="debian";
    elif [ -f /etc/fedora-release ]; then OS="fedora";
    elif [ -f /etc/os-release ] && grep -qi opensuse /etc/os-release; then OS="opensuse";
    fi ;;
esac
log "Detected OS: $OS"

# ── Install system packages ─────────────────────────────────────────────
case "$OS" in
  termux) pkg install -y python git >/dev/null ;;
  macos) command -v brew >/dev/null 2>&1 && brew install python3 >/dev/null || warn "Homebrew not found; ensure python3 is installed." ;;
  arch) sudo pacman -Sy --noconfirm python python-pip >/dev/null ;;
  debian) sudo apt-get update -qq && sudo apt-get install -y python3 python3-venv python3-pip >/dev/null ;;
  fedora) sudo dnf install -y python3 python3-pip >/dev/null ;;
  opensuse) sudo zypper install -y python3 python3-pip >/dev/null ;;
  *) warn "Unrecognized OS — assuming python3/pip3 are already available." ;;
esac

mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$DATA_DIR"
cp -r server.py vaultdrop_cli.py requirements.txt templates static "$INSTALL_DIR/"

# ── Python environment ───────────────────────────────────────────────────
if [ "$IS_TERMUX" = "1" ]; then
  log "Termux detected — installing dependencies globally (no venv)."
  pip install -q --upgrade pip
  pip install -q -r "$INSTALL_DIR/requirements.txt"
  PYRUN="python"
else
  log "Creating virtual environment…"
  python3 -m venv "$INSTALL_DIR/venv"
  "$INSTALL_DIR/venv/bin/pip" install -q --upgrade pip
  "$INSTALL_DIR/venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"
  PYRUN="$INSTALL_DIR/venv/bin/python"
fi

# ── Wrapper binaries ──────────────────────────────────────────────────────
cat > "$BIN_DIR/vaultdrop" <<EOF
#!/usr/bin/env bash
exec "$PYRUN" "$INSTALL_DIR/server.py" "\$@"
EOF
cat > "$BIN_DIR/vaultdrop-cli" <<EOF
#!/usr/bin/env bash
exec "$PYRUN" "$INSTALL_DIR/vaultdrop_cli.py" "\$@"
EOF
chmod +x "$BIN_DIR/vaultdrop" "$BIN_DIR/vaultdrop-cli"

# ── Background service (production uses gunicorn, not the Flask dev server) ─
GUNICORN="$INSTALL_DIR/venv/bin/gunicorn"
if [ "$IS_TERMUX" = "1" ]; then
  mkdir -p "$HOME/.termux/boot"
  cat > "$HOME/.termux/boot/vaultdrop.sh" <<EOF
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
tmux new-session -d -s vaultdrop "cd $INSTALL_DIR && $PYRUN -m gunicorn -w 2 -b 127.0.0.1:5000 server:app"
EOF
  chmod +x "$HOME/.termux/boot/vaultdrop.sh"
  log "termux-boot autostart script installed (requires the Termux:Boot app)."
elif command -v systemctl >/dev/null 2>&1 && systemctl --user status >/dev/null 2>&1; then
  mkdir -p "$HOME/.config/systemd/user"
  cat > "$HOME/.config/systemd/user/vaultdrop.service" <<EOF
[Unit]
Description=vaultdrop v2 server
After=network.target

[Service]
WorkingDirectory=$INSTALL_DIR
Environment=VAULTDROP_DIR=$DATA_DIR
ExecStart=$GUNICORN -w 2 -b 127.0.0.1:5000 server:app
Restart=on-failure

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now vaultdrop.service
  log "systemd user service installed and started (127.0.0.1:5000)."
elif [ "$OS" = "macos" ]; then
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$HOME/Library/LaunchAgents/com.vaultdrop.server.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.vaultdrop.server</string>
  <key>ProgramArguments</key>
  <array><string>$GUNICORN</string><string>-w</string><string>2</string><string>-b</string><string>127.0.0.1:5000</string><string>server:app</string></array>
  <key>WorkingDirectory</key><string>$INSTALL_DIR</string>
  <key>EnvironmentVariables</key><dict><key>VAULTDROP_DIR</key><string>$DATA_DIR</string></dict>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
</dict></plist>
EOF
  launchctl load "$HOME/Library/LaunchAgents/com.vaultdrop.server.plist"
  log "launchd agent installed and started (127.0.0.1:5000)."
else
  warn "No supported init system detected — start manually with: vaultdrop serve"
fi

cat <<EOF

vaultdrop v$VERSION installed.

  CLI:      vaultdrop-cli seal <file>
  Server:   vaultdrop serve --host 0.0.0.0 --port 5000   (dev only)
  Data:     $DATA_DIR

⚠️  For a public-facing deployment, put a TLS reverse proxy (Caddy/nginx)
   in front of this and set VAULTDROP_TRUST_PROXY=1. See DEPLOY.md.

Uninstall: bash install.sh --uninstall
EOF
