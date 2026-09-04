#!/bin/bash
# ========================================
# DNS Manager — Local Dev Startup
# Uses SQLite (no Docker/PostgreSQL needed)
# Starts both backend (8000) and frontend (3000)
# ========================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON="/Users/jyan/.workbuddy/binaries/python/envs/default/bin/python"
PIP="/Users/jyan/.workbuddy/binaries/python/envs/default/bin/pip"
NODE="/Users/jyan/.workbuddy/binaries/node/versions/22.22.2/bin/node"
NPX="/Users/jyan/.workbuddy/binaries/node/versions/22.22.2/bin/npx"

echo "=== DNS Manager Dev Startup ==="

# 1. Install Python deps
echo "[1/5] Installing Python dependencies..."
$PIP install -q -r backend/requirements.txt greenlet aiosqlite 2>&1 | tail -1

# 2. Init SQLite DB (only if not exists — preserves data across restarts)
echo "[2/5] Checking SQLite database..."
export USE_SQLITE=true
export PYTHONPATH=backend
if [ ! -f backend/dns_manager.db ]; then
    echo "  DB not found, running seed..."
    $PYTHON backend/seed.py
else
    echo "  DB exists (backend/dns_manager.db), skipping seed."
fi

# 3. Kill any existing processes
echo "[3/5] Cleaning up old processes..."
pkill -f "uvicorn app.main:app" 2>/dev/null || true
pkill -f "vite" 2>/dev/null || true
sleep 1

# 4. Start backend
echo "[4/5] Starting FastAPI backend on http://localhost:8000"
export USE_SQLITE=true
export F5_ACTIVE_HOST=172.18.1.202
export F5_SSH_PASSWORD='root@f5.com'
export PYTHONPATH=backend
$PYTHON -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# 5. Start frontend
echo "[5/5] Starting Vite frontend on http://localhost:3000"
cd "$SCRIPT_DIR/frontend"
$NPX vite --port 3000 &
FRONTEND_PID=$!
cd "$SCRIPT_DIR"

sleep 3
echo ""
echo "✓ Backend running:  http://localhost:8000"
echo "  API docs:         http://localhost:8000/docs"
echo "  Health check:     http://localhost:8000/api/health"
echo ""
echo "✓ Frontend running: http://localhost:3000"
echo ""
echo "  Login: admin / admin123"
echo ""
echo "Press Ctrl+C to stop both servers"

cleanup() {
    echo ""
    echo "Shutting down..."
    kill $BACKEND_PID 2>/dev/null || true
    kill $FRONTEND_PID 2>/dev/null || true
    exit 0
}
trap cleanup INT TERM

wait
