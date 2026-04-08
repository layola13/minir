#!/bin/bash
set -euo pipefail

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
TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('transcript_path',''))" 2>/dev/null || printf '')
TRANSCRIPT_PATH="${TRANSCRIPT_PATH/#\~/$HOME}"

log_line "PRE-COMPACT triggered for session $SESSION_ID"

if [ ! -f "$TRANSCRIPT_PATH" ]; then
    cat <<'HOOKJSON'
{
  "decision": "block",
  "reason": "PreCompact auto-save could not run because the transcript file was unavailable. Save this session to MemPalace manually before compaction continues."
}
HOOKJSON
    exit 0
fi

TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
SESSION_DIR="$SNAPSHOT_ROOT/$SESSION_ID"
SNAPSHOT_FILE="$SESSION_DIR/${TIMESTAMP}_precompact.jsonl"
mkdir -p "$SESSION_DIR"
cp "$TRANSCRIPT_PATH" "$SNAPSHOT_FILE"

set +e
PYTHONPATH="$REPO_DIR${PYTHONPATH:+:$PYTHONPATH}" python3 -m mempalace.autosave "$SNAPSHOT_FILE" --wing "$MEMPAL_WING" --agent "$MEMPAL_AGENT" --workspace-root "$WORKSPACE_ROOT" --trigger precompact --session-id "$SESSION_ID" >> "$STATE_DIR/hook.log" 2>&1
AUTOSAVE_EXIT=$?
set -e

if [ "$AUTOSAVE_EXIT" -eq 0 ]; then
    log_line "PRE-COMPACT auto-save persisted successfully (exit=$AUTOSAVE_EXIT) -> $SNAPSHOT_FILE"
    echo "{}"
else
    log_line "PRE-COMPACT auto-save failed (exit=$AUTOSAVE_EXIT) after snapshotting $SNAPSHOT_FILE"
    cat <<HOOKJSON
{
  "decision": "block",
  "reason": "PreCompact selective autosave failed after snapshotting $SNAPSHOT_FILE. Check ~/.mempalace/hook_state/hook.log and save manually before compaction continues."
}
HOOKJSON
fi
