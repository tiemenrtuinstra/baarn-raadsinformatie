#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gecentraliseerde Configuratie voor Baarn Raadsinformatie Server.
MCP server met agents voor politieke documenten gemeente Baarn.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Config:
    """Centrale configuratie klasse."""

    # ===== Paths =====
    BASE_DIR = Path(__file__).parent.parent
    LOGS_DIR = BASE_DIR / 'logs'
    DATA_DIR = BASE_DIR / 'data'
    DOCUMENTS_DIR = DATA_DIR / 'documents'
    CACHE_DIR = DATA_DIR / 'cache'
    CONFIGS_DIR = BASE_DIR / 'configs'

    # Ensure directories exist
    LOGS_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)
    DOCUMENTS_DIR.mkdir(exist_ok=True)
    CACHE_DIR.mkdir(exist_ok=True)

    # ===== Database =====
    DB_PATH = DATA_DIR / os.getenv('DB_PATH', 'baarn.db').replace('data/', '')

    # ===== Notubiz API =====
    NOTUBIZ_API_URL = os.getenv('NOTUBIZ_API_URL', 'https://api.notubiz.nl')
    NOTUBIZ_API_TOKEN = os.getenv('NOTUBIZ_API_TOKEN', '11ef5846eaf0242ec4e0bea441379d699a77f703d')
    NOTUBIZ_API_VERSION = os.getenv('NOTUBIZ_API_VERSION', '1.17.0')
    NOTUBIZ_ORGANISATION_ID = os.getenv('NOTUBIZ_ORGANISATION_ID', None)
    # Auth token voor historische data - vereist voor:
    # - Ophalen van vergaderingen uit het verleden (niet alleen aankomende)
    # - Direct downloaden van documenten via /document/{id} endpoint
    # Verkrijg via Notubiz beheerportaal of neem contact op met Notubiz
    NOTUBIZ_AUTH_TOKEN = os.getenv('NOTUBIZ_AUTH_TOKEN', None)

    # ===== Raadsinformatie web search =====
    RAADSINFORMATIE_BASE_URL = os.getenv(
        'RAADSINFORMATIE_BASE_URL',
        'https://baarn.raadsinformatie.nl'
    )

    # Baarn specifiek
    MUNICIPALITY_NAME = 'Baarn'
    ORCHESTRATOR_AGENT_NAME = os.getenv('ORCHESTRATOR_AGENT_NAME', 'orchestrator')
    FORCE_ORCHESTRATOR = os.getenv('FORCE_ORCHESTRATOR', 'true').lower() == 'true'

    # ===== Logging =====
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

    # ===== Cache =====
    CACHE_TTL_HOURS = int(os.getenv('CACHE_TTL_HOURS', '24'))

    # ===== Embeddings (VERPLICHT) =====
    EMBEDDINGS_MODEL = os.getenv(
        'EMBEDDINGS_MODEL',
        'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
    )
    # Embeddings zijn VERPLICHT voor semantic search - geen optionele configuratie meer

    # ===== Transcriptie (Whisper) =====
    WHISPER_MODEL = os.getenv('WHISPER_MODEL', 'small')  # tiny, base, small, medium, large-v3
    TRANSCRIPTION_LANGUAGE = os.getenv('TRANSCRIPTION_LANGUAGE', 'nl')  # of 'auto'
    KEEP_AUDIO_FILES = os.getenv('KEEP_AUDIO_FILES', 'false').lower() == 'true'
    AUDIO_DIR = DATA_DIR / 'audio'

    # ===== MCP Server =====
    MCP_PROTOCOL_VERSION = '2024-11-05'
    SERVER_NAME = 'baarn-raadsinformatie'
    SERVER_VERSION = '2.0.0'

    # ===== Auto Sync =====
    AUTO_SYNC_ENABLED = os.getenv('AUTO_SYNC_ENABLED', 'true').lower() == 'true'
    AUTO_SYNC_DAYS = int(os.getenv('AUTO_SYNC_DAYS', '365'))  # Hoeveel dagen terug bij eerste sync
    AUTO_DOWNLOAD_DOCS = os.getenv('AUTO_DOWNLOAD_DOCS', 'true').lower() == 'true'
    AUTO_INDEX_DOCS = os.getenv('AUTO_INDEX_DOCS', 'true').lower() == 'true'  # Embeddings indexeren (default: aan)

    # Full history sync - haalt ALLE beschikbare data op (kan lang duren!)
    # Standaard aan voor volledige historische zoekfunctionaliteit
    FULL_HISTORY_SYNC = os.getenv('FULL_HISTORY_SYNC', 'true').lower() == 'true'
    # Startdatum voor volledige sync (Notubiz Baarn data begint rond 2010)
    FULL_HISTORY_START = os.getenv('FULL_HISTORY_START', '2010-01-01')

    # ===== Storage =====
    # false (default): Download PDF → extract text → delete PDF (minimal storage)
    # true: Keep PDF files on disk after extraction
    KEEP_PDF_FILES = os.getenv('KEEP_PDF_FILES', 'false').lower() == 'true'
    STORE_FILES_IN_DB = os.getenv('STORE_FILES_IN_DB', 'false').lower() == 'true'  # Default false: images to filesystem
    MAX_FILE_SIZE_MB = int(os.getenv('MAX_FILE_SIZE_MB', '25'))

    # ===== Gremia filters =====
    # Welke gremia (commissies) we willen indexeren
    # None = alles, of een lijst van namen
    GREMIA_FILTER = None  # ['Gemeenteraad', 'Commissie'] zou filteren

    @classmethod
    def get_notubiz_params(cls) -> dict:
        """Get default parameters for Notubiz API calls."""
        return {
            'format': 'json',
            'version': cls.NOTUBIZ_API_VERSION,
            'application_token': cls.NOTUBIZ_API_TOKEN
        }

    @classmethod
    def get_config_summary(cls) -> dict:
        """Get summary of current configuration."""
        return {
            'server': {
                'name': cls.SERVER_NAME,
                'version': cls.SERVER_VERSION,
                'mcp_version': cls.MCP_PROTOCOL_VERSION
            },
            'notubiz': {
                'api_url': cls.NOTUBIZ_API_URL,
                'api_version': cls.NOTUBIZ_API_VERSION,
                'organization_id': cls.NOTUBIZ_ORGANISATION_ID,
                'municipality': cls.MUNICIPALITY_NAME
            },
            'paths': {
                'base_dir': str(cls.BASE_DIR),
                'db_path': str(cls.DB_PATH),
                'documents_dir': str(cls.DOCUMENTS_DIR),
                'cache_dir': str(cls.CACHE_DIR)
            },
            'features': {
                'embeddings_enabled': True,  # Altijd aan (verplicht)
                'embeddings_model': cls.EMBEDDINGS_MODEL
            }
        }

    @classmethod
    def validate(cls) -> dict:
        """Validate configuration."""
        errors = []
        warnings = []

        # Check API token
        if not cls.NOTUBIZ_API_TOKEN:
            errors.append("NOTUBIZ_API_TOKEN not set")

        # Check directories
        if not cls.DATA_DIR.exists():
            warnings.append(f"Data directory will be created: {cls.DATA_DIR}")

        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings
        }


if __name__ == '__main__':
    import json
    print("Configuration Summary:")
    print(json.dumps(Config.get_config_summary(), indent=2, default=str))
    print("\nValidation:")
    print(json.dumps(Config.validate(), indent=2))
