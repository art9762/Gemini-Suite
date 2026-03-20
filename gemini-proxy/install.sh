#!/bin/bash
set -e

# Gemini Proxy Installer
# Installs gemini-proxy as a systemd service

PYTHON_MIN_VERSION="3.10"
PROXY_DIR="/opt/gemini-proxy"
VENV_DIR="$PROXY_DIR/venv"
CONFIG_DIR="/etc/gemini-proxy"
CONFIG_FILE="$CONFIG_DIR/config.env"
SERVICE_FILE="/etc/systemd/system/gemini-proxy.service"
SERVICE_USER="gemini-proxy"

echo "╔════════════════════════════════════════╗"
echo "║   Gemini Proxy Installer v1.0          ║"
echo "╚════════════════════════════════════════╝"
echo

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "✗ This installer must be run with sudo"
    exit 1
fi

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

# Create service user
echo "[*] Creating service user..."
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd --system --shell /bin/false --home-dir /var/lib/gemini-proxy "$SERVICE_USER" 2>/dev/null || true
    echo "    ✓ User '$SERVICE_USER' created"
else
    echo "    ✓ User '$SERVICE_USER' already exists"
fi

# Create directories
echo "[*] Creating directories..."
mkdir -p "$PROXY_DIR"
mkdir -p "$CONFIG_DIR"
mkdir -p "/var/log/gemini-proxy"
chmod 755 "$PROXY_DIR"
chmod 755 "$CONFIG_DIR"
chmod 755 "/var/log/gemini-proxy"
echo "    ✓ Directories created"

# Create virtualenv
echo "[*] Creating virtual environment..."
if [ -d "$VENV_DIR" ]; then
    echo "    Removing existing virtualenv..."
    rm -rf "$VENV_DIR"
fi
python3 -m venv "$VENV_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$PROXY_DIR"
echo "    ✓ Virtualenv created"

# Install dependencies
echo "[*] Installing dependencies..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip setuptools wheel > /dev/null 2>&1
pip install -r "$(dirname "$0")/requirements.txt" > /dev/null 2>&1
deactivate
echo "    ✓ Dependencies installed"

# Copy application
echo "[*] Copying application..."
cp "$(dirname "$0")/gemini_proxy.py" "$PROXY_DIR/"
chmod +x "$PROXY_DIR/gemini_proxy.py"
chown -R "$SERVICE_USER:$SERVICE_USER" "$PROXY_DIR"
echo "    ✓ Application copied"

# Create config file
echo "[*] Creating configuration file..."
if [ ! -f "$CONFIG_FILE" ]; then
    cat > "$CONFIG_FILE" << 'EOF'
# Gemini Proxy Configuration
# Uncomment and set your values

# Your Gemini API key from https://aistudio.google.com/app/apikeys
# GEMINI_API_KEY=your_api_key_here

# Proxy API key for authentication (change this!)
PROXY_API_KEY=change-me-secret-key

# Server host (0.0.0.0 for all interfaces)
HOST=0.0.0.0

# Server port
PORT=8000
EOF
    chmod 600 "$CONFIG_FILE"
    echo "    ✓ Configuration file created at $CONFIG_FILE"
    echo "    ⚠ Please edit $CONFIG_FILE and set GEMINI_API_KEY"
else
    echo "    ✓ Configuration file already exists"
fi

chown "$SERVICE_USER:$SERVICE_USER" "$CONFIG_FILE"

# Copy systemd service file
echo "[*] Installing systemd service..."
cp "$(dirname "$0")/gemini-proxy.service" "$SERVICE_FILE"
chmod 644 "$SERVICE_FILE"
systemctl daemon-reload
echo "    ✓ Systemd service installed"

# Create log rotation config
echo "[*] Setting up log rotation..."
cat > "/etc/logrotate.d/gemini-proxy" << 'EOF'
/var/log/gemini-proxy/*.log {
    daily
    rotate 7
    compress
    delaycompress
    notifempty
    create 0640 gemini-proxy gemini-proxy
    sharedscripts
}
EOF
echo "    ✓ Log rotation configured"

echo
echo "╔════════════════════════════════════════╗"
echo "║   ✓ Installation Complete!             ║"
echo "╚════════════════════════════════════════╝"
echo
echo "Next steps:"
echo "  1. Edit config: sudo nano $CONFIG_FILE"
echo "  2. Set GEMINI_API_KEY and PROXY_API_KEY"
echo "  3. Start service: sudo systemctl start gemini-proxy"
echo "  4. Enable on boot: sudo systemctl enable gemini-proxy"
echo
echo "Useful commands:"
echo "  sudo systemctl start gemini-proxy      # Start the service"
echo "  sudo systemctl stop gemini-proxy       # Stop the service"
echo "  sudo systemctl restart gemini-proxy    # Restart the service"
echo "  sudo systemctl status gemini-proxy     # Check status"
echo "  journalctl -u gemini-proxy -f          # View logs"
echo
echo "Access:"
echo "  API: http://localhost:8000"
echo "  Dashboard: http://localhost:8000/dashboard"
echo "  API Docs: http://localhost:8000/docs"
echo "  Health: http://localhost:8000/health"
echo
echo "Installation directory: $PROXY_DIR"
echo "Configuration directory: $CONFIG_DIR"
echo "Log directory: /var/log/gemini-proxy"
echo
