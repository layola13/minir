#!/bin/bash
set -euo pipefail

SAVE_INTERVAL=15
STATE_DIR="$HOME/.mempalace/hook_state"
SNAPSHOT_ROOT="$STATE_DIR/transcript_snapshots"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MEMPAL_WING="${MEMPAL_WING:-wing_claude_code}"
MEMPAL_AGENT="${MEMPAL_AGENT:-mempalace_hook}"
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

if [ "$STOP_HOOK_ACTIVE" = "True" ] || [ "$STOP_HOOK_ACTIVE" = "true" ]; then
    echo "{}"
    exit 0
fi

if [ -f "$TRANSCRIPT_PATH" ]; then
    EXCHANGE_COUNT=$(python3 -c "
import json
count = 0
with open('$TRANSCRIPT_PATH', encoding='utf-8', errors='replace') as f:
    for line in f:
        try:
            entry = json.loads(line)
            msg = entry.get('message', {})
            if isinstance(msg, dict) and msg.get('role') == 'user':
                content = msg.get('content', '')
                if isinstance(content, str) and '<command-message>' in content:
                    continue
                count += 1
        except Exception:
            pass
print(count)
" 2>/dev/null)
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
  "reason": "AUTO-SAVE was due, but the transcript file was unavailable. Save this session to MemPalace manually before continuing."
}
HOOKJSON
    exit 0
fi

TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
SESSION_DIR="$SNAPSHOT_ROOT/$SESSION_ID"
SNAPSHOT_FILE="$SESSION_DIR/${TIMESTAMP}_stop.jsonl"
mkdir -p "$SESSION_DIR"
cp "$TRANSCRIPT_PATH" "$SNAPSHOT_FILE"

log_line "TRIGGERING SAVE at exchange $EXCHANGE_COUNT -> $SNAPSHOT_FILE"

set +e
PYTHONPATH="$REPO_DIR${PYTHONPATH:+:$PYTHONPATH}" python3 -m mempalace.autosave "$SNAPSHOT_FILE" --wing "$MEMPAL_WING" --agent "$MEMPAL_AGENT" --workspace-root "$WORKSPACE_ROOT" --trigger stop --session-id "$SESSION_ID" >> "$STATE_DIR/hook.log" 2>&1
AUTOSAVE_EXIT=$?
set -e

if [ "$AUTOSAVE_EXIT" -eq 0 ]; then
    if ! printf '%s\n' "$EXCHANGE_COUNT" > "$LAST_SAVE_FILE"; then
        log_line "AUTO-SAVE succeeded but failed to update last save marker: $LAST_SAVE_FILE"
    fi
    log_line "AUTO-SAVE persisted successfully (exit=$AUTOSAVE_EXIT)"
    echo "{}"
else
    log_line "AUTO-SAVE failed (exit=$AUTOSAVE_EXIT) after snapshotting $SNAPSHOT_FILE"
    cat <<HOOKJSON
{
  "decision": "block",
  "reason": "AUTO-SAVE was due, but selective autosave failed after snapshotting $SNAPSHOT_FILE. Check ~/.mempalace/hook_state/hook.log and save manually before continuing."
}
HOOKJSON
fi
