#!/bin/bash
set -e

echo "=== AI Agent Orchestration Platform Setup ==="

# Check for .env
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from .env.example"
    echo ">> IMPORTANT: Edit .env and add your OPENAI_API_KEY or ANTHROPIC_API_KEY"
    echo ""
fi

# Check if docker-compose is available
if command -v docker &>/dev/null && command -v docker-compose &>/dev/null; then
    echo "Starting with Docker Compose..."
    docker-compose up --build
    exit 0
fi

echo "Docker not found. Setting up locally..."

# Backend
echo ""
echo "--- Setting up backend ---"
cd backend

if ! command -v python3 &>/dev/null; then
    echo "ERROR: Python 3 is required"
    exit 1
fi

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

echo "Starting backend on http://localhost:8000"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!
cd ..

# Frontend
echo ""
echo "--- Setting up frontend ---"
cd frontend

if ! command -v node &>/dev/null; then
    echo "ERROR: Node.js is required for the frontend"
    kill $BACKEND_PID
    exit 1
fi

npm install
echo "Starting frontend on http://localhost:3000"
npm run dev &
FRONTEND_PID=$!
cd ..

echo ""
echo "=== Platform is running ==="
echo "  Frontend: http://localhost:3000"
echo "  Backend:  http://localhost:8000"
echo "  API docs: http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop"

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
