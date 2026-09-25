"""Pipe filter: masks every secret-bearing .env value (and derived bearer tokens) in stdin.

    <command> 2>&1 | python scripts/redact.py
"""

import re
import sys
from pathlib import Path

from dotenv import dotenv_values

SECRET_KEYS = ("TG_PASSWORD", "TG_SECRET", "TG_API_TOKEN", "TG_JWT_TOKEN", "TG_USERNAME", "ANTHROPIC_API_KEY")
env = dotenv_values(Path(__file__).resolve().parent.parent / ".env")
secrets = sorted({v for k, v in env.items() if k in SECRET_KEYS and v and len(v) >= 3}, key=len, reverse=True)
token = re.compile(r"(?i)(bearer\s+|token['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9._\-]{16,}")

for line in sys.stdin:
    for s in secrets:
        line = line.replace(s, "***")
    sys.stdout.write(token.sub(r"\1***", line))
    sys.stdout.flush()
