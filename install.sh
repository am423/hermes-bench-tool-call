#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Python venv + editable install: see scripts/bootstrap.sh (also invoked below).
echo "╔══════════════════════════════════════╗"
echo "║  HermesBench Installer          ║"
echo "╚══════════════════════════════════════╝"

# 1. Python check (3.11+)
if ! command -v python3 &>/dev/null; then
    echo "✗ Python 3 not found. Install Python 3.11+ first."
    exit 1
fi
PYVER=$(python3 -c 'import sys; print(sys.version_info >= (3, 11))')
if [ "$PYVER" != "True" ]; then
    echo "✗ Python 3.11+ required. Found: $(python3 --version 2>&1)"
    exit 1
fi
echo "✓ Python $(python3 --version 2>&1)"

# 2. Detect package manager
install_dep() {
    local dep="$1"
    if command -v "$dep" &>/dev/null; then
        echo "✓ $dep"
        return 0
    fi
    echo "→ Installing $dep..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get update -qq && sudo apt-get install -y -qq "$dep"
    elif command -v brew &>/dev/null; then
        brew install "$dep"
    elif command -v yum &>/dev/null; then
        sudo yum install -y "$dep"
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y "$dep"
    elif command -v pacman &>/dev/null; then
        sudo pacman -S --noconfirm "$dep"
    else
        echo "✗ Cannot auto-install $dep. Please install manually."
        return 1
    fi
    echo "✓ $dep installed"
}

# Check sudo availability
CAN_SUDO="no"
if [ "$(id -u)" = "0" ]; then
    CAN_SUDO="yes"
elif sudo -n true 2>/dev/null; then
    CAN_SUDO="yes"
fi

if [ "$CAN_SUDO" = "no" ] && ! command -v brew &>/dev/null; then
    echo "⚠  No sudo access and no brew. System deps may need manual install."
fi

# 3. Install system deps
for dep in tmux ffmpeg; do
    install_dep "$dep" || true
done

# xterm + Xvfb for video recording (optional)
for dep in xterm xvfb; do
    command -v "$dep" &>/dev/null && echo "✓ $dep" || echo "ℹ  $dep not found (optional: for video recording)"
done

# 4. Optional: agg (asciinema GIF renderer)
if ! command -v agg &>/dev/null; then
    echo "ℹ  agg not found (optional: for .cast → .gif rendering)"
    echo "   Install: cargo install agg  OR  https://github.com/asciinema/agg"
fi

# 5. Create venv + install
echo "→ Bootstrapping Python environment (scripts/bootstrap.sh)..."
bash "$SCRIPT_DIR/scripts/bootstrap.sh"
source .venv/bin/activate
echo "✓ Python dependencies installed"

# 6. Check for hermes-agent
HERMES_FOUND=false
for path in ~/.hermes/hermes-agent ~/hermes-agent "$SCRIPT_DIR/hermes-agent"; do
    if [ -d "$path" ] && [ -f "$path/run_agent.py" ]; then
        echo "✓ hermes-agent found at $path"
        HERMES_FOUND=true
        export HERMES_AGENT_PATH="$path"
        break
    fi
done
if [ "$HERMES_FOUND" = "false" ]; then
    echo "⚠  hermes-agent not found."
    echo "   Install: curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash"
    echo "   Or set:  export HERMES_AGENT_PATH=/path/to/hermes-agent"
    echo "   (Fake agent mode works without hermes-agent for development)"
fi

# 7. Doctor check
echo ""
echo "→ Running doctor check..."
python3 -m hermesbench doctor || true

# 8. Config template
if [ ! -f hermesbench.yaml ]; then
    cp hermesbench.yaml.example hermesbench.yaml
    echo "✓ Created hermesbench.yaml (edit to configure your model)"
fi

echo ""
echo "╔══════════════════════════════════════╗"
echo "║  Installation complete!              ║"
echo "╠══════════════════════════════════════╣"
echo "║  Next steps:                         ║"
echo "║  1. Edit hermesbench.yaml            ║"
echo "║  2. hermesbench serve                ║"
echo "║  3. hermesbench run --all            ║"
echo "╚══════════════════════════════════════╝"
