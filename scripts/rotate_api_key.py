#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rotate API_KEY in .env by generating a new random key.
"""

import secrets
from pathlib import Path


def main() -> int:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        print("Missing .env; copy from .env.example first.")
        return 1

    content = env_path.read_text(encoding="utf-8").splitlines()
    new_key = f"baarn-api-key-{secrets.token_hex(8)}"
    updated = False
    new_lines = []
    for line in content:
        if line.startswith("API_KEY="):
            new_lines.append(f"API_KEY={new_key}")
            updated = True
        else:
            new_lines.append(line)

    if not updated:
        new_lines.append(f"API_KEY={new_key}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    print(f"New API_KEY set: {new_key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
