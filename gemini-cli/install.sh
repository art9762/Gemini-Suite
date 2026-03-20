#!/bin/bash
set -e

# Gemini CLI Installer
# Installs gemini-cli to ~/.gemini-cli with virtualenv and creates wrapper at /usr/local/bin/gemini-cli

PYTHON_MIN_VERSION="3.10"
CLI_DIR="$HOME/.gemini-cli"
VENV_DIR="$CLI_DIR/venv"
BIN_DIR="/usr/local/bin"
CONFIG_FILE="$CLI_DIR/config.json"

echo "╔════════════════════════════════════════╗"
echo "║     Gemini CLI Installer v1.0          ║"
echo "╚════════════════════════════════════════╝"
echo

# Check Python version
echo "[*] Checking Python version..."
if ! command -v python3 &> /dev/null; then
    echo "✗ Python 3 is not installed"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "    Found Python $PYTHON_VERSION"

if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then
    echo "✗ Python 3.10 or higher is required (found $PYTHON_VERSION)"
    exit 1
fi

# Create CLI directory
echo "[*] Creating CLI directory at $CLI_DIR..."
mkdir -p "$CLI_DIR"

# Create virtualenv
echo "[*] Creating virtual environment..."
if [ -d "$VENV_DIR" ]; then
    echo "    Removing existing virtualenv..."
    rm -rf "$VENV_DIR"
fi
python3 -m venv "$VENV_DIR"
echo "    ✓ Virtualenv created"

# Activate virtualenv and install requirements
echo "[*] Installing dependencies..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip setuptools wheel > /dev/null 2>&1
pip install -r "$(dirname "$0")/requirements.txt" > /dev/null 2>&1
deactivate
echo "    ✓ Dependencies installed"

# Copy gemini_cli.py
echo "[*] Copying application files..."
cp "$(dirname "$0")/gemini_cli.py" "$CLI_DIR/"
chmod +x "$CLI_DIR/gemini_cli.py"
echo "    ✓ Application files copied"

# Create wrapper script
echo "[*] Creating wrapper script at $BIN_DIR/gemini-cli..."
cat > /tmp/gemini-cli-wrapper << 'EOF'
#!/bin/bash
source "$HOME/.gemini-cli/venv/bin/activate"
python3 "$HOME/.gemini-cli/gemini_cli.py" "$@"
EOF
chmod +x /tmp/gemini-cli-wrapper

if [ -w "$BIN_DIR" ]; then
    mv /tmp/gemini-cli-wrapper "$BIN_DIR/gemini-cli"
    echo "    ✓ Wrapper script installed"
else
    echo "    ⚠ Cannot write to $BIN_DIR (need sudo)"
    echo "    Run: sudo mv /tmp/gemini-cli-wrapper $BIN_DIR/gemini-cli"
    echo "    Then: sudo chmod +x $BIN_DIR/gemini-cli"
fi

# Create default config if not exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "[*] Creating default configuration..."
    mkdir -p "$CLI_DIR"
    cat > "$CONFIG_FILE" << 'EOF'
{
  "api_key": "",
  "model": "gemini-1.5-pro",
  "server_url": "ws://localhost:8000/ws/remote",
  "remote_enabled": false,
  "timeout": 30
}
EOF
    echo "    ✓ Default config created at $CONFIG_FILE"
fi

# Installation complete
echo
echo "╔════════════════════════════════════════╗"
echo "║   ✓ Installation Complete!             ║"
echo "╚════════════════════════════════════════╝"
echo
echo "Next steps:"
echo "  1. Get your Gemini API key from https://aistudio.google.com/app/apikeys"
echo "  2. Run: gemini-cli"
echo "  3. Type: /setup"
echo "  4. Paste your API key"
echo
echo "Usage:"
echo "  gemini-cli              Start interactive CLI"
echo "  gemini-cli /help        Show available commands"
echo
echo "Config file location: $CONFIG_FILE"
echo
