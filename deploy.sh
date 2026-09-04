#!/bin/bash
# ═══════════════════════════════════════════════════════════
# DNS Zone Manager — One-Click Deploy Script
# ═══════════════════════════════════════════════════════════
set -e

cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"

# ── Colors ──
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║   DNS Zone Manager — Docker Deploy Script     ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════╝${NC}"
echo ""

# ── Check Docker ──
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: Docker is not installed.${NC}"
    echo "  Install: https://docs.docker.com/engine/install/"
    exit 1
fi

if ! docker compose version &> /dev/null; then
    echo -e "${RED}Error: Docker Compose v2 is not installed.${NC}"
    echo "  Install: https://docs.docker.com/compose/install/"
    exit 1
fi

echo -e "${GREEN}✓ Docker $(docker --version)${NC}"
echo -e "${GREEN}✓ Docker Compose $(docker compose version --short)${NC}"
echo ""

# ── Select deploy mode ──
echo "Select deployment mode:"
echo -e "  ${CYAN}1) Lite${NC}  — SQLite, 2 containers, fast startup (recommended for testing/small teams)"
echo -e "  ${CYAN}2) Full${NC}  — PostgreSQL, 3 containers, production-grade"
echo ""
read -p "Choice [1]: " mode_choice
mode_choice=${mode_choice:-1}

if [ "$mode_choice" = "2" ]; then
    MODE="full"
    COMPOSE_FILE="docker-compose.yml"
else
    MODE="lite"
    COMPOSE_FILE="docker-compose.lite.yml"
fi

echo -e "\n${GREEN}→ Mode: ${MODE}${NC}\n"

# ── Generate .env if missing ──
if [ ! -f .env ]; then
    echo -e "${YELLOW}Creating .env from .env.example...${NC}"
    cp .env.example .env

    # Generate random JWT secret
    JWT_SECRET=$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | base64)
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s|change-this-to-a-random-secret-key|${JWT_SECRET}|g" .env
    else
        sed -i "s|change-this-to-a-random-secret-key|${JWT_SECRET}|g" .env
    fi
    echo -e "${GREEN}✓ .env created with random JWT secret${NC}"
else
    echo -e "${GREEN}✓ .env exists (keeping existing)${NC}"
fi

# ── Generate SSL certificates ──
echo -e "\n${YELLOW}Checking SSL certificates...${NC}"
if [ ! -f nginx/certs/server.crt ] || [ ! -f nginx/certs/server.key ]; then
    mkdir -p nginx/certs
    echo "Generating self-signed SSL certificates..."
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout nginx/certs/server.key \
        -out nginx/certs/server.crt \
        -subj "/C=CN/ST=Beijing/L=Beijing/O=DNS-Manager/CN=dns-manager.local" 2>/dev/null
    chmod 600 nginx/certs/server.key
    echo -e "${GREEN}✓ SSL certificates generated${NC}"
else
    echo -e "${GREEN}✓ SSL certificates exist${NC}"
fi

# ── Create directories ──
mkdir -p ssh_keys backups

# ── Check SSH keys ──
if [ -z "$(ls -A ssh_keys/ 2>/dev/null)" ]; then
    echo -e "\n${YELLOW}⚠ ssh_keys/ directory is empty.${NC}"
    echo "  Place your F5 SSH private key here (e.g., ssh_keys/id_ed25519)"
    echo "  Or configure F5_SSH_PASSWORD in .env for password auth"
    echo ""
    read -p "Continue anyway? [Y/n]: " cont
    if [[ "$cont" =~ ^[Nn] ]]; then
        echo "Aborted. Add SSH keys and re-run."
        exit 0
    fi
fi

# ── Build and start ──
echo -e "\n${YELLOW}Building Docker images...${NC}"
docker compose -f $COMPOSE_FILE build

echo -e "\n${YELLOW}Starting services...${NC}"
docker compose -f $COMPOSE_FILE up -d

# ── Wait for backend health ──
echo -e "\n${YELLOW}Waiting for backend to become healthy...${NC}"
for i in $(seq 1 30); do
    if docker compose -f $COMPOSE_FILE exec -T backend curl -sf http://localhost:8000/api/health &>/dev/null; then
        echo -e "${GREEN}✓ Backend is healthy${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${RED}Backend health check timeout. Check logs:${NC}"
        echo "  docker compose -f $COMPOSE_FILE logs backend"
        exit 1
    fi
    sleep 2
done

# ── Done ──
HTTPS_PORT=$(grep HTTPS_PORT .env 2>/dev/null | cut -d= -f2 | tr -d ' ')
HTTPS_PORT=${HTTPS_PORT:-443}

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║          Deployment Complete!                 ║${NC}"
echo -e "${CYAN}╠══════════════════════════════════════════════╣${NC}"
echo -e "${CYAN}║${NC}  Access:  https://localhost:${HTTPS_PORT}                ${CYAN}║${NC}"
echo -e "${CYAN}║${NC}  Login:   admin / admin123                   ${CYAN}║${NC}"
echo -e "${CYAN}║${NC}  Mode:    ${MODE}                              ${CYAN}║${NC}"
echo -e "${CYAN}╠══════════════════════════════════════════════╣${NC}"
echo -e "${CYAN}║${NC}  Logs:        docker compose -f ${COMPOSE_FILE} logs -f   ${CYAN}║${NC}"
echo -e "${CYAN}║${NC}  Stop:        docker compose -f ${COMPOSE_FILE} down     ${CYAN}║${NC}"
echo -e "${CYAN}║${NC}  Status:      docker compose -f ${COMPOSE_FILE} ps      ${CYAN}║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════╝${NC}"
