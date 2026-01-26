#!/bin/bash
#
# Start Baarn Raadsinformatie services
#
# Gebruik: ./start.sh [commando]
#   start     - Start alle services (default)
#   stop      - Stop alle services
#   restart   - Herstart alle services
#   logs      - Bekijk logs
#   api       - Start alleen API server
#   sync      - Start alleen sync service
#   status    - Toon status van services

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Kleuren
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

case "${1:-start}" in
    start)
        echo -e "${CYAN}Alle services starten...${NC}"
        docker compose up -d api-server sync-service
        echo ""
        echo -e "${YELLOW}API Server: http://localhost:8000${NC}"
        echo -e "${YELLOW}API Docs:   http://localhost:8000/docs${NC}"
        echo ""
        docker compose ps
        ;;

    stop)
        echo -e "${CYAN}Services stoppen...${NC}"
        docker compose down
        echo -e "${GREEN}Services gestopt${NC}"
        ;;

    restart)
        echo -e "${CYAN}Services herstarten...${NC}"
        docker compose restart
        echo -e "${GREEN}Services herstart${NC}"
        ;;

    logs)
        echo -e "${CYAN}Logs bekijken (Ctrl+C om te stoppen)...${NC}"
        docker compose logs -f
        ;;

    api)
        echo -e "${CYAN}API server starten...${NC}"
        docker compose up -d api-server
        echo ""
        echo -e "${YELLOW}API Server: http://localhost:8000${NC}"
        echo -e "${YELLOW}API Docs:   http://localhost:8000/docs${NC}"
        ;;

    sync)
        echo -e "${CYAN}Sync service starten...${NC}"
        docker compose up -d sync-service
        echo -e "${GREEN}Sync service gestart${NC}"
        ;;

    status)
        docker compose ps
        ;;

    *)
        echo "Gebruik: $0 {start|stop|restart|logs|api|sync|status}"
        exit 1
        ;;
esac
