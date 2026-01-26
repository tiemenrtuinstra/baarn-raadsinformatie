#!/bin/bash
#
# Baarn Raadsinformatie - macOS/Linux Installatiescript
#
# One-liner installatie:
#   curl -fsSL https://raw.githubusercontent.com/tiemenrtuinstra/baarn-raadsinformatie/main/install.sh | bash
#
# Of lokaal:
#   ./install.sh [opties]
#
# Opties:
#   --skip-docker     Skip Docker installatie
#   --skip-build      Skip Docker build
#   --skip-ai         Skip AI configuratie
#   --skip-claude     Skip Claude Desktop/CLI installatie
#   --light           Lichtgewicht build (zonder embeddings)
#   --force           Overschrijf bestaande configuraties
#   --help            Toon help

set -e

# Configuratie
VERSION="2.3.5"
REPO="tiemenrtuinstra/baarn-raadsinformatie"
REGISTRY="ghcr.io"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/share/baarn-raadsinformatie}"
API_KEY="baarn-api-key-$RANDOM"

# Detecteer of we lokaal of remote draaien
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/mcp_server.py" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
    REMOTE_INSTALL=false
else
    SCRIPT_DIR="$INSTALL_DIR"
    REMOTE_INSTALL=true
fi

# Opties
SKIP_DOCKER=false
SKIP_BUILD=false
SKIP_AI=false
SKIP_CLAUDE=false
LIGHT_BUILD=false
FORCE=false

# Kleuren
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
GRAY='\033[0;90m'
NC='\033[0m' # No Color

# Output functies
print_step() {
    echo ""
    echo -e "${CYAN}==> ${NC}$1"
}

print_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_error() {
    echo -e "${RED}[X]${NC} $1"
}

print_info() {
    echo -e "    ${GRAY}$1${NC}"
}

# Download bestand van GitHub
download_file() {
    local file="$1"
    local dest="$2"
    local url="https://raw.githubusercontent.com/$REPO/main/$file"

    if command -v curl &> /dev/null; then
        curl -fsSL "$url" -o "$dest"
    elif command -v wget &> /dev/null; then
        wget -q "$url" -O "$dest"
    else
        print_error "curl of wget niet gevonden"
        return 1
    fi
}

# Download project bestanden van GitHub (voor remote install)
download_project_files() {
    print_step "Project bestanden downloaden van GitHub..."

    mkdir -p "$SCRIPT_DIR"
    cd "$SCRIPT_DIR"

    # Download essentiële bestanden
    local files=(
        "docker-compose.yml"
        "Dockerfile"
        ".env.example"
        "requirements.txt"
        "requirements-embeddings.txt"
        ".dockerignore"
    )

    for file in "${files[@]}"; do
        print_info "Downloading $file..."
        download_file "$file" "$file" || print_warning "Kon $file niet downloaden"
    done

    # Download directory structuren
    mkdir -p agents core providers analyzers shared data/documents data/cache logs

    # Download core Python bestanden
    local python_files=(
        "mcp_server.py"
        "api_server.py"
        "sync_service.py"
        "core/__init__.py"
        "core/config.py"
        "core/database.py"
        "core/document_index.py"
        "core/coalitie_tracker.py"
        "providers/__init__.py"
        "providers/notubiz_client.py"
        "providers/meeting_provider.py"
        "providers/document_provider.py"
        "providers/transcription_provider.py"
        "providers/summary_provider.py"
        "providers/dossier_provider.py"
        "analyzers/__init__.py"
        "analyzers/search_analyzer.py"
        "shared/__init__.py"
        "shared/logging_config.py"
        "agents/__init__.py"
    )

    for file in "${python_files[@]}"; do
        print_info "Downloading $file..."
        download_file "$file" "$file" 2>/dev/null || true
    done

    # Download agent YAML bestanden
    local agent_url="https://api.github.com/repos/$REPO/contents/agents"
    local agent_files=$(curl -fsSL "$agent_url" 2>/dev/null | grep '"name"' | grep '.yaml' | sed 's/.*"name": "\([^"]*\)".*/\1/')

    for agent in $agent_files; do
        print_info "Downloading agents/$agent..."
        download_file "agents/$agent" "agents/$agent" 2>/dev/null || true
    done

    print_success "Project bestanden gedownload naar $SCRIPT_DIR"
}

# Haal laatste versie op van GitHub
get_latest_version() {
    print_step "Laatste versie ophalen..."
    local release_url="https://api.github.com/repos/$REPO/releases/latest"

    if command -v curl &> /dev/null; then
        LATEST_VERSION=$(curl -fsSL "$release_url" 2>/dev/null | grep '"tag_name"' | sed -E 's/.*"([^"]+)".*/\1/')
    elif command -v wget &> /dev/null; then
        LATEST_VERSION=$(wget -qO- "$release_url" 2>/dev/null | grep '"tag_name"' | sed -E 's/.*"([^"]+)".*/\1/')
    fi

    if [ -z "$LATEST_VERSION" ]; then
        LATEST_VERSION="v$VERSION"
        print_warning "Kon laatste versie niet ophalen, gebruik v$VERSION"
    else
        print_success "Laatste versie: $LATEST_VERSION"
    fi
}

# Pull Docker image van registry (voor remote install)
pull_docker_image() {
    print_step "Docker image pullen van registry..."

    local image="$REGISTRY/$REPO"
    local tag="${LATEST_VERSION:-latest}"

    if [ "$LIGHT_BUILD" = true ]; then
        tag="${tag}-light"
        print_info "Light image: $image:$tag"
    else
        print_info "Full image: $image:$tag"
    fi

    if docker pull "$image:$tag" 2>/dev/null; then
        docker tag "$image:$tag" "baarn-raadsinformatie:latest"
        print_success "Docker image gepulled en getagd als baarn-raadsinformatie:latest"
        return 0
    else
        print_warning "Kon image niet pullen, probeer lokale build..."
        return 1
    fi
}

# Banner
show_banner() {
    echo ""
    echo -e "${CYAN}  ____                            ____                _     ${NC}"
    echo -e "${CYAN} | __ )  __ _  __ _ _ __ _ __    |  _ \\ __ _  __ _  __| |___ ${NC}"
    echo -e "${CYAN} |  _ \\ / _\` |/ _\` | '__| '_ \\   | |_) / _\` |/ _\` |/ _\` / __|${NC}"
    echo -e "${CYAN} | |_) | (_| | (_| | |  | | | |  |  _ < (_| | (_| | (_| \\__ \\${NC}"
    echo -e "${CYAN} |____/ \\__,_|\\__,_|_|  |_| |_|  |_| \\_\\__,_|\\__,_|\\__,_|___/${NC}"
    echo ""
    echo -e "  Raadsinformatie MCP Server - Installer v${VERSION}"
    echo -e "  ${GRAY}======================================================${NC}"
    echo ""
}

# Help
show_help() {
    echo "Gebruik: $0 [opties]"
    echo ""
    echo "Opties:"
    echo "  --skip-docker     Skip Docker installatie check"
    echo "  --skip-build      Skip Docker image build"
    echo "  --skip-ai         Skip AI tool configuratie"
    echo "  --skip-claude     Skip Claude Desktop/CLI installatie"
    echo "  --light           Lichtgewicht build (zonder embeddings)"
    echo "  --force           Overschrijf bestaande configuraties"
    echo "  --help            Toon deze help"
    echo ""
    echo "Voorbeelden:"
    echo "  $0                      # Volledige installatie"
    echo "  $0 --light              # Lichtgewicht build"
    echo "  $0 --skip-docker        # Skip Docker check"
    echo ""
}

# Parse argumenten
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --skip-docker)
                SKIP_DOCKER=true
                shift
                ;;
            --skip-build)
                SKIP_BUILD=true
                shift
                ;;
            --skip-ai)
                SKIP_AI=true
                shift
                ;;
            --skip-claude)
                SKIP_CLAUDE=true
                shift
                ;;
            --light)
                LIGHT_BUILD=true
                shift
                ;;
            --force)
                FORCE=true
                shift
                ;;
            --help)
                show_help
                exit 0
                ;;
            *)
                print_error "Onbekende optie: $1"
                show_help
                exit 1
                ;;
        esac
    done
}

# Detecteer OS
detect_os() {
    IS_CHROMEBOOK=false

    case "$(uname -s)" in
        Darwin)
            OS="macos"
            ;;
        Linux)
            OS="linux"
            # Detecteer distro
            if [ -f /etc/os-release ]; then
                . /etc/os-release
                DISTRO=$ID

                # Chromebook/ChromeOS detectie
                if [[ "$ID" == "chromeos" ]] || [[ "$ID_LIKE" == *"chromeos"* ]] || [ -d "/mnt/chromeos" ] || [ -f "/dev/.cros_milestone" ]; then
                    IS_CHROMEBOOK=true
                    print_info "Chromebook/ChromeOS (Crostini) gedetecteerd"
                fi
            fi
            ;;
        *)
            print_error "Niet-ondersteund besturingssysteem: $(uname -s)"
            exit 1
            ;;
    esac
    print_info "Gedetecteerd OS: $OS"
}

# Check of Docker is geinstalleerd
check_docker_installed() {
    if command -v docker &> /dev/null; then
        return 0
    else
        return 1
    fi
}

# Check of Docker draait
check_docker_running() {
    if docker info &> /dev/null; then
        return 0
    else
        return 1
    fi
}

# Installeer Docker op macOS
install_docker_macos() {
    print_step "Docker Desktop installeren voor macOS..."

    # Check voor Homebrew
    if command -v brew &> /dev/null; then
        print_info "Homebrew gevonden, Docker installeren via cask..."
        brew install --cask docker
        print_success "Docker Desktop geinstalleerd"

        print_info "Start Docker Desktop vanuit Applications..."
        open -a Docker

        # Wacht tot Docker is gestart
        print_info "Wachten tot Docker is gestart (max 120 seconden)..."
        local timeout=120
        local elapsed=0
        while ! check_docker_running && [ $elapsed -lt $timeout ]; do
            sleep 5
            elapsed=$((elapsed + 5))
            echo -n "."
        done
        echo ""

        if check_docker_running; then
            print_success "Docker is gestart"
            return 0
        else
            print_error "Docker kon niet worden gestart"
            return 1
        fi
    else
        print_warning "Homebrew niet gevonden"
        print_info "Installeer Docker Desktop handmatig van: https://www.docker.com/products/docker-desktop"
        print_info "Of installeer eerst Homebrew: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
        return 1
    fi
}

# Installeer Docker op Linux
install_docker_linux() {
    print_step "Docker installeren voor Linux..."

    case "$DISTRO" in
        ubuntu|debian)
            print_info "Ubuntu/Debian gedetecteerd, Docker installeren..."
            sudo apt-get update
            sudo apt-get install -y apt-transport-https ca-certificates curl gnupg lsb-release

            # Docker GPG key
            curl -fsSL https://download.docker.com/linux/$DISTRO/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg

            # Docker repository
            echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/$DISTRO $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

            # Install Docker
            sudo apt-get update
            sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

            # Add user to docker group
            sudo usermod -aG docker $USER
            print_warning "Log uit en weer in om Docker zonder sudo te gebruiken"
            ;;

        fedora|centos|rhel)
            print_info "Fedora/CentOS/RHEL gedetecteerd..."
            sudo dnf install -y dnf-plugins-core
            sudo dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo
            sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
            sudo systemctl start docker
            sudo systemctl enable docker
            sudo usermod -aG docker $USER
            ;;

        arch)
            print_info "Arch Linux gedetecteerd..."
            sudo pacman -S --noconfirm docker docker-compose
            sudo systemctl start docker
            sudo systemctl enable docker
            sudo usermod -aG docker $USER
            ;;

        *)
            print_warning "Distributie niet automatisch ondersteund: $DISTRO"
            print_info "Installeer Docker handmatig: https://docs.docker.com/engine/install/"
            return 1
            ;;
    esac

    print_success "Docker geinstalleerd"
    return 0
}

# Check of FFmpeg is geinstalleerd
check_ffmpeg_installed() {
    if command -v ffmpeg &> /dev/null; then
        return 0
    else
        return 1
    fi
}

# Installeer FFmpeg (vereist voor video/audio transcriptie)
install_ffmpeg() {
    print_step "FFmpeg installeren (vereist voor video/audio transcriptie)..."

    if check_ffmpeg_installed; then
        print_success "FFmpeg is al geinstalleerd"
        return 0
    fi

    case "$OS" in
        macos)
            if command -v brew &> /dev/null; then
                print_info "Installeren via Homebrew..."
                brew install ffmpeg
                if check_ffmpeg_installed; then
                    print_success "FFmpeg geinstalleerd"
                    return 0
                fi
            else
                print_warning "Homebrew niet gevonden"
                print_info "Installeer FFmpeg handmatig: brew install ffmpeg"
                return 1
            fi
            ;;
        linux)
            case "$DISTRO" in
                ubuntu|debian)
                    print_info "Installeren via apt..."
                    sudo apt-get update
                    sudo apt-get install -y ffmpeg
                    ;;
                fedora|centos|rhel)
                    print_info "Installeren via dnf..."
                    sudo dnf install -y ffmpeg
                    ;;
                arch)
                    print_info "Installeren via pacman..."
                    sudo pacman -S --noconfirm ffmpeg
                    ;;
                *)
                    print_warning "Distributie niet automatisch ondersteund: $DISTRO"
                    print_info "Installeer FFmpeg handmatig"
                    return 1
                    ;;
            esac

            if check_ffmpeg_installed; then
                print_success "FFmpeg geinstalleerd"
                return 0
            else
                print_error "FFmpeg installatie gefaald"
                return 1
            fi
            ;;
    esac
}

# Check of Node.js is geinstalleerd
check_nodejs_installed() {
    if command -v node &> /dev/null && command -v npm &> /dev/null; then
        return 0
    else
        return 1
    fi
}

# Installeer Node.js
install_nodejs() {
    print_step "Node.js installeren..."

    case "$OS" in
        macos)
            if command -v brew &> /dev/null; then
                brew install node
            else
                print_warning "Homebrew niet gevonden, installeer Node.js handmatig"
                print_info "Download: https://nodejs.org/en/download/"
                return 1
            fi
            ;;
        linux)
            case "$DISTRO" in
                ubuntu|debian)
                    # NodeSource LTS repository
                    curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
                    sudo apt-get install -y nodejs
                    ;;
                fedora|centos|rhel)
                    sudo dnf install -y nodejs npm
                    ;;
                arch)
                    sudo pacman -S --noconfirm nodejs npm
                    ;;
                *)
                    print_warning "Distributie niet automatisch ondersteund: $DISTRO"
                    print_info "Installeer Node.js handmatig: https://nodejs.org/en/download/"
                    return 1
                    ;;
            esac
            ;;
    esac

    if check_nodejs_installed; then
        print_success "Node.js geinstalleerd: $(node --version)"
        return 0
    else
        print_error "Node.js installatie gefaald"
        return 1
    fi
}

# Check of Claude Code CLI is geinstalleerd
check_claude_cli_installed() {
    if command -v claude &> /dev/null; then
        return 0
    else
        return 1
    fi
}

# Installeer Claude Code CLI via npm
install_claude_code_cli() {
    print_step "Claude Code CLI installeren..."

    # Check Node.js
    if ! check_nodejs_installed; then
        print_warning "Node.js niet gevonden, eerst installeren..."
        install_nodejs || return 1
    fi

    # Installeer Claude Code CLI globally
    print_info "Installeren via npm..."
    if npm install -g @anthropic-ai/claude-code 2>/dev/null; then
        print_success "Claude Code CLI geinstalleerd"
        print_info "Versie: $(claude --version 2>/dev/null || echo 'geinstalleerd')"
        return 0
    else
        # Probeer met sudo als normale install faalt
        print_info "Proberen met sudo..."
        if sudo npm install -g @anthropic-ai/claude-code 2>/dev/null; then
            print_success "Claude Code CLI geinstalleerd (met sudo)"
            return 0
        else
            print_error "Claude Code CLI installatie gefaald"
            print_info "Probeer handmatig: npm install -g @anthropic-ai/claude-code"
            return 1
        fi
    fi
}

# Check of Claude Desktop is geinstalleerd
check_claude_desktop_installed() {
    if [ "$OS" == "macos" ]; then
        if [ -d "/Applications/Claude.app" ]; then
            return 0
        fi
    else
        # Linux - check common locations
        if [ -f "$HOME/.local/share/applications/claude-desktop.desktop" ]; then
            return 0
        fi
    fi
    return 1
}

# Installeer Claude Desktop op macOS
install_claude_desktop_macos() {
    print_step "Claude Desktop installeren voor macOS..."

    if command -v brew &> /dev/null; then
        print_info "Installeren via Homebrew cask..."
        if brew install --cask claude 2>/dev/null; then
            print_success "Claude Desktop geinstalleerd"
            return 0
        else
            # Alternatief: direct downloaden
            print_warning "Homebrew cask niet beschikbaar, direct downloaden..."
        fi
    fi

    # Direct download als fallback
    print_info "Downloaden van Anthropic website..."
    local dmg_url="https://storage.googleapis.com/anthropic-public/claude-desktop/claude-desktop-latest-macos.dmg"
    local dmg_path="/tmp/claude-desktop.dmg"

    if curl -fsSL "$dmg_url" -o "$dmg_path" 2>/dev/null; then
        print_info "DMG bestand gedownload, installeren..."

        # Mount DMG
        hdiutil attach "$dmg_path" -quiet

        # Copy app
        cp -R "/Volumes/Claude/Claude.app" /Applications/ 2>/dev/null || \
            sudo cp -R "/Volumes/Claude/Claude.app" /Applications/

        # Unmount
        hdiutil detach "/Volumes/Claude" -quiet 2>/dev/null || true

        # Cleanup
        rm -f "$dmg_path"

        if [ -d "/Applications/Claude.app" ]; then
            print_success "Claude Desktop geinstalleerd in /Applications"
            return 0
        fi
    fi

    print_error "Claude Desktop installatie gefaald"
    print_info "Download handmatig van: https://claude.ai/download"
    return 1
}

# Installeer Claude (Desktop of CLI afhankelijk van platform)
install_claude() {
    print_step "Claude AI tool installeren..."

    # Check of al geinstalleerd
    if check_claude_desktop_installed; then
        print_success "Claude Desktop is al geinstalleerd"
        return 0
    fi

    if check_claude_cli_installed; then
        print_success "Claude Code CLI is al geinstalleerd"
        return 0
    fi

    # Installeer afhankelijk van platform
    case "$OS" in
        macos)
            # macOS: installeer Claude Desktop
            if install_claude_desktop_macos; then
                return 0
            else
                # Fallback naar CLI
                print_info "Fallback naar Claude Code CLI..."
                install_claude_code_cli
            fi
            ;;
        linux)
            # Linux/Chromebook: Claude Desktop niet beschikbaar, installeer CLI
            if [ "$IS_CHROMEBOOK" = true ]; then
                print_info "Chromebook gedetecteerd - Claude Desktop niet beschikbaar"
            else
                print_info "Linux gedetecteerd - Claude Desktop niet beschikbaar"
            fi
            print_info "Installeren van Claude Code CLI..."
            install_claude_code_cli
            ;;
    esac
}

# Maak .env bestand
init_env_file() {
    print_step "Environment bestand configureren..."

    local env_file="$SCRIPT_DIR/.env"
    local env_example="$SCRIPT_DIR/.env.example"

    if [ -f "$env_file" ] && [ "$FORCE" = false ]; then
        print_info ".env bestand bestaat al, wordt overgeslagen"
        print_info "Gebruik --force om te overschrijven"
        return
    fi

    if [ -f "$env_example" ]; then
        cp "$env_example" "$env_file"

        # Update API key
        if [[ "$OS" == "macos" ]]; then
            sed -i '' "s/API_KEY=baarn-api-key-change-me/API_KEY=$API_KEY/" "$env_file"
        else
            sed -i "s/API_KEY=baarn-api-key-change-me/API_KEY=$API_KEY/" "$env_file"
        fi

        print_success ".env bestand aangemaakt"
        print_info "API Key: $API_KEY"
    else
        print_warning ".env.example niet gevonden"
    fi
}

# Bouw Docker images
build_docker_images() {
    print_step "Docker images bouwen..."

    cd "$SCRIPT_DIR"

    if [ "$LIGHT_BUILD" = true ]; then
        print_info "Lichtgewicht build (zonder embeddings)..."
        docker compose --profile light build api-server-light
    else
        print_info "Volledige build (met embeddings, kan 5-10 minuten duren)..."
        docker compose build
    fi

    if [ $? -eq 0 ]; then
        print_success "Docker images gebouwd"
        return 0
    else
        print_error "Docker build gefaald"
        return 1
    fi
}

# Configureer Claude Desktop
configure_claude_desktop() {
    print_step "Claude Desktop configureren..."

    local claude_config_dir
    local claude_config

    if [ "$OS" == "macos" ]; then
        claude_config_dir="$HOME/Library/Application Support/Claude"
    else
        claude_config_dir="$HOME/.config/Claude"
    fi
    claude_config="$claude_config_dir/claude_desktop_config.json"

    mkdir -p "$claude_config_dir"

    local project_path="$SCRIPT_DIR"

    # Maak JSON config
    local mcp_config=$(cat <<EOF
{
  "mcpServers": {
    "baarn-raadsinformatie": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "--env-file", "$project_path/.env",
        "-v", "$project_path/data:/app/data",
        "-v", "$project_path/logs:/app/logs",
        "baarn-raadsinformatie:latest"
      ]
    }
  }
}
EOF
)

    if [ -f "$claude_config" ]; then
        # Merge met bestaande config (vereist jq)
        if command -v jq &> /dev/null; then
            local existing_config=$(cat "$claude_config")
            local merged=$(echo "$existing_config" | jq --argjson new "$mcp_config" '.mcpServers = (.mcpServers // {}) + $new.mcpServers')
            echo "$merged" > "$claude_config"
            print_success "Claude Desktop configuratie bijgewerkt"
        else
            print_warning "jq niet gevonden, overschrijf bestaande config"
            echo "$mcp_config" > "$claude_config"
        fi
    else
        echo "$mcp_config" > "$claude_config"
        print_success "Claude Desktop configuratie aangemaakt"
    fi

    print_info "Config: $claude_config"
}

# Configureer Cursor IDE
configure_cursor_ide() {
    print_step "Cursor IDE configureren..."

    local cursor_dir="$SCRIPT_DIR/.cursor"
    local cursor_config="$cursor_dir/mcp.json"

    mkdir -p "$cursor_dir"

    cat > "$cursor_config" <<EOF
{
  "mcpServers": {
    "baarn-raadsinformatie": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "--env-file", "$SCRIPT_DIR/.env",
        "-v", "$SCRIPT_DIR/data:/app/data",
        "-v", "$SCRIPT_DIR/logs:/app/logs",
        "baarn-raadsinformatie:latest"
      ]
    }
  }
}
EOF

    print_success "Cursor IDE configuratie aangemaakt"
    print_info "Config: $cursor_config"
}

# Configureer Continue.dev
configure_continue_dev() {
    print_step "Continue.dev configureren..."

    local continue_dir="$SCRIPT_DIR/.continue"
    local continue_config="$continue_dir/config.json"

    mkdir -p "$continue_dir"

    cat > "$continue_config" <<EOF
{
  "models": [
    {
      "title": "Claude 3.5 Sonnet",
      "provider": "anthropic",
      "model": "claude-3-5-sonnet-20241022",
      "apiKey": "\${ANTHROPIC_API_KEY}"
    },
    {
      "title": "GPT-4o",
      "provider": "openai",
      "model": "gpt-4o",
      "apiKey": "\${OPENAI_API_KEY}"
    },
    {
      "title": "Ollama Local",
      "provider": "ollama",
      "model": "llama3.2"
    }
  ],
  "tabAutocompleteModel": {
    "title": "Starcoder",
    "provider": "ollama",
    "model": "starcoder2:3b"
  },
  "experimental": {
    "modelContextProtocolServers": [
      {
        "transport": {
          "type": "stdio",
          "command": "docker",
          "args": [
            "run", "-i", "--rm",
            "--env-file", "$SCRIPT_DIR/.env",
            "-v", "$SCRIPT_DIR/data:/app/data",
            "-v", "$SCRIPT_DIR/logs:/app/logs",
            "baarn-raadsinformatie:latest"
          ]
        }
      }
    ]
  },
  "customCommands": [
    {
      "name": "baarn-vergaderingen",
      "description": "Zoek vergaderingen in Baarn",
      "prompt": "Gebruik de MCP tools om vergaderingen op te halen. {{{ input }}}"
    },
    {
      "name": "baarn-zoek",
      "description": "Zoek in politieke documenten",
      "prompt": "Gebruik search_documents of semantic_search om te zoeken naar: {{{ input }}}"
    }
  ]
}
EOF

    print_success "Continue.dev configuratie aangemaakt"
    print_info "Config: $continue_config"
}

# Configureer Zed Editor
configure_zed_editor() {
    print_step "Zed Editor configureren..."

    local zed_dir="$SCRIPT_DIR/.zed"
    local zed_config="$zed_dir/settings.json"

    mkdir -p "$zed_dir"

    cat > "$zed_config" <<EOF
{
  "context_servers": {
    "baarn-raadsinformatie": {
      "command": {
        "path": "docker",
        "args": [
          "run", "-i", "--rm",
          "--env-file", "$SCRIPT_DIR/.env",
          "-v", "$SCRIPT_DIR/data:/app/data",
          "-v", "$SCRIPT_DIR/logs:/app/logs",
          "baarn-raadsinformatie:latest"
        ]
      }
    }
  },
  "assistant": {
    "default_model": {
      "provider": "anthropic",
      "model": "claude-3-5-sonnet-20241022"
    },
    "version": "2"
  }
}
EOF

    print_success "Zed Editor configuratie aangemaakt"
    print_info "Config: $zed_config"
}

# Configureer Windsurf
configure_windsurf() {
    print_step "Windsurf configureren..."

    local windsurf_dir="$SCRIPT_DIR/.windsurf"
    local windsurf_config="$windsurf_dir/mcp.json"

    mkdir -p "$windsurf_dir"

    cat > "$windsurf_config" <<EOF
{
  "mcpServers": {
    "baarn-raadsinformatie": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "--env-file", "$SCRIPT_DIR/.env",
        "-v", "$SCRIPT_DIR/data:/app/data",
        "-v", "$SCRIPT_DIR/logs:/app/logs",
        "baarn-raadsinformatie:latest"
      ],
      "description": "Baarn Raadsinformatie MCP Server"
    }
  }
}
EOF

    print_success "Windsurf configuratie aangemaakt"
    print_info "Config: $windsurf_config"
}

# Detecteer geinstalleerde AI tools
detect_ai_tools() {
    print_step "Gedetecteerde AI tools..."

    local tools=()

    # Claude Desktop
    if [ "$OS" == "macos" ]; then
        if [ -d "/Applications/Claude.app" ]; then
            echo -e "  [${GREEN}V${NC}] Claude Desktop"
            print_info "     /Applications/Claude.app"
            tools+=("claude")
        else
            echo -e "  [ ] ${GRAY}Claude Desktop${NC}"
        fi
    else
        # Linux - check common locations
        if [ -f "$HOME/.local/share/applications/claude-desktop.desktop" ] || command -v claude &> /dev/null; then
            echo -e "  [${GREEN}V${NC}] Claude Desktop"
            tools+=("claude")
        else
            echo -e "  [ ] ${GRAY}Claude Desktop${NC}"
        fi
    fi

    # Cursor
    if [ "$OS" == "macos" ]; then
        if [ -d "/Applications/Cursor.app" ]; then
            echo -e "  [${GREEN}V${NC}] Cursor IDE"
            print_info "     /Applications/Cursor.app"
            tools+=("cursor")
        else
            echo -e "  [ ] ${GRAY}Cursor IDE${NC}"
        fi
    else
        if command -v cursor &> /dev/null || [ -d "$HOME/.local/share/cursor" ]; then
            echo -e "  [${GREEN}V${NC}] Cursor IDE"
            tools+=("cursor")
        else
            echo -e "  [ ] ${GRAY}Cursor IDE${NC}"
        fi
    fi

    # VS Code
    if command -v code &> /dev/null; then
        echo -e "  [${GREEN}V${NC}] VS Code"
        tools+=("vscode")
    else
        echo -e "  [ ] ${GRAY}VS Code${NC}"
    fi

    # Continue.dev (VS Code extension)
    local continue_ext_dir
    if [ "$OS" == "macos" ]; then
        continue_ext_dir="$HOME/.vscode/extensions"
    else
        continue_ext_dir="$HOME/.vscode/extensions"
    fi
    if [ -d "$continue_ext_dir" ] && ls "$continue_ext_dir" | grep -q "continue."; then
        echo -e "  [${GREEN}V${NC}] Continue.dev"
        tools+=("continue")
    else
        echo -e "  [ ] ${GRAY}Continue.dev${NC}"
    fi

    # Ollama
    if command -v ollama &> /dev/null; then
        echo -e "  [${GREEN}V${NC}] Ollama"
        print_info "     $(which ollama)"
        tools+=("ollama")
    else
        echo -e "  [ ] ${GRAY}Ollama${NC}"
    fi

    # GitHub Copilot CLI
    if command -v github-copilot-cli &> /dev/null; then
        echo -e "  [${GREEN}V${NC}] GitHub Copilot CLI"
        tools+=("copilot-cli")
    else
        echo -e "  [ ] ${GRAY}GitHub Copilot CLI${NC}"
    fi

    # Cline (Claude Dev) - VS Code extension
    if [ -d "$HOME/.vscode/extensions" ] && ls "$HOME/.vscode/extensions" 2>/dev/null | grep -qE "saoudrizwan.claude-dev|cline."; then
        echo -e "  [${GREEN}V${NC}] Cline (Claude Dev)"
        tools+=("cline")
    else
        echo -e "  [ ] ${GRAY}Cline (Claude Dev)${NC}"
    fi

    # Aider
    if command -v aider &> /dev/null; then
        echo -e "  [${GREEN}V${NC}] Aider"
        print_info "     $(which aider)"
        tools+=("aider")
    else
        echo -e "  [ ] ${GRAY}Aider${NC}"
    fi

    # Zed Editor
    if [ "$OS" == "macos" ]; then
        if [ -d "/Applications/Zed.app" ]; then
            echo -e "  [${GREEN}V${NC}] Zed Editor"
            print_info "     /Applications/Zed.app"
            tools+=("zed")
        else
            echo -e "  [ ] ${GRAY}Zed Editor${NC}"
        fi
    else
        if command -v zed &> /dev/null || [ -d "$HOME/.local/share/zed" ]; then
            echo -e "  [${GREEN}V${NC}] Zed Editor"
            tools+=("zed")
        else
            echo -e "  [ ] ${GRAY}Zed Editor${NC}"
        fi
    fi

    # Windsurf (Codeium)
    if [ "$OS" == "macos" ]; then
        if [ -d "/Applications/Windsurf.app" ]; then
            echo -e "  [${GREEN}V${NC}] Windsurf"
            print_info "     /Applications/Windsurf.app"
            tools+=("windsurf")
        else
            echo -e "  [ ] ${GRAY}Windsurf${NC}"
        fi
    else
        if command -v windsurf &> /dev/null || [ -d "$HOME/.local/share/windsurf" ]; then
            echo -e "  [${GREEN}V${NC}] Windsurf"
            tools+=("windsurf")
        else
            echo -e "  [ ] ${GRAY}Windsurf${NC}"
        fi
    fi

    # Claude Code CLI (Anthropic)
    if command -v claude &> /dev/null; then
        echo -e "  [${GREEN}V${NC}] Claude Code CLI"
        print_info "     $(which claude)"
        tools+=("claude-cli")
    else
        echo -e "  [ ] ${GRAY}Claude Code CLI${NC}"
    fi

    # OpenAI Codex CLI
    if command -v codex &> /dev/null; then
        echo -e "  [${GREEN}V${NC}] OpenAI Codex CLI"
        print_info "     $(which codex)"
        tools+=("codex-cli")
    else
        echo -e "  [ ] ${GRAY}OpenAI Codex CLI${NC}"
    fi

    DETECTED_TOOLS="${tools[*]}"
}

# Registreer MCP server bij Claude Code CLI
register_claude_code_mcp() {
    print_step "Claude Code CLI MCP registreren..."

    # Verwijder eerst bestaande registratie (ignore errors)
    claude mcp remove baarn-raadsinformatie 2>/dev/null || true

    # Registreer de MCP server
    if claude mcp add baarn-raadsinformatie -- docker run -i --rm \
        --env-file "$SCRIPT_DIR/.env" \
        -v "$SCRIPT_DIR/data:/app/data" \
        -v "$SCRIPT_DIR/logs:/app/logs" \
        baarn-raadsinformatie:latest 2>/dev/null; then
        print_success "Claude Code CLI MCP geregistreerd"
        print_info "Gebruik: claude (start sessie met MCP tools)"
        return 0
    else
        print_warning "Claude Code CLI MCP registratie gefaald"
        return 1
    fi
}

# Registreer MCP server bij OpenAI Codex CLI
register_codex_mcp() {
    print_step "OpenAI Codex CLI MCP registreren..."

    # Verwijder eerst bestaande registratie (ignore errors)
    codex mcp remove baarn-raadsinformatie 2>/dev/null || true

    # Registreer de MCP server
    if codex mcp add baarn-raadsinformatie -- docker run -i --rm \
        --env-file "$SCRIPT_DIR/.env" \
        -v "$SCRIPT_DIR/data:/app/data" \
        -v "$SCRIPT_DIR/logs:/app/logs" \
        baarn-raadsinformatie:latest 2>/dev/null; then
        print_success "OpenAI Codex CLI MCP geregistreerd"
        print_info "Gebruik: codex (start sessie met MCP tools)"
        return 0
    else
        print_warning "OpenAI Codex CLI MCP registratie gefaald"
        return 1
    fi
}

# Start services
start_services() {
    print_step "Docker services starten..."

    cd "$SCRIPT_DIR"

    docker compose up -d api-server sync-service

    if [ $? -eq 0 ]; then
        print_success "Services gestart"
        sleep 3
        docker compose ps
        return 0
    else
        print_error "Services konden niet worden gestart"
        return 1
    fi
}

# Toon samenvatting
show_summary() {
    echo ""
    echo -e "${CYAN}============================================================${NC}"
    echo -e "${GREEN}  Installatie voltooid!${NC}"
    echo -e "${CYAN}============================================================${NC}"
    echo ""

    if [ "$REMOTE_INSTALL" = true ]; then
        echo -e "  Installatie dir: ${YELLOW}$SCRIPT_DIR${NC}"
        echo ""
    fi

    echo -e "  API Server:     ${YELLOW}http://localhost:8000${NC}"
    echo -e "  API Docs:       ${YELLOW}http://localhost:8000/docs${NC}"
    echo -e "  API Key:        ${YELLOW}$API_KEY${NC}"
    echo ""

    echo -e "  ${NC}Volgende stappen:${NC}"
    echo -e "  ${GRAY}1. Herstart Claude Desktop om de MCP server te laden${NC}"
    echo -e "  ${GRAY}2. Test de API: curl http://localhost:8000/health${NC}"
    echo ""

    echo -e "  ${NC}Handige commando's:${NC}"
    echo -e "  ${GRAY}cd $SCRIPT_DIR${NC}"
    echo -e "  ${GRAY}docker compose logs -f          # Bekijk logs${NC}"
    echo -e "  ${GRAY}docker compose restart          # Herstart services${NC}"
    echo -e "  ${GRAY}docker compose down             # Stop services${NC}"
    echo ""
}

# Hoofdprogramma
main() {
    show_banner
    parse_args "$@"
    detect_os

    # Remote install: download project bestanden eerst
    if [ "$REMOTE_INSTALL" = true ]; then
        print_info "Remote installatie gedetecteerd"
        get_latest_version
        download_project_files
    fi

    # Stap 1: Docker
    if [ "$SKIP_DOCKER" = false ]; then
        if check_docker_installed; then
            print_success "Docker is geinstalleerd"

            if ! check_docker_running; then
                print_warning "Docker draait niet"
                if [ "$OS" == "macos" ]; then
                    print_info "Start Docker Desktop vanuit Applications..."
                    open -a Docker 2>/dev/null || true
                    sleep 10
                else
                    print_info "Start Docker service..."
                    sudo systemctl start docker 2>/dev/null || true
                fi

                if ! check_docker_running; then
                    print_error "Kan Docker niet starten. Start Docker handmatig en voer dit script opnieuw uit."
                    exit 1
                fi
            fi
            print_success "Docker is actief"
        else
            print_warning "Docker niet gevonden, installeren..."

            if [ "$OS" == "macos" ]; then
                install_docker_macos || {
                    print_error "Docker installatie gefaald"
                    exit 1
                }
            else
                install_docker_linux || {
                    print_error "Docker installatie gefaald"
                    exit 1
                }
            fi
        fi
    fi

    # Stap 2: Environment
    init_env_file

    # Stap 3: Data directories
    print_step "Data directories aanmaken..."
    mkdir -p "$SCRIPT_DIR/data/documents"
    mkdir -p "$SCRIPT_DIR/data/cache"
    mkdir -p "$SCRIPT_DIR/data/audio"
    mkdir -p "$SCRIPT_DIR/logs"
    print_success "Directories aangemaakt"

    # Stap 3b: FFmpeg (vereist voor video/audio transcriptie)
    install_ffmpeg

    # Stap 4: Docker image (pull of build)
    if [ "$SKIP_BUILD" = false ]; then
        if [ "$REMOTE_INSTALL" = true ]; then
            # Remote install: probeer eerst te pullen, anders bouwen
            pull_docker_image || build_docker_images || {
                print_error "Docker image niet beschikbaar"
                exit 1
            }
        else
            # Lokale install: altijd bouwen
            build_docker_images || {
                print_error "Docker build gefaald"
                exit 1
            }
        fi
    fi

    # Stap 5: Claude installeren (indien nodig en niet overgeslagen)
    if [ "$SKIP_AI" = false ] && [ "$SKIP_CLAUDE" = false ]; then
        install_claude
    elif [ "$SKIP_CLAUDE" = true ]; then
        print_info "Claude installatie overgeslagen (--skip-claude)"
    fi

    # Stap 6: Detecteer AI tools
    detect_ai_tools

    # Stap 7: Configureer AI tools
    if [ "$SKIP_AI" = false ]; then
        # Altijd lokale configs maken voor alle AI tools
        configure_cursor_ide
        configure_continue_dev
        configure_zed_editor
        configure_windsurf

        # Claude Desktop config (altijd aanmaken)
        configure_claude_desktop

        # Aider config wordt automatisch geladen uit .aider.conf.yml
        if [[ " ${DETECTED_TOOLS} " =~ " aider " ]]; then
            print_info "Aider configuratie gevonden in .aider.conf.yml"
        fi

        # CLI tools: registreer MCP server als geinstalleerd
        if [[ " ${DETECTED_TOOLS} " =~ " claude-cli " ]]; then
            register_claude_code_mcp
        fi

        if [[ " ${DETECTED_TOOLS} " =~ " codex-cli " ]]; then
            register_codex_mcp
        fi
    fi

    # Stap 8: Start services
    if [ "$SKIP_BUILD" = false ]; then
        start_services
    fi

    # Samenvatting
    show_summary
}

# Run
main "$@"
