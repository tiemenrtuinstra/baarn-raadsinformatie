#!/usr/bin/env bash
set -euo pipefail

ENV_PATH="${1:-.env}"

if [[ ! -f "$ENV_PATH" ]]; then
  echo "Missing .env; copy from .env.example first."
  exit 1
fi

NEW_KEY="baarn-api-key-$(python3 - <<'PY'
import secrets
print(secrets.token_hex(8))
PY
)"

if grep -q '^API_KEY=' "$ENV_PATH"; then
  if command -v sed >/dev/null 2>&1; then
    # macOS/BSD vs GNU sed
    if sed --version >/dev/null 2>&1; then
      sed -i "s/^API_KEY=.*/API_KEY=$NEW_KEY/" "$ENV_PATH"
    else
      sed -i '' "s/^API_KEY=.*/API_KEY=$NEW_KEY/" "$ENV_PATH"
    fi
  else
    python3 - <<PY
from pathlib import Path
p = Path("$ENV_PATH")
lines = p.read_text().splitlines()
out = []
updated = False
for line in lines:
    if line.startswith("API_KEY="):
        out.append("API_KEY=$NEW_KEY")
        updated = True
    else:
        out.append(line)
if not updated:
    out.append("API_KEY=$NEW_KEY")
p.write_text("\\n".join(out) + "\\n")
PY
  fi
else
  echo "API_KEY=$NEW_KEY" >> "$ENV_PATH"
fi

echo "New API_KEY set: $NEW_KEY"
