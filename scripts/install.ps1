#Requires -Version 5.1
<#
.SYNOPSIS
    Baarn Raadsinformatie - Windows Installatiescript
.DESCRIPTION
    Dit script installeert alle benodigdheden voor de Baarn Raadsinformatie MCP server:
    - Docker Desktop (indien niet aanwezig)
    - Docker images bouwen
    - AI systemen configureren (Claude Desktop, Cursor, Continue.dev, etc.)

    One-liner installatie:
    irm https://raw.githubusercontent.com/tiemenrtuinstra/baarn-raadsinformatie/main/install.ps1 | iex
.NOTES
    Versie: 2.3.5
    Auteur: Baarn Raadsinformatie Team
#>

param(
    [switch]$SkipDocker,
    [switch]$SkipBuild,
    [switch]$SkipAI,
    [switch]$SkipClaude,
    [switch]$Force,
    [switch]$LightBuild,
    [string]$ApiKey = "baarn-api-key-$(Get-Random -Maximum 999999)"
)

# Configuratie
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Repo = "tiemenrtuinstra/baarn-raadsinformatie"
$Registry = "ghcr.io"
$InstallDir = "$env:LOCALAPPDATA\baarn-raadsinformatie"

# Detecteer of we lokaal of remote draaien
if (Test-Path (Join-Path $PSScriptRoot "mcp_server.py")) {
    $ScriptDir = $PSScriptRoot
    $RemoteInstall = $false
} else {
    $ScriptDir = $InstallDir
    $RemoteInstall = $true
}

# Kleuren voor output
function Write-ColorOutput {
    param([string]$Message, [string]$Color = "White")
    Write-Host $Message -ForegroundColor $Color
}

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> " -ForegroundColor Cyan -NoNewline
    Write-Host $Message -ForegroundColor White
}

function Write-Success {
    param([string]$Message)
    Write-Host "[OK] " -ForegroundColor Green -NoNewline
    Write-Host $Message
}

function Write-Warning {
    param([string]$Message)
    Write-Host "[!] " -ForegroundColor Yellow -NoNewline
    Write-Host $Message
}

function Write-Error {
    param([string]$Message)
    Write-Host "[X] " -ForegroundColor Red -NoNewline
    Write-Host $Message
}

function Write-Info {
    param([string]$Message)
    Write-Host "    $Message" -ForegroundColor Gray
}

# Download bestand van GitHub
function Get-GitHubFile {
    param(
        [string]$File,
        [string]$Destination
    )
    $url = "https://raw.githubusercontent.com/$Repo/main/$File"
    try {
        Invoke-WebRequest -Uri $url -OutFile $Destination -UseBasicParsing
        return $true
    } catch {
        return $false
    }
}

# Download project bestanden van GitHub (voor remote install)
function Get-ProjectFiles {
    Write-Step "Project bestanden downloaden van GitHub..."

    # Maak install directory
    if (-not (Test-Path $ScriptDir)) {
        New-Item -ItemType Directory -Path $ScriptDir -Force | Out-Null
    }

    Push-Location $ScriptDir

    # Download essentiële bestanden
    $files = @(
        "docker-compose.yml",
        "Dockerfile",
        ".env.example",
        "requirements.txt",
        "requirements-embeddings.txt",
        ".dockerignore"
    )

    foreach ($file in $files) {
        Write-Info "Downloading $file..."
        if (-not (Get-GitHubFile -File $file -Destination $file)) {
            Write-Warning "Kon $file niet downloaden"
        }
    }

    # Maak directories
    $dirs = @("agents", "core", "providers", "analyzers", "shared", "data\documents", "data\cache", "logs")
    foreach ($dir in $dirs) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }

    # Download core Python bestanden
    $pythonFiles = @(
        "mcp_server.py",
        "api_server.py",
        "sync_service.py",
        "core\__init__.py",
        "core\config.py",
        "core\database.py",
        "core\document_index.py",
        "core\coalitie_tracker.py",
        "providers\__init__.py",
        "providers\notubiz_client.py",
        "providers\meeting_provider.py",
        "providers\document_provider.py",
        "providers\transcription_provider.py",
        "providers\summary_provider.py",
        "providers\dossier_provider.py",
        "analyzers\__init__.py",
        "analyzers\search_analyzer.py",
        "shared\__init__.py",
        "shared\logging_config.py",
        "agents\__init__.py"
    )

    foreach ($file in $pythonFiles) {
        Write-Info "Downloading $file..."
        $null = Get-GitHubFile -File ($file -replace "\\", "/") -Destination $file
    }

    Pop-Location
    Write-Success "Project bestanden gedownload naar $ScriptDir"
}

# Haal laatste versie op van GitHub
function Get-LatestVersion {
    Write-Step "Laatste versie ophalen..."
    try {
        $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest"
        $script:LatestVersion = $release.tag_name
        Write-Success "Laatste versie: $LatestVersion"
    } catch {
        $script:LatestVersion = "latest"
        Write-Warning "Kon laatste versie niet ophalen, gebruik 'latest'"
    }
}

# Pull Docker image van registry (voor remote install)
function Get-DockerImage {
    Write-Step "Docker image pullen van registry..."

    $image = "$Registry/$Repo"
    $tag = if ($LightBuild) { "$LatestVersion-light" } else { $LatestVersion }

    Write-Info "Image: ${image}:${tag}"

    try {
        docker pull "${image}:${tag}"
        docker tag "${image}:${tag}" "baarn-raadsinformatie:latest"
        Write-Success "Docker image gepulled en getagd als baarn-raadsinformatie:latest"
        return $true
    } catch {
        Write-Warning "Kon image niet pullen, probeer lokale build..."
        return $false
    }
}

# Banner
function Show-Banner {
    Write-Host ""
    Write-Host "  ____                            ____                _     " -ForegroundColor Cyan
    Write-Host " | __ )  __ _  __ _ _ __ _ __    |  _ \ __ _  __ _  __| |___ " -ForegroundColor Cyan
    Write-Host " |  _ \ / _`` |/ _`` | '__| '_ \   | |_) / _`` |/ _`` |/ _`` / __|" -ForegroundColor Cyan
    Write-Host " | |_) | (_| | (_| | |  | | | |  |  _ < (_| | (_| | (_| \__ \" -ForegroundColor Cyan
    Write-Host " |____/ \__,_|\__,_|_|  |_| |_|  |_| \_\__,_|\__,_|\__,_|___/" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Raadsinformatie MCP Server - Windows Installer v2.4.0" -ForegroundColor White
    Write-Host "  ======================================================" -ForegroundColor Gray
    Write-Host ""
}

# Check Administrator rechten
function Test-Administrator {
    $currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Check of Docker is geinstalleerd
function Test-DockerInstalled {
    try {
        $null = Get-Command docker -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

# Check of Docker draait
function Test-DockerRunning {
    try {
        $result = docker info 2>&1
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

# Installeer Docker Desktop
function Install-DockerDesktop {
    Write-Step "Docker Desktop installeren..."

    $installerUrl = "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"
    $installerPath = "$env:TEMP\DockerDesktopInstaller.exe"

    Write-Info "Docker Desktop downloaden..."
    try {
        Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing
    } catch {
        Write-Error "Kan Docker Desktop niet downloaden. Check je internetverbinding."
        Write-Info "Je kunt Docker Desktop handmatig downloaden van: https://www.docker.com/products/docker-desktop"
        return $false
    }

    Write-Info "Docker Desktop installeren (dit kan enkele minuten duren)..."
    Start-Process -FilePath $installerPath -ArgumentList "install", "--quiet", "--accept-license" -Wait -NoNewWindow

    # Cleanup
    Remove-Item $installerPath -Force -ErrorAction SilentlyContinue

    # Refresh PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

    Write-Success "Docker Desktop geinstalleerd"
    Write-Warning "Een herstart kan nodig zijn om Docker te kunnen gebruiken"

    return $true
}

# Start Docker Desktop
function Start-DockerDesktop {
    Write-Step "Docker Desktop starten..."

    $dockerPath = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dockerPath) {
        Start-Process $dockerPath
        Write-Info "Wachten tot Docker is gestart (max 120 seconden)..."

        $timeout = 120
        $elapsed = 0
        while (-not (Test-DockerRunning) -and $elapsed -lt $timeout) {
            Start-Sleep -Seconds 5
            $elapsed += 5
            Write-Host "." -NoNewline
        }
        Write-Host ""

        if (Test-DockerRunning) {
            Write-Success "Docker is gestart"
            return $true
        } else {
            Write-Error "Docker kon niet worden gestart binnen $timeout seconden"
            return $false
        }
    } else {
        Write-Error "Docker Desktop niet gevonden op: $dockerPath"
        return $false
    }
}

# Check of FFmpeg is geinstalleerd
function Test-FFmpegInstalled {
    try {
        $null = Get-Command ffmpeg -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

# Installeer FFmpeg (vereist voor video/audio transcriptie)
function Install-FFmpeg {
    Write-Step "FFmpeg installeren (vereist voor video/audio transcriptie)..."

    # Check of al geinstalleerd
    if (Test-FFmpegInstalled) {
        Write-Success "FFmpeg is al geinstalleerd"
        return $true
    }

    # Probeer via winget
    try {
        $null = Get-Command winget -ErrorAction Stop
        Write-Info "Installeren via winget..."
        winget install Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
        if ($LASTEXITCODE -eq 0) {
            # Refresh PATH
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
            Write-Success "FFmpeg geinstalleerd via winget"
            return $true
        }
    } catch {
        Write-Info "winget niet beschikbaar, probeer chocolatey..."
    }

    # Probeer via chocolatey
    try {
        $null = Get-Command choco -ErrorAction Stop
        Write-Info "Installeren via chocolatey..."
        choco install ffmpeg -y
        if ($LASTEXITCODE -eq 0) {
            # Refresh PATH
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
            Write-Success "FFmpeg geinstalleerd via chocolatey"
            return $true
        }
    } catch {
        Write-Info "chocolatey niet beschikbaar..."
    }

    # Handmatige download als laatste optie
    Write-Warning "FFmpeg kon niet automatisch worden geinstalleerd"
    Write-Info "Download FFmpeg handmatig van: https://ffmpeg.org/download.html"
    Write-Info "Of installeer via: winget install Gyan.FFmpeg"
    Write-Info "Of via chocolatey: choco install ffmpeg"
    return $false
}

# Check of Node.js is geinstalleerd
function Test-NodeJSInstalled {
    try {
        $null = Get-Command node -ErrorAction Stop
        $null = Get-Command npm -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

# Installeer Node.js
function Install-NodeJS {
    Write-Step "Node.js installeren..."

    # Probeer via winget
    try {
        $null = Get-Command winget -ErrorAction Stop
        Write-Info "Installeren via winget..."
        winget install OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
        if ($LASTEXITCODE -eq 0) {
            # Refresh PATH
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
            Write-Success "Node.js geinstalleerd via winget"
            return $true
        }
    } catch {
        Write-Info "winget niet beschikbaar, probeer directe download..."
    }

    # Direct downloaden als fallback
    $nodeInstallerUrl = "https://nodejs.org/dist/v20.11.0/node-v20.11.0-x64.msi"
    $nodeInstallerPath = "$env:TEMP\nodejs-installer.msi"

    Write-Info "Node.js downloaden..."
    try {
        Invoke-WebRequest -Uri $nodeInstallerUrl -OutFile $nodeInstallerPath -UseBasicParsing
        Write-Info "Node.js installeren..."
        Start-Process msiexec.exe -ArgumentList "/i", $nodeInstallerPath, "/quiet", "/norestart" -Wait -NoNewWindow
        Remove-Item $nodeInstallerPath -Force -ErrorAction SilentlyContinue

        # Refresh PATH
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

        if (Test-NodeJSInstalled) {
            Write-Success "Node.js geinstalleerd: $(node --version)"
            return $true
        }
    } catch {
        Write-Warning "Node.js installatie gefaald: $_"
    }

    Write-Error "Node.js kon niet worden geinstalleerd"
    Write-Info "Download handmatig van: https://nodejs.org/en/download/"
    return $false
}

# Check of Claude Code CLI is geinstalleerd
function Test-ClaudeCLIInstalled {
    try {
        $null = Get-Command claude -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

# Installeer Claude Code CLI via npm
function Install-ClaudeCodeCLI {
    Write-Step "Claude Code CLI installeren..."

    # Check Node.js
    if (-not (Test-NodeJSInstalled)) {
        Write-Warning "Node.js niet gevonden, eerst installeren..."
        if (-not (Install-NodeJS)) {
            return $false
        }
    }

    # Installeer Claude Code CLI globally
    Write-Info "Installeren via npm..."
    try {
        npm install -g @anthropic-ai/claude-code 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            # Refresh PATH
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
            Write-Success "Claude Code CLI geinstalleerd"
            return $true
        }
    } catch {
        Write-Warning "npm install gefaald: $_"
    }

    Write-Error "Claude Code CLI installatie gefaald"
    Write-Info "Probeer handmatig: npm install -g @anthropic-ai/claude-code"
    return $false
}

# Check of Claude Desktop is geinstalleerd
function Test-ClaudeDesktopInstalled {
    $paths = @(
        "$env:LOCALAPPDATA\Programs\claude-desktop\Claude.exe",
        "$env:LOCALAPPDATA\AnthropicClaude\Claude.exe",
        "$env:ProgramFiles\Claude\Claude.exe"
    )

    foreach ($path in $paths) {
        if (Test-Path $path) {
            return $true
        }
    }
    return $false
}

# Installeer Claude Desktop
function Install-ClaudeDesktop {
    Write-Step "Claude Desktop installeren..."

    # Probeer via winget
    try {
        $null = Get-Command winget -ErrorAction Stop
        Write-Info "Installeren via winget..."
        winget install Anthropic.Claude --accept-source-agreements --accept-package-agreements
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Claude Desktop geinstalleerd via winget"
            return $true
        }
    } catch {
        Write-Info "winget niet beschikbaar, probeer directe download..."
    }

    # Direct downloaden als fallback
    Write-Info "Claude Desktop downloaden..."
    $claudeInstallerUrl = "https://storage.googleapis.com/anthropic-public/claude-desktop/claude-desktop-latest-windows.exe"
    $claudeInstallerPath = "$env:TEMP\claude-desktop-installer.exe"

    try {
        Invoke-WebRequest -Uri $claudeInstallerUrl -OutFile $claudeInstallerPath -UseBasicParsing
        Write-Info "Claude Desktop installeren..."
        Start-Process $claudeInstallerPath -ArgumentList "/S" -Wait -NoNewWindow
        Remove-Item $claudeInstallerPath -Force -ErrorAction SilentlyContinue

        if (Test-ClaudeDesktopInstalled) {
            Write-Success "Claude Desktop geinstalleerd"
            return $true
        }
    } catch {
        Write-Warning "Claude Desktop download gefaald: $_"
    }

    Write-Error "Claude Desktop installatie gefaald"
    Write-Info "Download handmatig van: https://claude.ai/download"
    return $false
}

# Installeer Claude (Desktop of CLI)
function Install-Claude {
    Write-Step "Claude AI tool installeren..."

    # Check of al geinstalleerd
    if (Test-ClaudeDesktopInstalled) {
        Write-Success "Claude Desktop is al geinstalleerd"
        return $true
    }

    if (Test-ClaudeCLIInstalled) {
        Write-Success "Claude Code CLI is al geinstalleerd"
        return $true
    }

    # Windows: eerst Claude Desktop proberen, dan CLI als fallback
    if (Install-ClaudeDesktop) {
        return $true
    }

    Write-Info "Fallback naar Claude Code CLI..."
    return Install-ClaudeCodeCLI
}

# Maak .env bestand
function Initialize-EnvFile {
    Write-Step "Environment bestand configureren..."

    $envFile = Join-Path $PSScriptRoot ".env"
    $envExample = Join-Path $PSScriptRoot ".env.example"

    if ((Test-Path $envFile) -and -not $Force) {
        Write-Info ".env bestand bestaat al, wordt overgeslagen"
        Write-Info "Gebruik -Force om te overschrijven"
        return
    }

    if (Test-Path $envExample) {
        Copy-Item $envExample $envFile -Force

        # Update API key
        $content = Get-Content $envFile -Raw
        $content = $content -replace "API_KEY=baarn-api-key-change-me", "API_KEY=$ApiKey"
        Set-Content $envFile $content -NoNewline

        Write-Success ".env bestand aangemaakt"
        Write-Info "API Key: $ApiKey"
    } else {
        Write-Warning ".env.example niet gevonden, maak handmatig .env aan"
    }
}

# Bouw Docker images
function Build-DockerImages {
    Write-Step "Docker images bouwen..."

    Push-Location $PSScriptRoot

    try {
        if ($LightBuild) {
            Write-Info "Lichtgewicht build (zonder embeddings)..."
            docker compose --profile light build api-server-light
        } else {
            Write-Info "Volledige build (met embeddings, kan 5-10 minuten duren)..."
            docker compose build
        }

        if ($LASTEXITCODE -eq 0) {
            Write-Success "Docker images gebouwd"
            return $true
        } else {
            Write-Error "Docker build gefaald"
            return $false
        }
    } finally {
        Pop-Location
    }
}

# Test of een pad bestaat en maak het aan
function Ensure-Directory {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

# Configureer Claude Desktop
function Configure-ClaudeDesktop {
    Write-Step "Claude Desktop configureren..."

    $claudeConfigDir = "$env:APPDATA\Claude"
    $claudeConfig = "$claudeConfigDir\claude_desktop_config.json"
    $projectPath = $PSScriptRoot -replace "\\", "\\\\"

    Ensure-Directory $claudeConfigDir

    $mcpConfig = @{
        mcpServers = @{
            "baarn-raadsinformatie" = @{
                command = "docker"
                args = @(
                    "run", "-i", "--rm",
                    "--env-file", "$projectPath\\.env",
                    "-v", "$projectPath\\data:/app/data",
                    "-v", "$projectPath\\logs:/app/logs",
                    "baarn-raadsinformatie:latest"
                )
            }
        }
    }

    if (Test-Path $claudeConfig) {
        try {
            $existingConfig = Get-Content $claudeConfig -Raw | ConvertFrom-Json

            if (-not $existingConfig.mcpServers) {
                $existingConfig | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue @{} -Force
            }

            $existingConfig.mcpServers | Add-Member -NotePropertyName "baarn-raadsinformatie" -NotePropertyValue $mcpConfig.mcpServers."baarn-raadsinformatie" -Force

            $existingConfig | ConvertTo-Json -Depth 10 | Set-Content $claudeConfig
            Write-Success "Claude Desktop configuratie bijgewerkt"
        } catch {
            Write-Warning "Kon bestaande Claude config niet lezen, wordt overschreven"
            $mcpConfig | ConvertTo-Json -Depth 10 | Set-Content $claudeConfig
        }
    } else {
        $mcpConfig | ConvertTo-Json -Depth 10 | Set-Content $claudeConfig
        Write-Success "Claude Desktop configuratie aangemaakt"
    }

    Write-Info "Config: $claudeConfig"
    return $true
}

# Configureer Cursor IDE
function Configure-CursorIDE {
    Write-Step "Cursor IDE configureren..."

    $cursorDir = Join-Path $PSScriptRoot ".cursor"
    $cursorConfig = Join-Path $cursorDir "mcp.json"
    $projectPath = $PSScriptRoot -replace "\\", "/"

    Ensure-Directory $cursorDir

    $config = @{
        mcpServers = @{
            "baarn-raadsinformatie" = @{
                command = "docker"
                args = @(
                    "run", "-i", "--rm",
                    "--env-file", "$projectPath/.env",
                    "-v", "$projectPath/data:/app/data",
                    "-v", "$projectPath/logs:/app/logs",
                    "baarn-raadsinformatie:latest"
                )
            }
        }
    }

    $config | ConvertTo-Json -Depth 10 | Set-Content $cursorConfig
    Write-Success "Cursor IDE configuratie aangemaakt"
    Write-Info "Config: $cursorConfig"
    return $true
}

# Configureer Continue.dev
function Configure-ContinueDev {
    Write-Step "Continue.dev configureren..."

    $continueDir = Join-Path $PSScriptRoot ".continue"
    $continueConfig = Join-Path $continueDir "config.json"
    $projectPath = $PSScriptRoot -replace "\\", "/"

    # Check ook globale Continue config
    $globalContinueDir = "$env:USERPROFILE\.continue"

    Ensure-Directory $continueDir

    $config = @{
        models = @(
            @{
                title = "Claude 3.5 Sonnet"
                provider = "anthropic"
                model = "claude-3-5-sonnet-20241022"
                apiKey = "`${ANTHROPIC_API_KEY}"
            },
            @{
                title = "GPT-4o"
                provider = "openai"
                model = "gpt-4o"
                apiKey = "`${OPENAI_API_KEY}"
            },
            @{
                title = "Ollama Local"
                provider = "ollama"
                model = "llama3.2"
            }
        )
        tabAutocompleteModel = @{
            title = "Starcoder"
            provider = "ollama"
            model = "starcoder2:3b"
        }
        experimental = @{
            modelContextProtocolServers = @(
                @{
                    transport = @{
                        type = "stdio"
                        command = "docker"
                        args = @(
                            "run", "-i", "--rm",
                            "--env-file", "$projectPath/.env",
                            "-v", "$projectPath/data:/app/data",
                            "-v", "$projectPath/logs:/app/logs",
                            "baarn-raadsinformatie:latest"
                        )
                    }
                }
            )
        }
        customCommands = @(
            @{
                name = "baarn-vergaderingen"
                description = "Zoek vergaderingen in Baarn"
                prompt = "Gebruik de MCP tools om vergaderingen op te halen. {{{ input }}}"
            },
            @{
                name = "baarn-zoek"
                description = "Zoek in politieke documenten"
                prompt = "Gebruik search_documents of semantic_search om te zoeken naar: {{{ input }}}"
            }
        )
    }

    $config | ConvertTo-Json -Depth 10 | Set-Content $continueConfig
    Write-Success "Continue.dev configuratie aangemaakt"
    Write-Info "Config: $continueConfig"
    return $true
}

# Configureer VS Code
function Configure-VSCode {
    Write-Step "VS Code instellingen configureren..."

    $vscodeDir = Join-Path $PSScriptRoot ".vscode"
    $settingsFile = Join-Path $vscodeDir "settings.json"

    Ensure-Directory $vscodeDir

    $settings = @{
        "github.copilot.enable" = @{
            "*" = $true
        }
        "github.copilot.advanced" = @{
            "inlineSuggestCount" = 3
        }
    }

    if (Test-Path $settingsFile) {
        try {
            $existingSettings = Get-Content $settingsFile -Raw | ConvertFrom-Json
            foreach ($key in $settings.Keys) {
                $existingSettings | Add-Member -NotePropertyName $key -NotePropertyValue $settings[$key] -Force
            }
            $existingSettings | ConvertTo-Json -Depth 10 | Set-Content $settingsFile
        } catch {
            $settings | ConvertTo-Json -Depth 10 | Set-Content $settingsFile
        }
    } else {
        $settings | ConvertTo-Json -Depth 10 | Set-Content $settingsFile
    }

    Write-Success "VS Code instellingen aangemaakt"
    return $true
}

# Configureer Zed Editor
function Configure-ZedEditor {
    Write-Step "Zed Editor configureren..."

    $zedDir = Join-Path $PSScriptRoot ".zed"
    $zedConfig = Join-Path $zedDir "settings.json"
    $projectPath = $PSScriptRoot -replace "\\", "/"

    Ensure-Directory $zedDir

    $config = @{
        context_servers = @{
            "baarn-raadsinformatie" = @{
                command = @{
                    path = "docker"
                    args = @(
                        "run", "-i", "--rm",
                        "--env-file", "$projectPath/.env",
                        "-v", "$projectPath/data:/app/data",
                        "-v", "$projectPath/logs:/app/logs",
                        "baarn-raadsinformatie:latest"
                    )
                }
            }
        }
        assistant = @{
            default_model = @{
                provider = "anthropic"
                model = "claude-3-5-sonnet-20241022"
            }
            version = "2"
        }
    }

    $config | ConvertTo-Json -Depth 10 | Set-Content $zedConfig
    Write-Success "Zed Editor configuratie aangemaakt"
    Write-Info "Config: $zedConfig"
    return $true
}

# Configureer Windsurf
function Configure-Windsurf {
    Write-Step "Windsurf configureren..."

    $windsurfDir = Join-Path $PSScriptRoot ".windsurf"
    $windsurfConfig = Join-Path $windsurfDir "mcp.json"
    $projectPath = $PSScriptRoot -replace "\\", "/"

    Ensure-Directory $windsurfDir

    $config = @{
        mcpServers = @{
            "baarn-raadsinformatie" = @{
                command = "docker"
                args = @(
                    "run", "-i", "--rm",
                    "--env-file", "$projectPath/.env",
                    "-v", "$projectPath/data:/app/data",
                    "-v", "$projectPath/logs:/app/logs",
                    "baarn-raadsinformatie:latest"
                )
                description = "Baarn Raadsinformatie MCP Server"
            }
        }
    }

    $config | ConvertTo-Json -Depth 10 | Set-Content $windsurfConfig
    Write-Success "Windsurf configuratie aangemaakt"
    Write-Info "Config: $windsurfConfig"
    return $true
}

# Registreer MCP server bij Claude Code CLI
function Register-ClaudeCodeMCP {
    Write-Step "Claude Code CLI MCP registreren..."

    $projectPath = $PSScriptRoot -replace "\\", "/"

    try {
        # Verwijder eerst bestaande registratie (ignore errors)
        $null = claude mcp remove baarn-raadsinformatie 2>&1

        # Registreer de MCP server
        $result = claude mcp add baarn-raadsinformatie -- docker run -i --rm `
            --env-file "$projectPath/.env" `
            -v "$projectPath/data:/app/data" `
            -v "$projectPath/logs:/app/logs" `
            baarn-raadsinformatie:latest 2>&1

        if ($LASTEXITCODE -eq 0) {
            Write-Success "Claude Code CLI MCP geregistreerd"
            Write-Info "Gebruik: claude (start sessie met MCP tools)"
            return $true
        } else {
            Write-Warning "Claude Code CLI MCP registratie gefaald: $result"
            return $false
        }
    } catch {
        Write-Warning "Claude Code CLI MCP registratie gefaald: $_"
        return $false
    }
}

# Registreer MCP server bij OpenAI Codex CLI
function Register-CodexMCP {
    Write-Step "OpenAI Codex CLI MCP registreren..."

    $projectPath = $PSScriptRoot -replace "\\", "/"

    try {
        # Verwijder eerst bestaande registratie (ignore errors)
        $null = codex mcp remove baarn-raadsinformatie 2>&1

        # Registreer de MCP server
        $result = codex mcp add baarn-raadsinformatie -- docker run -i --rm `
            --env-file "$projectPath/.env" `
            -v "$projectPath/data:/app/data" `
            -v "$projectPath/logs:/app/logs" `
            baarn-raadsinformatie:latest 2>&1

        if ($LASTEXITCODE -eq 0) {
            Write-Success "OpenAI Codex CLI MCP geregistreerd"
            Write-Info "Gebruik: codex (start sessie met MCP tools)"
            return $true
        } else {
            Write-Warning "OpenAI Codex CLI MCP registratie gefaald: $result"
            return $false
        }
    } catch {
        Write-Warning "OpenAI Codex CLI MCP registratie gefaald: $_"
        return $false
    }
}

# Detecteer geinstalleerde AI tools
function Get-InstalledAITools {
    $tools = @()

    # Claude Desktop
    if (Test-Path "$env:LOCALAPPDATA\Programs\claude-desktop\Claude.exe") {
        $tools += @{Name = "Claude Desktop"; Installed = $true; Path = "$env:LOCALAPPDATA\Programs\claude-desktop"}
    } elseif (Test-Path "$env:LOCALAPPDATA\AnthropicClaude\Claude.exe") {
        $tools += @{Name = "Claude Desktop"; Installed = $true; Path = "$env:LOCALAPPDATA\AnthropicClaude"}
    } else {
        $tools += @{Name = "Claude Desktop"; Installed = $false}
    }

    # Cursor
    if (Test-Path "$env:LOCALAPPDATA\Programs\cursor\Cursor.exe") {
        $tools += @{Name = "Cursor IDE"; Installed = $true; Path = "$env:LOCALAPPDATA\Programs\cursor"}
    } else {
        $tools += @{Name = "Cursor IDE"; Installed = $false}
    }

    # VS Code
    $vscodePaths = @(
        "$env:LOCALAPPDATA\Programs\Microsoft VS Code\Code.exe",
        "$env:ProgramFiles\Microsoft VS Code\Code.exe"
    )
    $vscodeInstalled = $false
    foreach ($path in $vscodePaths) {
        if (Test-Path $path) {
            $tools += @{Name = "VS Code"; Installed = $true; Path = Split-Path $path}
            $vscodeInstalled = $true
            break
        }
    }
    if (-not $vscodeInstalled) {
        $tools += @{Name = "VS Code"; Installed = $false}
    }

    # Continue.dev (VS Code extension)
    $continueExtPath = "$env:USERPROFILE\.vscode\extensions"
    if (Test-Path $continueExtPath) {
        $continueExt = Get-ChildItem $continueExtPath -Directory | Where-Object { $_.Name -like "continue.*" }
        if ($continueExt) {
            $tools += @{Name = "Continue.dev"; Installed = $true; Path = $continueExt[0].FullName}
        } else {
            $tools += @{Name = "Continue.dev"; Installed = $false}
        }
    } else {
        $tools += @{Name = "Continue.dev"; Installed = $false}
    }

    # Ollama
    try {
        $null = Get-Command ollama -ErrorAction Stop
        $tools += @{Name = "Ollama"; Installed = $true; Path = (Get-Command ollama).Source}
    } catch {
        $tools += @{Name = "Ollama"; Installed = $false}
    }

    # GitHub Copilot CLI
    try {
        $null = Get-Command github-copilot-cli -ErrorAction Stop
        $tools += @{Name = "GitHub Copilot CLI"; Installed = $true}
    } catch {
        $tools += @{Name = "GitHub Copilot CLI"; Installed = $false}
    }

    # Cline (Claude Dev) - VS Code extension
    $clineExtPath = "$env:USERPROFILE\.vscode\extensions"
    if (Test-Path $clineExtPath) {
        $clineExt = Get-ChildItem $clineExtPath -Directory | Where-Object { $_.Name -like "saoudrizwan.claude-dev*" -or $_.Name -like "cline.*" }
        if ($clineExt) {
            $tools += @{Name = "Cline (Claude Dev)"; Installed = $true; Path = $clineExt[0].FullName}
        } else {
            $tools += @{Name = "Cline (Claude Dev)"; Installed = $false}
        }
    } else {
        $tools += @{Name = "Cline (Claude Dev)"; Installed = $false}
    }

    # Aider
    try {
        $null = Get-Command aider -ErrorAction Stop
        $tools += @{Name = "Aider"; Installed = $true; Path = (Get-Command aider).Source}
    } catch {
        $tools += @{Name = "Aider"; Installed = $false}
    }

    # Claude Code CLI (Anthropic)
    try {
        $null = Get-Command claude -ErrorAction Stop
        $tools += @{Name = "Claude Code CLI"; Installed = $true; Path = (Get-Command claude).Source}
    } catch {
        $tools += @{Name = "Claude Code CLI"; Installed = $false}
    }

    # OpenAI Codex CLI
    try {
        $null = Get-Command codex -ErrorAction Stop
        $tools += @{Name = "OpenAI Codex CLI"; Installed = $true; Path = (Get-Command codex).Source}
    } catch {
        $tools += @{Name = "OpenAI Codex CLI"; Installed = $false}
    }

    # Zed Editor
    $zedPaths = @(
        "$env:LOCALAPPDATA\Programs\Zed\Zed.exe",
        "$env:LOCALAPPDATA\Zed\Zed.exe",
        "$env:ProgramFiles\Zed\Zed.exe"
    )
    $zedInstalled = $false
    foreach ($path in $zedPaths) {
        if (Test-Path $path) {
            $tools += @{Name = "Zed Editor"; Installed = $true; Path = Split-Path $path}
            $zedInstalled = $true
            break
        }
    }
    if (-not $zedInstalled) {
        $tools += @{Name = "Zed Editor"; Installed = $false}
    }

    # Windsurf (Codeium)
    $windsurfPaths = @(
        "$env:LOCALAPPDATA\Programs\Windsurf\Windsurf.exe",
        "$env:LOCALAPPDATA\Windsurf\Windsurf.exe"
    )
    $windsurfInstalled = $false
    foreach ($path in $windsurfPaths) {
        if (Test-Path $path) {
            $tools += @{Name = "Windsurf"; Installed = $true; Path = Split-Path $path}
            $windsurfInstalled = $true
            break
        }
    }
    if (-not $windsurfInstalled) {
        $tools += @{Name = "Windsurf"; Installed = $false}
    }

    return $tools
}

# Toon gedetecteerde AI tools
function Show-DetectedAITools {
    Write-Step "Gedetecteerde AI tools..."

    $tools = Get-InstalledAITools

    foreach ($tool in $tools) {
        if ($tool.Installed) {
            Write-Host "  [" -NoNewline
            Write-Host "V" -ForegroundColor Green -NoNewline
            Write-Host "] " -NoNewline
            Write-Host $tool.Name -ForegroundColor White
            if ($tool.Path) {
                Write-Info "     $($tool.Path)"
            }
        } else {
            Write-Host "  [" -NoNewline
            Write-Host " " -NoNewline
            Write-Host "] " -NoNewline
            Write-Host $tool.Name -ForegroundColor Gray
        }
    }

    return $tools
}

# Start services
function Start-Services {
    Write-Step "Docker services starten..."

    Push-Location $ScriptDir

    try {
        # Start API server en sync service
        docker compose up -d api-server sync-service

        if ($LASTEXITCODE -eq 0) {
            Write-Success "Services gestart"

            # Wacht even en toon status
            Start-Sleep -Seconds 5
            docker compose ps

            return $true
        } else {
            Write-Error "Services konden niet worden gestart"
            return $false
        }
    } finally {
        Pop-Location
    }
}

# Toon samenvatting
function Show-Summary {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  Installatie voltooid!" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""

    if ($RemoteInstall) {
        Write-Host "  Installatie dir: " -NoNewline
        Write-Host $ScriptDir -ForegroundColor Yellow
        Write-Host ""
    }

    Write-Host "  API Server:     " -NoNewline
    Write-Host "http://localhost:8000" -ForegroundColor Yellow
    Write-Host "  API Docs:       " -NoNewline
    Write-Host "http://localhost:8000/docs" -ForegroundColor Yellow
    Write-Host "  API Key:        " -NoNewline
    Write-Host $ApiKey -ForegroundColor Yellow
    Write-Host ""

    Write-Host "  Volgende stappen:" -ForegroundColor White
    Write-Host "  1. Herstart Claude Desktop om de MCP server te laden" -ForegroundColor Gray
    Write-Host "  2. Test de API: curl http://localhost:8000/health" -ForegroundColor Gray
    Write-Host ""

    Write-Host "  Handige commando's:" -ForegroundColor White
    Write-Host "  cd $ScriptDir" -ForegroundColor Gray
    Write-Host "  docker compose logs -f          # Bekijk logs" -ForegroundColor Gray
    Write-Host "  docker compose restart          # Herstart services" -ForegroundColor Gray
    Write-Host "  docker compose down             # Stop services" -ForegroundColor Gray
    Write-Host ""
}

# Hoofdprogramma
function Main {
    Show-Banner

    # Remote install: download project bestanden eerst
    if ($RemoteInstall) {
        Write-Info "Remote installatie gedetecteerd"
        Get-LatestVersion
        Get-ProjectFiles
    }

    # Check administrator rechten voor Docker installatie
    if (-not $SkipDocker -and -not (Test-DockerInstalled)) {
        if (-not (Test-Administrator)) {
            Write-Warning "Administrator rechten nodig voor Docker installatie"
            Write-Info "Start dit script opnieuw als Administrator, of installeer Docker handmatig"
            Write-Info "Download: https://www.docker.com/products/docker-desktop"

            $response = Read-Host "Doorgaan zonder Docker installatie? (j/n)"
            if ($response -ne "j") {
                exit 1
            }
            $SkipDocker = $true
        }
    }

    # Stap 1: Docker
    if (-not $SkipDocker) {
        if (Test-DockerInstalled) {
            Write-Success "Docker is geinstalleerd"

            if (-not (Test-DockerRunning)) {
                if (-not (Start-DockerDesktop)) {
                    Write-Error "Kan Docker niet starten. Start Docker Desktop handmatig en voer dit script opnieuw uit."
                    exit 1
                }
            } else {
                Write-Success "Docker is actief"
            }
        } else {
            if (-not (Install-DockerDesktop)) {
                exit 1
            }

            Write-Warning "Herstart je computer en voer dit script opnieuw uit"
            exit 0
        }
    }

    # Stap 2: Environment
    Initialize-EnvFile

    # Stap 3: Data directories
    Write-Step "Data directories aanmaken..."
    Ensure-Directory (Join-Path $ScriptDir "data")
    Ensure-Directory (Join-Path $ScriptDir "data\documents")
    Ensure-Directory (Join-Path $ScriptDir "data\cache")
    Ensure-Directory (Join-Path $ScriptDir "data\audio")
    Ensure-Directory (Join-Path $ScriptDir "logs")
    Write-Success "Directories aangemaakt"

    # Stap 3b: FFmpeg (vereist voor video/audio transcriptie)
    Install-FFmpeg

    # Stap 4: Docker image (pull of build)
    if (-not $SkipBuild) {
        if ($RemoteInstall) {
            # Remote install: probeer eerst te pullen, anders bouwen
            if (-not (Get-DockerImage)) {
                if (-not (Build-DockerImages)) {
                    Write-Error "Docker image niet beschikbaar"
                    exit 1
                }
            }
        } else {
            # Lokale install: altijd bouwen
            if (-not (Build-DockerImages)) {
                Write-Error "Docker build gefaald. Check de logs hierboven."
                exit 1
            }
        }
    }

    # Stap 5: Claude installeren (indien nodig en niet overgeslagen)
    if (-not $SkipAI -and -not $SkipClaude) {
        Install-Claude
    } elseif ($SkipClaude) {
        Write-Info "Claude installatie overgeslagen (-SkipClaude)"
    }

    # Stap 6: Detecteer AI tools
    $detectedTools = Show-DetectedAITools

    # Stap 7: Configureer AI tools
    if (-not $SkipAI) {
        foreach ($tool in $detectedTools) {
            if ($tool.Installed) {
                switch ($tool.Name) {
                    "Claude Desktop" { Configure-ClaudeDesktop }
                    "Cursor IDE" { Configure-CursorIDE }
                    "VS Code" {
                        Configure-VSCode
                        # Als Continue.dev ook geinstalleerd is
                        $continueTool = $detectedTools | Where-Object { $_.Name -eq "Continue.dev" -and $_.Installed }
                        if ($continueTool) {
                            Configure-ContinueDev
                        }
                    }
                    "Continue.dev" {
                        # Wordt al afgehandeld bij VS Code
                    }
                    "Claude Code CLI" { Register-ClaudeCodeMCP }
                    "OpenAI Codex CLI" { Register-CodexMCP }
                    "Zed Editor" { Configure-ZedEditor }
                    "Windsurf" { Configure-Windsurf }
                }
            }
        }

        # Altijd lokale configs maken (voor als de tool later wordt geinstalleerd)
        Configure-CursorIDE
        Configure-ContinueDev
        Configure-ZedEditor
        Configure-Windsurf
    }

    # Stap 8: Start services
    if (-not $SkipBuild) {
        Start-Services
    }

    # Samenvatting
    Show-Summary
}

# Run
Main
