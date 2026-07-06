#!/usr/bin/env bash
# ============================================================
#  Flood Monitoring System — Linux/macOS Setup Script
#  Author: Deng Daniel Ayuen Kur (240103002054)
# ============================================================
set -euo pipefail

echo "============================================"
echo "  FloodWatch IoT — Server Setup"
echo "============================================"

cd "$(dirname "$0")/../server"

# ── Python version check ────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
  echo "[ERROR] Python 3 is required but not found."
  echo "        On Ubuntu/Debian: sudo apt install python3 python3-pip python3-venv"
  exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "[OK] Python $PY_VERSION found"

# ── Virtual environment ─────────────────────────────────────────
if [ ! -d "venv" ]; then
  echo "[...] Creating virtual environment..."
  python3 -m venv venv
fi
echo "[OK] Virtual environment ready"

# shellcheck disable=SC1091
source venv/bin/activate

# ── Install dependencies ────────────────────────────────────────
echo "[...] Installing Python packages..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo "[OK] Dependencies installed"

# ── Create .env from example if not present ────────────────────
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "[OK] .env created from .env.example"
  echo ""
  echo "  !! ACTION REQUIRED: Edit server/.env and fill in your values !!"
  echo "     Especially: SECRET_KEY, JWT_SECRET_KEY, SENSOR_API_KEY"
  echo ""
fi

# ── Create logs directory ───────────────────────────────────────
mkdir -p logs
echo "[OK] logs/ directory ready"

# ── Generate secret keys ────────────────────────────────────────
echo ""
echo "============================================"
echo "  Generated secret keys (paste into .env)"
echo "============================================"
echo ""
echo "SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
echo "JWT_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
echo "SENSOR_API_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
echo ""

# ── Firewall reminder ───────────────────────────────────────────
if command -v ufw &>/dev/null; then
  echo "[INFO] To open port 5000 in UFW: sudo ufw allow 5000/tcp"
fi

echo "============================================"
echo "  Setup complete!"
echo ""
echo "  To start the server:"
echo "    cd server"
echo "    source venv/bin/activate"
echo "    python app.py"
echo ""
echo "  Default login: admin / Admin@FloodWatch2025!"
echo "  CHANGE THE PASSWORD AFTER FIRST LOGIN!"
echo "============================================"
