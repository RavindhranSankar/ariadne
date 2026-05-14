#!/usr/bin/env bash
# tools/register-dialin.sh — Register the Daily dial-in phone number with a webhook URL.
#
# Usage:
#   ./tools/register-dialin.sh <webhook_url>
#
# Example:
#   ./tools/register-dialin.sh http://1.2.3.4:7860/daily-dialin-webhook
#
# Reads DAILY_API_KEY and DAILY_DIALIN_PHONE_NUMBER from bot/.env.

set -euo pipefail

WEBHOOK_URL="${1:?Usage: ./tools/register-dialin.sh <webhook_url>}"

LOCAL_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BOT_ENV="${BOT_ENV_FILE:-$LOCAL_ROOT/bot/.env}"

if [ ! -f "$BOT_ENV" ]; then
  echo "ERROR: bot/.env not found at $BOT_ENV" >&2
  exit 1
fi

_read_env() { grep "^$1=" "$BOT_ENV" | cut -d= -f2- | tr -d '"' | tr -d "'"; }

DAILY_API_KEY="$(_read_env DAILY_API_KEY)"
DAILY_DIALIN_PHONE_NUMBER="$(_read_env DAILY_DIALIN_PHONE_NUMBER)"

if [ -z "$DAILY_API_KEY" ]; then
  echo "ERROR: DAILY_API_KEY not set in bot/.env" >&2
  exit 1
fi

if [ -z "$DAILY_DIALIN_PHONE_NUMBER" ]; then
  echo "ERROR: DAILY_DIALIN_PHONE_NUMBER not set in bot/.env" >&2
  exit 1
fi

echo "==> Registering Daily dial-in webhook..."
echo "    Phone:   $DAILY_DIALIN_PHONE_NUMBER"
echo "    Webhook: $WEBHOOK_URL"

HTTP_CODE=$(curl -s -o /tmp/daily-register-response.json -w "%{http_code}" \
  --location 'https://api.daily.co/v1' \
  --header 'Content-Type: application/json' \
  --header "Authorization: Bearer $DAILY_API_KEY" \
  --data "{
    \"properties\": {
      \"pinless_dialin\": [
        {
          \"phone_number\": \"$DAILY_DIALIN_PHONE_NUMBER\",
          \"room_creation_api\": \"$WEBHOOK_URL\"
        }
      ]
    }
  }")

if [ "$HTTP_CODE" = "200" ]; then
  echo "    OK (HTTP 200)"
else
  echo "ERROR: Daily API returned HTTP $HTTP_CODE" >&2
  echo "Response body:" >&2
  cat /tmp/daily-register-response.json >&2
  exit 1
fi
