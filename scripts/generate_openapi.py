#!/usr/bin/env python3
"""
Generate OpenAPI schema for ChatGPT Custom GPT Actions.

Run with: python scripts/generate_openapi.py

This will create openapi.json that can be imported into ChatGPT.
"""

import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api_server import app


def generate_openapi_schema():
    """Generate OpenAPI schema from FastAPI app."""
    schema = app.openapi()

    # Customize for ChatGPT
    schema["info"]["title"] = "Baarn Raadsinformatie API"
    schema["info"]["description"] = """
API voor toegang tot politieke documenten en vergaderingen van gemeente Baarn.

Beschikbare functionaliteit:
- Vergaderingen ophalen en doorzoeken
- Documenten lezen en zoeken (keyword en semantisch)
- Gremia (commissies) ophalen
- Coalitieakkoord tracking
- Annotaties beheren
    """.strip()

    # Set the production server URL
    schema["servers"] = [
        {
            "url": "https://your-domain.com",
            "description": "Production API server"
        }
    ]

    return schema


def main():
    schema = generate_openapi_schema()

    # Write to file
    output_path = Path(__file__).parent.parent / "openapi.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)

    print(f"OpenAPI schema generated: {output_path}")
    print(f"Endpoints: {len([p for p in schema['paths'].values()])}")


if __name__ == "__main__":
    main()
