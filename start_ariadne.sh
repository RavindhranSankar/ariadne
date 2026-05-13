#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BOT_ENV="$SCRIPT_DIR/bot/.env"

# ── Helpers ────────────────────────────────────────────────────────────────────

_RED='\033[0;31m'
_GREEN='\033[0;32m'
_YELLOW='\033[1;33m'
_CYAN='\033[0;36m'
_BOLD='\033[1m'
_RESET='\033[0m'

_ok()     { echo -e "  ${_GREEN}✓${_RESET}  $1"; }
_warn()   { echo -e "  ${_YELLOW}⚠${_RESET}  $1"; }
_err()    { echo -e "  ${_RED}✗${_RESET}  $1" >&2; }
_info()   { echo "  $1"; }
_header() { echo ""; echo -e "${_BOLD}${_CYAN}── $1 ──${_RESET}"; echo ""; }

_read_env_val() {
  local key="$1" file="${2:-}"
  [[ -f "$file" ]] || return 0
  { grep "^${key}=" "$file" 2>/dev/null || true; } \
    | head -1 | cut -d= -f2- | sed "s/^['\"]//;s/['\"]$//"
}

# ── Process cleanup ────────────────────────────────────────────────────────────

NGROK_PID=""

cleanup() {
  echo ""
  if [[ -n "$NGROK_PID" ]]; then
    _info "Stopping ngrok (PID $NGROK_PID)..."
    kill "$NGROK_PID" 2>/dev/null || true
    wait "$NGROK_PID" 2>/dev/null || true
  fi
  _info "Done."
}

trap cleanup EXIT INT TERM

# ── Preflight ──────────────────────────────────────────────────────────────────

_header "Starting Ariadne"

if [[ ! -f "$BOT_ENV" ]]; then
  _err "bot/.env not found. Run ./setup.sh first."
  exit 1
fi

DAILY_API_KEY="$(_read_env_val DAILY_API_KEY "$BOT_ENV")"
DAILY_PHONE="$(_read_env_val DAILY_DIALIN_PHONE_NUMBER "$BOT_ENV")"

if [[ -z "$DAILY_API_KEY" ]]; then
  _err "DAILY_API_KEY not set in bot/.env. Run ./setup.sh first."
  exit 1
fi

if [[ -z "$DAILY_PHONE" ]]; then
  _err "DAILY_DIALIN_PHONE_NUMBER not set in bot/.env. Run ./setup.sh first."
  exit 1
fi

if ! command -v ngrok &>/dev/null; then
  _err "ngrok not found. Install from https://ngrok.com/download"
  exit 1
fi

if ! command -v uv &>/dev/null; then
  _err "uv not found. Install from https://docs.astral.sh/uv/"
  exit 1
fi

_ok "bot/.env"
_ok "ngrok"
_ok "uv"

# ── ngrok ──────────────────────────────────────────────────────────────────────

_header "Starting ngrok tunnel"

# If ngrok is already running on 4040, reuse it rather than starting a new one.
if curl -s --max-time 1 http://localhost:4040/api/tunnels &>/dev/null; then
  _warn "ngrok already running on port 4040 — reusing existing tunnel."
else
  ngrok http 7860 > /dev/null 2>&1 &
  NGROK_PID=$!
  _ok "ngrok started (PID $NGROK_PID)"
fi

# Poll the ngrok local API until the HTTPS tunnel URL appears.
_info "Waiting for tunnel..."

NGROK_URL=""
for i in $(seq 1 20); do
  NGROK_URL=$(curl -s --max-time 1 http://localhost:4040/api/tunnels 2>/dev/null \
    | python3 -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
    for t in d.get('tunnels', []):
        if t.get('proto') == 'https':
            print(t['public_url'])
            break
except Exception:
    pass
" 2>/dev/null || true)
  if [[ -n "$NGROK_URL" ]]; then
    break
  fi
  sleep 0.5
done

if [[ -z "$NGROK_URL" ]]; then
  _err "ngrok tunnel did not appear after 10 seconds."
  _info "Make sure ngrok is authenticated: ngrok config add-authtoken <token>"
  exit 1
fi

_ok "Tunnel: $NGROK_URL"

# ── Register Daily webhook ─────────────────────────────────────────────────────

_header "Registering Daily webhook"

WEBHOOK_URL="${NGROK_URL}/daily-dialin-webhook"
_info "Phone:   $DAILY_PHONE"
_info "Webhook: $WEBHOOK_URL"
echo ""

if ! "$SCRIPT_DIR/tools/register-dialin.sh" "$WEBHOOK_URL"; then
  _err "Failed to register webhook with Daily."
  _info "Check DAILY_API_KEY and DAILY_DIALIN_PHONE_NUMBER in bot/.env."
  exit 1
fi

# ── Ready ──────────────────────────────────────────────────────────────────────

echo ""
echo -e "${_BOLD}${_GREEN}Ariadne is ready.${_RESET}"
echo ""
echo -e "  Call: ${_BOLD}${DAILY_PHONE}${_RESET}"
echo ""
echo "  When Ariadne answers, try:"
echo "  \"I want to think through a change in this repo."
echo "   Can you help me investigate where to start?\""
echo ""
echo -e "  ${_YELLOW}Ctrl-C to stop.${_RESET}"

# ── Start bot ─────────────────────────────────────────────────────────────────

_header "Ariadne logs"

cd "$SCRIPT_DIR/bot" && uv run bot.py -t daily --dialin
