#!/usr/bin/env bash
set -euo pipefail

# ─── Quantom Processing — One-Command Runner ───────────────────────────────────
# Prerequisites: Docker >= 20.10, Docker Compose >= 2.0
# Usage: ./run.sh
# ────────────────────────────────────────────────────────────────────────────────

API_URL="http://localhost:8000"
EXPECTED_SHOTS="${SHOTS:-1024}"
POLL_TIMEOUT=120
POLL_INTERVAL=2

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; exit 1; }

# ─── Prerequisite checks ───────────────────────────────────────────────────────
info "Checking prerequisites..."

command -v docker >/dev/null 2>&1 || fail "Docker is not installed. Please install Docker: https://docs.docker.com/get-docker/"
command -v curl   >/dev/null 2>&1 || fail "curl is not installed."

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif docker-compose version >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  fail "Docker Compose is not installed. Please install Docker Compose v2+."
fi

ok "Docker and Docker Compose found."

# ─── Check port availability ───────────────────────────────────────────────────
for port in 8000 5432 5672 15672; do
  if lsof -i ":$port" >/dev/null 2>&1; then
    warn "Port $port is already in use. This may cause conflicts."
  fi
done

# ─── Start the stack ────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_DIR="$SCRIPT_DIR/deploy"

if [ ! -f "$COMPOSE_DIR/docker-compose.yml" ]; then
  fail "docker-compose.yml not found at $COMPOSE_DIR. Are you running from the repo root?"
fi

info "Starting all services (this may take a few minutes on first run)..."
$COMPOSE -f "$COMPOSE_DIR/docker-compose.yml" up --build -d

# ─── Wait for API health ───────────────────────────────────────────────────────
info "Waiting for API to become healthy..."
elapsed=0
while [ $elapsed -lt 120 ]; do
  if curl -sf "$API_URL/healthz" >/dev/null 2>&1; then
    ok "API is healthy."
    break
  fi
  sleep 2
  elapsed=$((elapsed + 2))
done

if [ $elapsed -ge 120 ]; then
  fail "API did not become healthy within 120s. Check logs: $COMPOSE -f $COMPOSE_DIR/docker-compose.yml logs"
fi

# ─── Demo: submit a quantum circuit ────────────────────────────────────────────
echo ""
echo -e "${CYAN}════════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  Running Demo: Submit a Hadamard gate circuit (coin flip)     ${NC}"
echo -e "${CYAN}════════════════════════════════════════════════════════════════${NC}"
echo ""

QASM='OPENQASM 3;\ninclude \"stdgates.inc\";\nqubit[1] q;\nbit[1] c;\nh q[0];\nc[0] = measure q[0];'

info "POST /tasks — submitting circuit..."
RESPONSE=$(curl -sf -X POST "$API_URL/tasks" \
  -H "Content-Type: application/json" \
  -d "{\"qc\": \"$QASM\"}")

TASK_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['task_id'])" 2>/dev/null || true)

if [ -z "$TASK_ID" ]; then
  fail "Failed to submit task. Response: $RESPONSE"
fi

ok "Task submitted: $TASK_ID"

# ─── Poll for result ───────────────────────────────────────────────────────────
info "Polling GET /tasks/$TASK_ID ..."
elapsed=0
STATUS=""
while [ $elapsed -lt $POLL_TIMEOUT ]; do
  RESULT=$(curl -sf "$API_URL/tasks/$TASK_ID")
  STATUS=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])" 2>/dev/null || true)

  if [ "$STATUS" = "completed" ]; then
    break
  elif [ "$STATUS" = "error" ]; then
    fail "Task failed. Response: $RESULT"
  fi

  sleep $POLL_INTERVAL
  elapsed=$((elapsed + POLL_INTERVAL))
done

if [ "$STATUS" != "completed" ]; then
  fail "Task did not complete within ${POLL_TIMEOUT}s."
fi

ok "Task completed!"
echo ""
echo -e "${GREEN}Result:${NC}"
echo "$RESULT" | python3 -m json.tool
echo ""

# ─── Summary ────────────────────────────────────────────────────────────────────
echo -e "${CYAN}════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  All services are running!${NC}"
echo -e "${CYAN}════════════════════════════════════════════════════════════════${NC}"
echo ""
echo "  API:                  $API_URL"
echo "  RabbitMQ Management:  http://localhost:15672  (user/pass)"
echo "  PostgreSQL:           localhost:5432           (user/pass/quantom)"
echo ""
echo "  Try it yourself:"
echo "    curl -X POST $API_URL/tasks \\"
echo "      -H 'Content-Type: application/json' \\"
echo "      -d '{\"qc\": \"OPENQASM 3; include \\\\\"stdgates.inc\\\\\"; qubit[1] q; bit[1] c; h q[0]; c[0] = measure q[0];\"}'"
echo ""
echo "  Stop everything:"
echo "    $COMPOSE -f $COMPOSE_DIR/docker-compose.yml down"
echo ""
echo "  Stop and remove data:"
echo "    $COMPOSE -f $COMPOSE_DIR/docker-compose.yml down -v"
echo ""
