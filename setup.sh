#!/usr/bin/env bash
set -uo pipefail

# ── Constants ──────────────────────────────────────────────────────────────────

_RED='\033[0;31m'
_GREEN='\033[0;32m'
_YELLOW='\033[1;33m'
_CYAN='\033[0;36m'
_BOLD='\033[1m'
_RESET='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Helpers ────────────────────────────────────────────────────────────────────

_header() {
  echo ""
  echo -e "${_BOLD}${_CYAN}── $1 ──${_RESET}"
  echo ""
}

_ok()   { echo -e "  ${_GREEN}✓${_RESET}  $1"; }
_warn() { echo -e "  ${_YELLOW}⚠${_RESET}  $1"; }
_err()  { echo -e "  ${_RED}✗${_RESET}  $1" >&2; }
_info() { echo "  $1"; }

# Read KEY from a .env-style file. Strips surrounding quotes.
# Returns empty string (exit 0) if file doesn't exist or key is absent.
_read_env_val() {
  local key="$1" file="${2:-}"
  [[ -f "$file" ]] || return 0
  { grep "^${key}=" "$file" 2>/dev/null || true; } \
    | head -1 | cut -d= -f2- | sed "s/^['\"]//;s/['\"]$//"
}

# Prompt with an optional default. Result in $_REPLY.
_ask() {
  local prompt="$1" default="${2:-}"
  if [[ -n "$default" ]]; then
    printf "  %s [%s]: " "$prompt" "$default"
  else
    printf "  %s: " "$prompt"
  fi
  read -r _REPLY || _REPLY=""
  [[ -z "$_REPLY" && -n "$default" ]] && _REPLY="$default"
}

# Hidden-input prompt. Result in $_REPLY.
_ask_secret() {
  local prompt="$1"
  printf "  %s: " "$prompt"
  read -r -s _REPLY || _REPLY=""
  echo ""
}

# Yes/no prompt. Returns 0 for yes, 1 for no. Default via second arg ("y"/"n").
_ask_yn() {
  local prompt="$1" default="${2:-y}" reply
  if [[ "$default" == "y" ]]; then
    printf "  %s [Y/n]: " "$prompt"
  else
    printf "  %s [y/N]: " "$prompt"
  fi
  read -r reply || reply=""
  reply="${reply:-$default}"
  [[ "$reply" =~ ^[Yy] ]]
}

# Back up a file with a timestamp suffix. Prints what it did.
_backup_file() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  local ts backup
  ts="$(date +%Y%m%d-%H%M%S)"
  backup="${file}.backup-${ts}"
  cp "$file" "$backup"
  _ok "Backed up $(basename "$file") → $(basename "$backup")"
}

# Compute 8-char SHA-256 hex digest of a string. Portable across macOS and Linux.
_compute_path_hash() {
  local input="$1"
  if command -v sha256sum &>/dev/null; then
    printf '%s' "$input" | sha256sum | cut -c1-8
  elif command -v shasum &>/dev/null; then
    printf '%s' "$input" | shasum -a 256 | cut -c1-8
  else
    printf '%s' "$input" | cksum | awk '{printf "%08x", $1}'
  fi
}

# Run a Daily REST API call and return the response body. Prints nothing on failure.
_daily_api() {
  local method="$1" path="$2" body="${3:-}"
  local args=(-s -X "$method"
    --header "Authorization: Bearer ${DAILY_API_KEY}"
    --header "Content-Type: application/json")
  [[ -n "$body" ]] && args+=(--data "$body")
  curl "${args[@]}" "https://api.daily.co/v1${path}" 2>/dev/null || true
}

# ── Welcome ────────────────────────────────────────────────────────────────────

echo ""
echo -e "${_BOLD}Welcome to Ariadne setup.${_RESET}"
echo ""
echo "  Ariadne lets you call your workstation, talk through a repo-aware"
echo "  engineering task, and generate an implementation brief for a coding agent."
echo ""
echo "  Before we continue:"
echo "  • Use a personal, open-source, or work-authorized repo."
echo "  • Audio, transcripts, and repo findings may go to configured AI providers."
echo "  • Logs and transcripts are stored locally under ~/.ariadne."
echo "  • Implementation briefs are stored in <repo>/.ariadne/briefs."
echo "  • See PRIVACY.md for full details."
echo ""
read -r -p "  Press Enter to continue..." || true

# ── Dependency checks ──────────────────────────────────────────────────────────

_header "Checking dependencies"

MISSING_REQUIRED=()

_check() {
  local tool="$1" required="${2:-required}" hint="${3:-}"
  if command -v "$tool" &>/dev/null; then
    _ok "$tool"
  elif [[ "$required" == "required" ]]; then
    _err "$tool — not found"
    [[ -n "$hint" ]] && _info "      Install: $hint"
    MISSING_REQUIRED+=("$tool")
  else
    _warn "$tool — not found (optional)"
    [[ -n "$hint" ]] && _info "      Install: $hint"
  fi
}

_check "python3"  required  "https://python.org (3.11+)"
_check "uv"       required  "https://docs.astral.sh/uv/"
_check "git"      required  "https://git-scm.com"
_check "curl"     required  ""
_check "codex"    required  "https://github.com/openai/codex"
_check "docker"   optional  ""
_check "ngrok"    optional  "https://ngrok.com/download"

if (( ${#MISSING_REQUIRED[@]} > 0 )); then
  echo ""
  _err "Missing required tools: ${MISSING_REQUIRED[*]}"
  _info "Install them and re-run ./setup.sh"
  exit 1
fi

# ── Identity ───────────────────────────────────────────────────────────────────

_header "Your identity"

EXISTING_USER_NAME="$(_read_env_val ARIADNE_USER_NAME "$SCRIPT_DIR/bot/.env")"

_ask "Your name" "${EXISTING_USER_NAME:-}"
USER_NAME="$_REPLY"
if [[ -z "$USER_NAME" ]]; then
  _err "Name is required."
  exit 1
fi

# ── Repo path ──────────────────────────────────────────────────────────────────

_header "Target repo"

EXISTING_REPO_PATH="$(_read_env_val ARIADNE_REPO_PATH "$SCRIPT_DIR/bot/.env")"

REPO_PATH=""
while true; do
  _ask "Absolute path to the repo Ariadne should investigate" "${EXISTING_REPO_PATH:-}"
  RAW_PATH="$_REPLY"

  # Expand tilde
  RAW_PATH="${RAW_PATH/#\~/$HOME}"

  if [[ -z "$RAW_PATH" ]]; then
    _err "Repo path is required."
    continue
  fi

  RESOLVED="$(cd "$RAW_PATH" 2>/dev/null && pwd)" || {
    _err "Path does not exist: $RAW_PATH"
    continue
  }

  if [[ ! -d "$RESOLVED" ]]; then
    _err "Not a directory: $RESOLVED"
    continue
  fi

  if git -C "$RESOLVED" rev-parse --git-dir &>/dev/null 2>&1; then
    _ok "Repo: $RESOLVED"
  else
    _warn "$RESOLVED is not a git repo."
    _ask_yn "Continue anyway?" "n" || continue
  fi

  REPO_PATH="$RESOLVED"
  break
done

REPO_NAME="$(basename "$REPO_PATH")"

# Project name — human label, falls back to repo folder name
EXISTING_PROJECT_NAME="$(_read_env_val ARIADNE_PROJECT_NAME "$SCRIPT_DIR/bot/.env")"
_ask "Project name (human label for this session)" "${EXISTING_PROJECT_NAME:-$REPO_NAME}"
PROJECT_NAME="${_REPLY:-$REPO_NAME}"

# ── API keys ───────────────────────────────────────────────────────────────────

_header "API keys"
_info "Keys are written only to bot/.env and never echoed."
echo ""

# Prompt for a key. If an existing value is present, allow keeping it.
_prompt_key() {
  local var="$1" label="$2"
  local existing
  existing="$(_read_env_val "$var" "$SCRIPT_DIR/bot/.env")"
  if [[ -n "$existing" ]]; then
    printf "  %s [keep existing, press Enter to keep]: " "$label"
    read -r -s _KEY_REPLY || _KEY_REPLY=""
    echo ""
    if [[ -z "$_KEY_REPLY" ]]; then
      _KEY_REPLY="$existing"
      _ok "$label: keeping existing"
    fi
  else
    _ask_secret "$label"
    _KEY_REPLY="$_REPLY"
  fi
}

_prompt_key "OPENAI_API_KEY"    "OpenAI API key"
OPENAI_API_KEY="$_KEY_REPLY"

_prompt_key "DEEPGRAM_API_KEY"  "Deepgram API key"
DEEPGRAM_API_KEY="$_KEY_REPLY"

_prompt_key "CARTESIA_API_KEY"  "Cartesia API key"
CARTESIA_API_KEY="$_KEY_REPLY"

_prompt_key "DAILY_API_KEY"     "Daily API key"
DAILY_API_KEY="$_KEY_REPLY"

for _VAR in OPENAI_API_KEY DEEPGRAM_API_KEY CARTESIA_API_KEY DAILY_API_KEY; do
  if [[ -z "${!_VAR}" ]]; then
    _err "${_VAR} is required."
    exit 1
  fi
done

# ── Daily phone number ─────────────────────────────────────────────────────────

_header "Daily dial-in phone number"

_info "Ariadne uses Daily for voice calls over the phone."
_info "Don't have a Daily account? https://dashboard.daily.co/signup"
echo ""

DAILY_PHONE=""
EXISTING_PHONE="$(_read_env_val DAILY_DIALIN_PHONE_NUMBER "$SCRIPT_DIR/bot/.env")"

# Look up existing numbers on the account
_info "Checking your Daily account for existing phone numbers..."
NUMBERS_JSON="$(_daily_api GET /purchased-phone-numbers)"
NUMBER_COUNT=0
FIRST_NUMBER=""

_py_extract() {
  # Parse JSON from stdin and print a value. Usage: echo "$json" | _py_extract '<expr>'
  # <expr> is evaluated with `d` as the parsed dict.
  python3 -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
    result = $1
    print(result if result is not None else '')
except Exception:
    print('')
"
}

if [[ -n "$NUMBERS_JSON" ]]; then
  NUMBER_COUNT="$(echo "$NUMBERS_JSON" | _py_extract 'd.get("total_count", 0)')"
  FIRST_NUMBER="$(echo "$NUMBERS_JSON" | _py_extract '(d.get("data") or [{}])[0].get("number", "")')"
fi

if [[ "$NUMBER_COUNT" -gt 0 && -n "$FIRST_NUMBER" ]]; then
  _ok "Found $NUMBER_COUNT phone number(s) on your account."
  echo ""

  if [[ "$NUMBER_COUNT" -eq 1 ]]; then
    _info "Phone number: $FIRST_NUMBER"
    echo ""
    if _ask_yn "Use this number?" "y"; then
      DAILY_PHONE="$FIRST_NUMBER"
    fi
  else
    echo "$NUMBERS_JSON" | python3 -c "
import json, sys
d = json.loads(sys.stdin.read())
for i, n in enumerate(d.get('data', []), 1):
    print(f'  [{i}] {n[\"number\"]}')
"
    echo ""
    _ask "Enter the number to use (or paste it directly)" "${EXISTING_PHONE:-$FIRST_NUMBER}"
    DAILY_PHONE="$_REPLY"
  fi
fi

if [[ -z "$DAILY_PHONE" ]]; then
  echo ""
  _info "No phone number selected."
  echo ""
  if _ask_yn "Purchase a new US/Canada Daily phone number? (charges apply to your Daily account)" "n"; then
    _info "Purchasing phone number..."
    BUY_JSON="$(_daily_api POST /buy-phone-number)"
    DAILY_PHONE="$(echo "$BUY_JSON" | _py_extract 'd.get("number", "")')"
    if [[ -n "$DAILY_PHONE" ]]; then
      _ok "Purchased: $DAILY_PHONE"
    else
      _warn "Purchase returned an unexpected response. Check your Daily dashboard."
      _info "Response: $BUY_JSON"
      echo ""
      _ask "Enter a Daily phone number to continue (or leave blank to skip)" "${EXISTING_PHONE:-}"
      DAILY_PHONE="$_REPLY"
    fi
  else
    _ask "Enter your existing Daily phone number (or leave blank to skip)" "${EXISTING_PHONE:-}"
    DAILY_PHONE="$_REPLY"
  fi
fi

if [[ -z "$DAILY_PHONE" ]]; then
  _warn "No phone number configured. Dial-in will not work until you set"
  _warn "DAILY_DIALIN_PHONE_NUMBER in bot/.env and run ./tools/register-dialin.sh."
fi

# ── Ariadne home directories ───────────────────────────────────────────────────

_header "Creating Ariadne home"

ARIADNE_HOME="${HOME}/.ariadne"
mkdir -p \
  "${ARIADNE_HOME}/logs" \
  "${ARIADNE_HOME}/project-backgrounds" \
  "${ARIADNE_HOME}/cache"

_ok "~/.ariadne/logs"
_ok "~/.ariadne/project-backgrounds"
_ok "~/.ariadne/cache"

# ── Repo .ariadne/briefs + gitignore ──────────────────────────────────────────

_header "Repo artifact folder"

BRIEFS_DIR="${REPO_PATH}/.ariadne/briefs"
mkdir -p "$BRIEFS_DIR"
_ok "Created: $BRIEFS_DIR"

# Gitignore check
GITIGNORE="${REPO_PATH}/.gitignore"
ARIADNE_IGNORED=false
if [[ -f "$GITIGNORE" ]] && grep -qE '^\.ariadne/?$' "$GITIGNORE" 2>/dev/null; then
  ARIADNE_IGNORED=true
fi

if $ARIADNE_IGNORED; then
  _ok ".ariadne/ is already gitignored"
else
  echo ""
  _warn ".ariadne/ is not in ${GITIGNORE}."
  _info ""
  _info "  Ariadne writes implementation briefs under ${BRIEFS_DIR}."
  _info "  Adding .ariadne/ to .gitignore keeps them out of version control."
  echo ""
  if _ask_yn "Add .ariadne/ to this repo's .gitignore?" "y"; then
    printf '\n# Ariadne artifacts\n.ariadne/\n' >> "$GITIGNORE"
    _ok "Added .ariadne/ to $(basename "$GITIGNORE")"
  else
    _warn "Skipped. Be careful not to commit .ariadne/ files."
  fi
fi

# ── Compute project background path (must match paths.py hash) ────────────────

REPO_HASH="$(_compute_path_hash "$REPO_PATH")"
PROJECT_BG_PATH="${ARIADNE_HOME}/project-backgrounds/${REPO_NAME}-${REPO_HASH}/PROJECT_BACKGROUND.md"

# ── Generate .env files ────────────────────────────────────────────────────────

_header "Writing configuration"

# Root .env — Docker Compose host paths
ROOT_ENV="${SCRIPT_DIR}/.env"
_backup_file "$ROOT_ENV"
cat > "$ROOT_ENV" <<EOF
# Docker Compose host-side volume paths.
# These are not read by the bot — they tell Compose where to mount volumes.
ARIADNE_REPO_HOST_PATH="${REPO_PATH}"
ARIADNE_BRIEFS_HOST_PATH="${REPO_PATH}/.ariadne"
LOGS_HOST_PATH="${ARIADNE_HOME}/logs"
EOF
_ok "Wrote: .env (Docker Compose volume paths)"

# bot/.env — read by the bot runtime at startup
BOT_ENV="${SCRIPT_DIR}/bot/.env"
_backup_file "$BOT_ENV"
cat > "$BOT_ENV" <<EOF
# User and project identity
ARIADNE_USER_NAME="${USER_NAME}"
ARIADNE_PROJECT_NAME="${PROJECT_NAME}"

# Provider keys
OPENAI_API_KEY="${OPENAI_API_KEY}"
DEEPGRAM_API_KEY="${DEEPGRAM_API_KEY}"
CARTESIA_API_KEY="${CARTESIA_API_KEY}"
DAILY_API_KEY="${DAILY_API_KEY}"
DAILY_API_URL="https://api.daily.co/v1"
EOF

if [[ -n "$DAILY_PHONE" ]]; then
  echo "DAILY_DIALIN_PHONE_NUMBER=\"${DAILY_PHONE}\"" >> "$BOT_ENV"
else
  echo "# DAILY_DIALIN_PHONE_NUMBER=\"+1...\"" >> "$BOT_ENV"
fi

cat >> "$BOT_ENV" <<EOF

# Model
OPENAI_MODEL="gpt-4.1"

# Ariadne paths
ARIADNE_HOME="${ARIADNE_HOME}"
ARIADNE_REPO_PATH="${REPO_PATH}"
ARIADNE_BRIEFS_DIR="${REPO_PATH}/.ariadne/briefs"
LOGS_DIR="${ARIADNE_HOME}/logs"
ARIADNE_PROJECT_BACKGROUND_PATH="${PROJECT_BG_PATH}"

# Debug server — enable for local development only
ARIADNE_DEBUG_SERVER_ENABLED=false
ARIADNE_DEBUG_SERVER_HOST=127.0.0.1
ARIADNE_DEBUG_SERVER_PORT=8765

# Session idle timeout in seconds
ARIADNE_IDLE_TIMEOUT_SECONDS=300
EOF
_ok "Wrote: bot/.env"

# ── Install dependencies ───────────────────────────────────────────────────────

_header "Python dependencies"

if _ask_yn "Run 'uv sync' to install bot dependencies?" "y"; then
  echo ""
  _info "Running: cd bot && uv sync"
  echo ""
  (cd "$SCRIPT_DIR/bot" && uv sync)
  echo ""
  _ok "Dependencies installed"
fi

# ── Project background refresh ────────────────────────────────────────────────

_header "Project background"

_info "Ariadne loads a PROJECT_BACKGROUND.md at session start to orient itself"
_info "to the repo without needing an investigation on every question."
echo ""
_info "This runs Codex read-only against ${REPO_PATH}."
_info "It takes roughly 1–2 minutes."
echo ""

if _ask_yn "Refresh project background now?" "y"; then
  echo ""
  ARIADNE_REPO_PATH="$REPO_PATH" \
  ARIADNE_PROJECT_BACKGROUND_PATH="$PROJECT_BG_PATH" \
    "$SCRIPT_DIR/tools/refresh_project_background.sh"
  echo ""
  _ok "Project background written to:"
  _info "  $PROJECT_BG_PATH"
else
  _info "Skipped. Run this later:"
  _info "  ARIADNE_REPO_PATH=${REPO_PATH} \\"
  _info "  ARIADNE_PROJECT_BACKGROUND_PATH=${PROJECT_BG_PATH} \\"
  _info "  ./tools/refresh_project_background.sh"
fi

# ── Summary ────────────────────────────────────────────────────────────────────

echo ""
echo -e "${_BOLD}${_GREEN}Setup complete.${_RESET}"
echo ""
echo "  User:                  ${USER_NAME}"
echo "  Project:               ${PROJECT_NAME}"
echo "  Repo:                  ${REPO_PATH}"
echo "  Logs:                  ${ARIADNE_HOME}/logs"
echo "  Project background:    ${PROJECT_BG_PATH}"
echo "  Implementation briefs: ${BRIEFS_DIR}"
if [[ -n "$DAILY_PHONE" ]]; then
  echo "  Phone number:          ${DAILY_PHONE}"
fi
echo ""

if _ask_yn "Ready to start Ariadne and try a test call?" "y"; then
  exec "$SCRIPT_DIR/start_ariadne.sh"
else
  echo ""
  _info "When you're ready, run:"
  echo ""
  echo "  ./start_ariadne.sh"
  echo ""
fi
