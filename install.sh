#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════
#  vaultdrop — install.sh
#  Universal installer for Linux, macOS, and Termux
#
#  Supports:
#    Arch Linux / Manjaro          (pacman)
#    Ubuntu / Debian / Mint        (apt)
#    Fedora / RHEL / CentOS        (dnf)
#    openSUSE                      (zypper)
#    macOS (with Homebrew)         (brew)
#    Android Termux                (pkg)
#
#  Usage:
#    curl -fsSL https://raw.githubusercontent.com/franc417/vaultdrop/main/install.sh | bash
#
#    Or locally:
#    chmod +x install.sh && ./install.sh
#    ./install.sh --uninstall
#    ./install.sh --dir /opt/vaultdrop --port 8080
# ══════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Version ────────────────────────────────────────────────────────
VERSION="1.0.0"
REPO_RAW="https://raw.githubusercontent.com/franc417/vaultdrop/main"

# ── Defaults (overridable via flags) ───────────────────────────────
INSTALL_DIR=""       # resolved below based on environment
PORT="${VAULTDROP_PORT:-5000}"
MAX_MB="${VAULTDROP_MAX_MB:-100}"
TTL_H="${VAULTDROP_TTL_H:-24}"
UNINSTALL=0
START_NOW=0

# ── Colors ─────────────────────────────────────────────────────────
R=$'\033[0;31m'
G=$'\033[0;32m'
Y=$'\033[0;33m'
C=$'\033[0;36m'
W=$'\033[1;37m'
D=$'\033[2;37m'
BL=$'\033[1;34m'
M=$'\033[0;35m'
N=$'\033[0m'

# ── Helpers ────────────────────────────────────────────────────────
info()    { printf "  ${C}→${N} %s\n" "$*"; }
success() { printf "  ${G}✔${N} %s\n" "$*"; }
warn()    { printf "  ${Y}⚠${N} %s\n" "$*"; }
error()   { printf "  ${R}✗${N} %s\n" "$*" >&2; }
step()    { printf "\n  ${BL}[%s]${N} %s\n" "$1" "$2"; }
die()     { error "$*"; exit 1; }

print_banner() {
    printf "${BL}"
    cat << 'EOF'
╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║  ██╗   ██╗ █████╗ ██╗   ██╗██╗  ████████╗██████╗ ██████╗  ██████╗  ║
║  ██║   ██║██╔══██╗██║   ██║██║  ╚══██╔══╝██╔══██╗██╔══██╗██╔═══██╗ ║
║  ██║   ██║███████║██║   ██║██║     ██║   ██║  ██║██████╔╝██║   ██║ ║
║  ╚██╗ ██╔╝██╔══██║██║   ██║██║     ██║   ██║  ██║██╔══██╗██║   ██║ ║
║   ╚████╔╝ ██║  ██║╚██████╔╝███████╗██║   ██████╔╝██║  ██║╚██████╔╝ ║
║    ╚═══╝  ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝   ╚═════╝ ╚═╝  ╚═╝ ╚═════╝  ║
║                                                                  ║
║         One-Time Encrypted File Sharing  ·  v1.0.0              ║
╚══════════════════════════════════════════════════════════════════╝
EOF
    printf "${N}\n"
}

# ── Environment detection ──────────────────────────────────────────
detect_env() {
    IS_TERMUX=0
    IS_MACOS=0
    IS_LINUX=0
    PKG_MANAGER=""
    SUDO=""
    PYTHON=""
    PIP=""
    SERVICE_TYPE=""   # systemd | launchd | termux-boot | none

    # Termux (Android)
    if [[ -n "${TERMUX_VERSION:-}" ]] || [[ -d "/data/data/com.termux" ]]; then
        IS_TERMUX=1
        PKG_MANAGER="pkg"
        SUDO=""                 # no sudo in Termux
        INSTALL_DIR="${INSTALL_DIR:-$HOME/.vaultdrop/app}"
        SERVICE_TYPE="termux-boot"
        return
    fi

    # macOS
    if [[ "$(uname -s)" == "Darwin" ]]; then
        IS_MACOS=1
        PKG_MANAGER="brew"
        SUDO="sudo"
        INSTALL_DIR="${INSTALL_DIR:-/usr/local/lib/vaultdrop}"
        SERVICE_TYPE="launchd"
        return
    fi

    # Linux — detect distro
    IS_LINUX=1
    SUDO="sudo"
    INSTALL_DIR="${INSTALL_DIR:-/opt/vaultdrop}"
    SERVICE_TYPE="systemd"

    if command -v pacman &>/dev/null; then
        PKG_MANAGER="pacman"
    elif command -v apt-get &>/dev/null; then
        PKG_MANAGER="apt"
    elif command -v dnf &>/dev/null; then
        PKG_MANAGER="dnf"
    elif command -v zypper &>/dev/null; then
        PKG_MANAGER="zypper"
    else
        PKG_MANAGER="unknown"
    fi

    # Check if systemd is actually running
    if ! command -v systemctl &>/dev/null || ! systemctl is-system-running &>/dev/null 2>&1; then
        SERVICE_TYPE="none"
    fi
}

print_env_info() {
    printf "\n"
    if   [[ $IS_TERMUX -eq 1 ]]; then printf "  ${M}Platform :${N} Android / Termux\n"
    elif [[ $IS_MACOS  -eq 1 ]]; then printf "  ${M}Platform :${N} macOS\n"
    else
        local distro="Linux"
        [[ -f /etc/os-release ]] && distro=$(. /etc/os-release; echo "${PRETTY_NAME:-Linux}")
        printf "  ${M}Platform :${N} %s\n" "$distro"
    fi
    printf "  ${M}Package  :${N} %s\n"   "${PKG_MANAGER}"
    printf "  ${M}Install  :${N} %s\n"   "${INSTALL_DIR}"
    printf "  ${M}Port     :${N} %s\n"   "${PORT}"
    printf "  ${M}Service  :${N} %s\n\n" "${SERVICE_TYPE}"
}

# ── Argument parsing ───────────────────────────────────────────────
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --uninstall|-u) UNINSTALL=1 ;;
            --start)        START_NOW=1 ;;
            --dir)          INSTALL_DIR="$2"; shift ;;
            --port)         PORT="$2";        shift ;;
            --max-mb)       MAX_MB="$2";      shift ;;
            --help|-h)      print_usage; exit 0 ;;
            *) warn "Unknown flag: $1" ;;
        esac
        shift
    done
}

print_usage() {
    print_banner
    printf "  ${W}USAGE${N}\n"
    printf "    ${W}./install.sh [OPTIONS]${N}\n\n"
    printf "  ${W}OPTIONS${N}\n"
    printf "    ${C}--dir <path>${N}     Install location  (default varies by OS)\n"
    printf "    ${C}--port <n>${N}       Server port       (default: 5000)\n"
    printf "    ${C}--max-mb <n>${N}     Max upload MB     (default: 100)\n"
    printf "    ${C}--start${N}          Start server after install\n"
    printf "    ${C}--uninstall${N}      Remove vaultdrop completely\n\n"
    printf "  ${W}ENVIRONMENT VARS${N}\n"
    printf "    ${D}VAULTDROP_PORT${N}    Override default port\n"
    printf "    ${D}VAULTDROP_MAX_MB${N}  Override upload size limit\n"
    printf "    ${D}VAULTDROP_TTL_H${N}   Override default TTL\n\n"
}

# ── Dependency installation ────────────────────────────────────────
install_system_deps() {
    step "1/5" "Installing system dependencies..."

    case "$PKG_MANAGER" in

      pkg)   # Termux
        info "Updating Termux packages..."
        pkg update -y -q 2>/dev/null || true
        info "Installing python, git, curl..."
        pkg install -y python git curl 2>/dev/null
        # python-pip is bundled with Termux python
        ;;

      pacman)  # Arch / Manjaro
        info "Syncing pacman..."
        $SUDO pacman -Sy --noconfirm --needed python python-pip git curl 2>/dev/null
        ;;

      apt)  # Ubuntu / Debian / Mint
        info "Updating apt..."
        $SUDO apt-get update -qq 2>/dev/null
        info "Installing python3, pip, git, curl..."
        $SUDO apt-get install -y -qq \
            python3 python3-pip python3-venv \
            python3-cryptography \
            git curl 2>/dev/null
        ;;

      dnf)  # Fedora / RHEL / CentOS
        info "Installing python3, pip, git, curl..."
        $SUDO dnf install -y -q \
            python3 python3-pip \
            git curl 2>/dev/null
        ;;

      zypper)  # openSUSE
        info "Installing python3, pip, git, curl..."
        $SUDO zypper install -y -q \
            python3 python3-pip \
            git curl 2>/dev/null
        ;;

      brew)  # macOS
        if ! command -v brew &>/dev/null; then
            die "Homebrew not found. Install it first: https://brew.sh"
        fi
        info "Installing python, git via brew..."
        brew install python git 2>/dev/null || true
        ;;

      *)
        warn "Unknown package manager. Checking if python3 and pip are already available..."
        command -v python3 &>/dev/null || die "python3 not found. Please install it manually."
        ;;
    esac

    # Resolve python/pip paths
    PYTHON=$(command -v python3 || command -v python || die "python3 not found after install")
    PIP=$(command -v pip3 || command -v pip || echo "$PYTHON -m pip")

    success "System deps ready  ($(${PYTHON} --version 2>&1))"
}

# ── Download project files ─────────────────────────────────────────
download_files() {
    step "2/5" "Downloading vaultdrop..."

    # Create install dir
    if [[ $IS_TERMUX -eq 1 ]]; then
        mkdir -p "$INSTALL_DIR/templates" "$INSTALL_DIR/static"
    else
        $SUDO mkdir -p "$INSTALL_DIR/templates" "$INSTALL_DIR/static"
    fi

    # If running from a local clone (install.sh is next to server.py), copy directly
    local SCRIPT_DIR
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    if [[ -f "$SCRIPT_DIR/server.py" ]]; then
        info "Local install detected — copying from $SCRIPT_DIR"
        if [[ $IS_TERMUX -eq 1 ]]; then
            cp -r "$SCRIPT_DIR/." "$INSTALL_DIR/"
        else
            $SUDO cp -r "$SCRIPT_DIR/." "$INSTALL_DIR/"
        fi
    else
        # Remote install — pull from GitHub
        info "Fetching from GitHub..."
        local files=(
            "server.py"
            "vaultdrop_cli.py"
            "requirements.txt"
            "templates/index.html"
            "templates/drop.html"
            "templates/gone.html"
        )
        for f in "${files[@]}"; do
            local target="$INSTALL_DIR/$f"
            local dir
            dir="$(dirname "$target")"
            if [[ $IS_TERMUX -eq 1 ]]; then
                mkdir -p "$dir"
                curl -fsSL "$REPO_RAW/$f" -o "$target"
            else
                $SUDO mkdir -p "$dir"
                $SUDO curl -fsSL "$REPO_RAW/$f" -o "$target"
            fi
        done
    fi

    # Fix ownership on Linux/macOS so the running user can write store/DB
    if [[ $IS_LINUX -eq 1 ]] || [[ $IS_MACOS -eq 1 ]]; then
        $SUDO chown -R "$(id -un):$(id -gn)" "$INSTALL_DIR" 2>/dev/null || true
    fi

    success "Files installed → $INSTALL_DIR"
}

# ── Python venv + pip deps ─────────────────────────────────────────
setup_venv() {
    step "3/5" "Setting up Python environment..."

    local venv_dir="$INSTALL_DIR/.venv"

    if [[ $IS_TERMUX -eq 1 ]]; then
        # Termux: no venv needed, use system pip directly
        info "Installing Python packages (Termux global)..."
        pip install --quiet --upgrade pip 2>/dev/null || true
        pip install --quiet flask cryptography click requests 2>/dev/null
    else
        # All other platforms: isolated venv
        info "Creating venv at $venv_dir..."
        "$PYTHON" -m venv "$venv_dir" 2>/dev/null

        local venv_pip="$venv_dir/bin/pip"
        info "Installing Flask, cryptography, click, requests..."
        "$venv_pip" install --quiet --upgrade pip 2>/dev/null
        "$venv_pip" install --quiet flask cryptography click requests 2>/dev/null
    fi

    success "Python environment ready"
}

# ── Install CLI wrapper ────────────────────────────────────────────
install_cli() {
    step "4/5" "Installing CLI commands..."

    local venv_python
    if [[ $IS_TERMUX -eq 1 ]]; then
        venv_python="$PYTHON"
        local bin_dir="$HOME/.local/bin"
        mkdir -p "$bin_dir"
        local bin_target="$bin_dir"
    elif [[ $IS_MACOS -eq 1 ]]; then
        venv_python="$INSTALL_DIR/.venv/bin/python3"
        local bin_target="/usr/local/bin"
    else
        venv_python="$INSTALL_DIR/.venv/bin/python3"
        local bin_target="/usr/local/bin"
    fi

    # ── vaultdrop (server launcher) ──
    local server_wrapper
    server_wrapper=$(cat << EOF
#!/usr/bin/env bash
# vaultdrop server — generated by install.sh
VAULTDROP_DIR="\${VAULTDROP_DIR:-\$HOME/.vaultdrop}"
VAULTDROP_PORT="\${VAULTDROP_PORT:-${PORT}}"
VAULTDROP_MAX_MB="\${VAULTDROP_MAX_MB:-${MAX_MB}}"
VAULTDROP_TTL_H="\${VAULTDROP_TTL_H:-${TTL_H}}"
export VAULTDROP_DIR VAULTDROP_PORT VAULTDROP_MAX_MB VAULTDROP_TTL_H

exec ${venv_python} ${INSTALL_DIR}/server.py "\$@"
EOF
    )

    # ── vaultdrop-cli (seal/claim/status) ──
    local cli_wrapper
    cli_wrapper=$(cat << EOF
#!/usr/bin/env bash
# vaultdrop CLI — generated by install.sh
exec ${venv_python} ${INSTALL_DIR}/vaultdrop_cli.py "\$@"
EOF
    )

    if [[ $IS_TERMUX -eq 1 ]]; then
        printf '%s\n' "$server_wrapper" > "$bin_target/vaultdrop"
        printf '%s\n' "$cli_wrapper"    > "$bin_target/vaultdrop-cli"
        chmod +x "$bin_target/vaultdrop" "$bin_target/vaultdrop-cli"

        # Ensure ~/.local/bin is in PATH for this session
        export PATH="$bin_target:$PATH"

        # Add to .bashrc if not already there
        if ! grep -q 'vaultdrop' "$HOME/.bashrc" 2>/dev/null; then
            printf '\n# vaultdrop\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$HOME/.bashrc"
        fi
    else
        printf '%s\n' "$server_wrapper" | $SUDO tee "$bin_target/vaultdrop"     > /dev/null
        printf '%s\n' "$cli_wrapper"    | $SUDO tee "$bin_target/vaultdrop-cli" > /dev/null
        $SUDO chmod +x "$bin_target/vaultdrop" "$bin_target/vaultdrop-cli"
    fi

    success "CLI installed → ${bin_target}/vaultdrop"
    success "CLI installed → ${bin_target}/vaultdrop-cli"
}

# ── Service setup ──────────────────────────────────────────────────
setup_service() {
    step "5/5" "Setting up background service..."

    case "$SERVICE_TYPE" in

      # ── systemd (Linux) ──────────────────────────────────────────
      systemd)
        local unit_file="/etc/systemd/system/vaultdrop.service"
        local venv_python="$INSTALL_DIR/.venv/bin/python3"

        $SUDO tee "$unit_file" > /dev/null << EOF
[Unit]
Description=vaultdrop — one-time encrypted file sharing
After=network.target
Documentation=https://github.com/franc417/vaultdrop

[Service]
Type=simple
User=$(id -un)
WorkingDirectory=${INSTALL_DIR}
Environment="VAULTDROP_DIR=%h/.vaultdrop"
Environment="VAULTDROP_PORT=${PORT}"
Environment="VAULTDROP_MAX_MB=${MAX_MB}"
Environment="VAULTDROP_TTL_H=${TTL_H}"
ExecStart=${venv_python} ${INSTALL_DIR}/server.py
Restart=on-failure
RestartSec=5s
StandardOutput=journal
StandardError=journal
PrivateTmp=yes
NoNewPrivileges=yes

[Install]
WantedBy=multi-user.target
EOF

        $SUDO systemctl daemon-reload
        $SUDO systemctl enable vaultdrop.service 2>/dev/null || true

        success "systemd service installed (vaultdrop.service)"
        info "Start:   ${W}sudo systemctl start vaultdrop${N}"
        info "Logs:    ${W}journalctl -u vaultdrop -f${N}"
        info "Stop:    ${W}sudo systemctl stop vaultdrop${N}"

        if [[ $START_NOW -eq 1 ]]; then
            $SUDO systemctl start vaultdrop.service
            success "Service started → http://localhost:${PORT}"
        fi
        ;;

      # ── launchd (macOS) ──────────────────────────────────────────
      launchd)
        local plist_dir="$HOME/Library/LaunchAgents"
        local plist_file="$plist_dir/com.franc417.vaultdrop.plist"
        local venv_python="$INSTALL_DIR/.venv/bin/python3"
        local log_dir="$HOME/.vaultdrop/logs"
        mkdir -p "$plist_dir" "$log_dir"

        cat > "$plist_file" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.franc417.vaultdrop</string>
    <key>ProgramArguments</key>
    <array>
        <string>${venv_python}</string>
        <string>${INSTALL_DIR}/server.py</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>VAULTDROP_DIR</key>   <string>${HOME}/.vaultdrop</string>
        <key>VAULTDROP_PORT</key>  <string>${PORT}</string>
        <key>VAULTDROP_MAX_MB</key><string>${MAX_MB}</string>
        <key>VAULTDROP_TTL_H</key> <string>${TTL_H}</string>
    </dict>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>${log_dir}/vaultdrop.log</string>
    <key>StandardErrorPath</key><string>${log_dir}/vaultdrop.err</string>
    <key>WorkingDirectory</key><string>${INSTALL_DIR}</string>
</dict>
</plist>
EOF

        launchctl load "$plist_file" 2>/dev/null || true

        success "launchd agent installed"
        info "Start:   ${W}launchctl start com.franc417.vaultdrop${N}"
        info "Stop:    ${W}launchctl stop  com.franc417.vaultdrop${N}"
        info "Logs:    ${W}tail -f ~/.vaultdrop/logs/vaultdrop.log${N}"

        if [[ $START_NOW -eq 1 ]]; then
            launchctl start com.franc417.vaultdrop 2>/dev/null || true
            success "Service started → http://localhost:${PORT}"
        fi
        ;;

      # ── Termux boot ──────────────────────────────────────────────
      termux-boot)
        # Check if termux-boot is installed
        if pkg list-installed 2>/dev/null | grep -q "termux-boot"; then
            local boot_dir="$HOME/.termux/boot"
            mkdir -p "$boot_dir"
            cat > "$boot_dir/vaultdrop.sh" << EOF
#!/data/data/com.termux/files/usr/bin/bash
# vaultdrop auto-start on Termux boot
export VAULTDROP_DIR="\$HOME/.vaultdrop"
export VAULTDROP_PORT="${PORT}"
export VAULTDROP_MAX_MB="${MAX_MB}"
termux-wake-lock
cd ${INSTALL_DIR}
nohup python ${INSTALL_DIR}/server.py --host 0.0.0.0 >> "\$HOME/.vaultdrop/server.log" 2>&1 &
EOF
            chmod +x "$boot_dir/vaultdrop.sh"
            success "Termux-boot script installed → auto-starts on reboot"
        else
            info "termux-boot not installed. To auto-start on boot:"
            info "  ${W}pkg install termux-boot${N}"
            info "  Then re-run this installer."
        fi

        # For immediate use, also drop a tmux-based start script
        cat > "$HOME/.local/bin/vaultdrop-bg" << EOF
#!/data/data/com.termux/files/usr/bin/bash
# Start vaultdrop in a background tmux session
SESSION="vaultdrop"
if tmux has-session -t "\$SESSION" 2>/dev/null; then
    echo "Already running. Attach: tmux attach -t \$SESSION"
    exit 0
fi
tmux new-session -d -s "\$SESSION" \\
    "VAULTDROP_PORT=${PORT} python ${INSTALL_DIR}/server.py --host 0.0.0.0"
echo "Started in tmux session '\$SESSION'"
echo "Attach:  tmux attach -t \$SESSION"
echo "Detach:  Ctrl+B then D"
echo "Access:  http://localhost:${PORT}  or  http://\$(hostname -I | awk '{print \$1}'):${PORT}"
EOF
        chmod +x "$HOME/.local/bin/vaultdrop-bg"

        success "Background launcher → vaultdrop-bg"
        info "Start now:  ${W}vaultdrop-bg${N}  (runs in tmux, survives terminal close)"
        info "Start now:  ${W}vaultdrop${N}      (runs in foreground)"
        info "Access:     ${W}http://localhost:${PORT}${N}"
        ;;

      # ── No service manager ────────────────────────────────────────
      none)
        warn "No supported service manager found (systemd/launchd/termux-boot)."
        info "Run manually:  ${W}vaultdrop${N}"
        info "Background:    ${W}nohup vaultdrop &${N}"
        ;;
    esac
}

# ── Uninstall ──────────────────────────────────────────────────────
do_uninstall() {
    print_banner
    printf "  ${R}Uninstalling vaultdrop...${N}\n\n"

    local removed=0

    # Stop and remove service
    case "$SERVICE_TYPE" in
      systemd)
        if systemctl is-active --quiet vaultdrop 2>/dev/null; then
            $SUDO systemctl stop vaultdrop
            info "Service stopped"
        fi
        if [[ -f "/etc/systemd/system/vaultdrop.service" ]]; then
            $SUDO systemctl disable vaultdrop 2>/dev/null || true
            $SUDO rm -f "/etc/systemd/system/vaultdrop.service"
            $SUDO systemctl daemon-reload
            success "systemd service removed"
            removed=1
        fi
        ;;
      launchd)
        launchctl unload "$HOME/Library/LaunchAgents/com.franc417.vaultdrop.plist" 2>/dev/null || true
        rm -f "$HOME/Library/LaunchAgents/com.franc417.vaultdrop.plist"
        success "launchd agent removed"
        removed=1
        ;;
      termux-boot)
        rm -f "$HOME/.termux/boot/vaultdrop.sh"
        rm -f "$HOME/.local/bin/vaultdrop-bg"
        success "Termux boot script removed"
        removed=1
        ;;
    esac

    # Remove CLI wrappers
    for f in /usr/local/bin/vaultdrop /usr/local/bin/vaultdrop-cli \
             "$HOME/.local/bin/vaultdrop" "$HOME/.local/bin/vaultdrop-cli"; do
        if [[ -f "$f" ]]; then
            if [[ $IS_TERMUX -eq 1 ]]; then rm -f "$f"
            else $SUDO rm -f "$f" 2>/dev/null || rm -f "$f"; fi
            success "Removed $f"
            removed=1
        fi
    done

    # Remove install dir
    if [[ -d "$INSTALL_DIR" ]]; then
        if [[ $IS_TERMUX -eq 1 ]]; then rm -rf "$INSTALL_DIR"
        else $SUDO rm -rf "$INSTALL_DIR"; fi
        success "Removed $INSTALL_DIR"
        removed=1
    fi

    printf "\n"
    if [[ $removed -eq 1 ]]; then
        success "vaultdrop uninstalled."
        warn "Your data (~/.vaultdrop/) was NOT deleted. Remove manually if desired:"
        info "  rm -rf ~/.vaultdrop"
    else
        warn "Nothing to uninstall — vaultdrop was not found."
    fi
    printf "\n"
}

# ── Post-install summary ───────────────────────────────────────────
print_summary() {
    printf "\n"
    printf "${W}  ┌─ vaultdrop installed ──────────────────────────────────────┐${N}\n"
    printf "  │  ${D}Version :${N}  ${W}%s${N}\n" "$VERSION"
    printf "  │  ${D}Location:${N}  ${W}%s${N}\n" "$INSTALL_DIR"
    printf "  │  ${D}Port    :${N}  ${W}%s${N}\n" "$PORT"
    printf "  │  ${D}Data    :${N}  ${W}~/.vaultdrop/${N}\n"
    printf "  │\n"

    if [[ $IS_TERMUX -eq 1 ]]; then
        printf "  │  ${C}vaultdrop${N}           start server (foreground)\n"
        printf "  │  ${C}vaultdrop-bg${N}        start in tmux background\n"
        printf "  │  ${C}vaultdrop-cli seal file.pdf${N}\n"
        printf "  │  ${C}vaultdrop-cli claim <url>${N}\n"
        printf "  │  ${D}http://localhost:%s${N}  web UI\n" "$PORT"
        printf "  │  ${D}http://PHONE_IP:%s${N}   LAN access\n" "$PORT"
    elif [[ $SERVICE_TYPE == "systemd" ]]; then
        printf "  │  ${C}sudo systemctl start vaultdrop${N}   start\n"
        printf "  │  ${C}sudo systemctl stop  vaultdrop${N}   stop\n"
        printf "  │  ${C}journalctl -u vaultdrop -f${N}       logs\n"
        printf "  │  ${C}vaultdrop-cli seal file.pdf${N}\n"
        printf "  │  ${D}http://localhost:%s${N}\n" "$PORT"
    elif [[ $SERVICE_TYPE == "launchd" ]]; then
        printf "  │  ${C}launchctl start com.franc417.vaultdrop${N}\n"
        printf "  │  ${C}vaultdrop-cli seal file.pdf${N}\n"
        printf "  │  ${D}http://localhost:%s${N}\n" "$PORT"
    else
        printf "  │  ${C}vaultdrop${N}           start server\n"
        printf "  │  ${C}vaultdrop-cli seal file.pdf${N}\n"
        printf "  │  ${D}http://localhost:%s${N}\n" "$PORT"
    fi

    printf "  │\n"
    printf "  │  ${D}Uninstall:${N}  ${W}./install.sh --uninstall${N}\n"
    printf "${W}  └────────────────────────────────────────────────────────────┘${N}\n\n"
}

# ── Entry point ────────────────────────────────────────────────────
main() {
    parse_args "$@"
    detect_env

    print_banner
    print_env_info

    if [[ $UNINSTALL -eq 1 ]]; then
        do_uninstall
        exit 0
    fi

    # Confirm before installing system packages
    if [[ $IS_TERMUX -eq 0 ]]; then
        printf "  Continue with install? [Y/n] "
        read -r ans
        [[ -z "$ans" || "$ans" =~ ^[Yy]$ ]] || { info "Aborted."; exit 0; }
    fi

    install_system_deps
    download_files
    setup_venv
    install_cli
    setup_service
    print_summary
}

main "$@"
