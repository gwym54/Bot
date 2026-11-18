#!/bin/bash
# Local helper only. On Railway the Dockerfile CMD is used.
cd "$(dirname "$0")"
set -a
[ -f .env ] && . .env
set +a

if [ -z "$BOT_TOKEN" ]; then
  echo "BOT_TOKEN is empty. Copy .env.example → .env and fill the values."
  exit 1
fi

export DB_FILE="${DB_FILE:-./data/db.json}"
mkdir -p "$(dirname "$DB_FILE")"

python3 -m venv venv 2>/dev/null || true
source venv/bin/activate
pip install -q -r requirements.txt
exec python bot.py
