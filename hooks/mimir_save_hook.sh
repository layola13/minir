#!/bin/bash
set -euo pipefail

SAVE_INTERVAL=15
STATE_DIR="$HOME/.mimir/hook_state"
SNAPSHOT_ROOT="$STATE_DIR/transcript_snapshots"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MEMPAL_WING="${MEMPAL_WING:-wing_claude_code}"
MEMPAL_AGENT="${MEMPAL_AGENT:-mimir_hook}"
WORKSPACE_ROOT="${CLAUDE_PROJECT_DIR:-$REPO_DIR}"
mkdir -p "$STATE_DIR" "$SNAPSHOT_ROOT"

log_line() {
    printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$1" >> "$STATE_DIR/hook.log" || true
}

INPUT=$(cat)

SESSION_ID=$(printf '%s' "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('session_id','unknown'))" 2>/dev/null || printf 'unknown')
STOP_HOOK_ACTIVE=$(printf '%s' "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('stop_hook_active', False))" 2>/dev/null || printf 'False')
TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('transcript_path',''))" 2>/dev/null || printf '')
TRANSCRIPT_PATH="${TRANSCRIPT_PATH/#\~/$HOME}"

if command -v flock >/dev/null 2>&1; then
    LOCK_FILE="$STATE_DIR/${SESSION_ID}.stop.lock"
    exec 9>"$LOCK_FILE"
    if ! flock -n 9; then
        log_line "Session $SESSION_ID: duplicate concurrent Stop hook, skipped"
        echo "{}"
        exit 0
    fi
fi

log_line "Stop payload: session=$SESSION_ID stop_hook_active=$STOP_HOOK_ACTIVE transcript_path=${TRANSCRIPT_PATH:-<empty>} exists=$([ -f "$TRANSCRIPT_PATH" ] && echo yes || echo no)"

if [ "$STOP_HOOK_ACTIVE" = "True" ] || [ "$STOP_HOOK_ACTIVE" = "true" ]; then
    echo "{}"
    exit 0
fi

if [ -f "$TRANSCRIPT_PATH" ]; then
    EXCHANGE_COUNT=$(python3 - "$TRANSCRIPT_PATH" <<'PY'
import json
import sys

path = sys.argv[1]
claude_count = 0
codex_response_count = 0
codex_event_count = 0

def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if "text" in item:
                    parts.append(str(item.get("text", "")))
        return " ".join(part for part in parts if part).strip()
    if isinstance(content, dict):
        if "text" in content:
            return str(content.get("text", ""))
    return ""

def _is_noise(text):
    normalized = text.strip()
    if not normalized:
        return True
    if "<command-message>" in normalized:
        return True
    if normalized.startswith("<environment_context>"):
        return True
    return False

with open(path, encoding="utf-8", errors="replace") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        if not isinstance(entry, dict):
            continue

        # Claude transcript format.
        msg = entry.get("message")
        if isinstance(msg, dict) and msg.get("role") in {"user", "human"}:
            text = _text(msg.get("content", ""))
            if not _is_noise(text):
                claude_count += 1
            continue

        # Codex transcript format (preferred to avoid double-counting event_msg).
        if entry.get("type") == "response_item":
            payload = entry.get("payload", {})
            if isinstance(payload, dict) and payload.get("type") == "message" and payload.get("role") == "user":
                text = _text(payload.get("content", ""))
                if not _is_noise(text):
                    codex_response_count += 1
            continue

        # Fallback for older Codex traces.
        if entry.get("type") == "event_msg":
            payload = entry.get("payload", {})
            if isinstance(payload, dict) and payload.get("type") == "user_message":
                text = str(payload.get("message", ""))
                if not _is_noise(text):
                    codex_event_count += 1
            continue

if codex_response_count > 0:
    print(codex_response_count)
elif claude_count > 0:
    print(claude_count)
else:
    print(codex_event_count)
PY
)
else
    EXCHANGE_COUNT=0
fi

LAST_SAVE_FILE="$STATE_DIR/${SESSION_ID}_last_save"
LAST_SAVE=0
if [ -f "$LAST_SAVE_FILE" ]; then
    LAST_SAVE=$(cat "$LAST_SAVE_FILE")
fi

SINCE_LAST=$((EXCHANGE_COUNT - LAST_SAVE))
log_line "Session $SESSION_ID: $EXCHANGE_COUNT exchanges, $SINCE_LAST since last save"

if [ "$SINCE_LAST" -lt "$SAVE_INTERVAL" ] || [ "$EXCHANGE_COUNT" -le 0 ]; then
    echo "{}"
    exit 0
fi

if [ ! -f "$TRANSCRIPT_PATH" ]; then
    cat <<'HOOKJSON'
{
  "decision": "block",
  "reason": "AUTO-SAVE was due, but the transcript file was unavailable. Save this session to Mimir manually before continuing."
}
HOOKJSON
    exit 0
fi

TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
SESSION_DIR="$SNAPSHOT_ROOT/$SESSION_ID"
SNAPSHOT_FILE="$SESSION_DIR/${TIMESTAMP}_stop.jsonl"
mkdir -p "$SESSION_DIR"
cp "$TRANSCRIPT_PATH" "$SNAPSHOT_FILE"

# ... (previous setup code)
log_line "TRIGGERING SKELETON SAVE at exchange $EXCHANGE_COUNT -> $SNAPSHOT_FILE"

set +e
PYTHONPATH="$REPO_DIR${PYTHONPATH:+:$PYTHONPATH}" python3 -m mimir.autosave "$SNAPSHOT_FILE" --wing "$MEMPAL_WING" --agent "$MEMPAL_AGENT" --workspace-root "$WORKSPACE_ROOT" --trigger stop --session-id "$SESSION_ID" >> "$STATE_DIR/hook.log" 2>&1
AUTOSAVE_EXIT=$?
set -e

if [ "$AUTOSAVE_EXIT" -eq 0 ]; then
    # Update last save marker even if 0 memories extracted, because the skeleton was successfully processed.
    if ! printf '%s\n' "$EXCHANGE_COUNT" > "$LAST_SAVE_FILE"; then
        log_line "SKELETON SAVE succeeded but failed to update last save marker: $LAST_SAVE_FILE"
    fi
    log_line "SKELETON SAVE persisted successfully (exit=$AUTOSAVE_EXIT)"
    echo "{}"
else
    log_line "SKELETON SAVE failed (exit=$AUTOSAVE_EXIT) after snapshotting $SNAPSHOT_FILE"
    cat <<HOOKJSON
{
  "decision": "block",
  "reason": "Skeleton auto-save failed after snapshotting $SNAPSHOT_FILE. Check ~/.mimir/hook_state/hook.log and save manually before continuing."
}
HOOKJSON
fi
