# github-mcp provider for start-ticket.sh   — requires: jq
#
# For sessions where gh can't authenticate (Claude Code cloud). A bash script can't
# call MCP tools, so the calling agent reads each issue through the GitHub MCP tools
# and writes $START_TICKET_MCP_DIR/<id>.json:
#   {"number":12,"title":"…","body":"…","state":"OPEN","url":"…","labels":["bug"],"parent":9}
# Tracker writes (assign, comment) are the agent's job too: mark_in_progress is a
# no-op and read_state reports "unknown", which /start step 1a repairs.

# tracker.sh uses the same handoff for listing and creating: the agent writes
# $TRACKER_MCP_DIR/issues-open.json and issues-closed.json (arrays of
# {id,title,state,labels:[names],url,updated,body}), and create requests are written
# to $TRACKER_MCP_DIR/create/<n>.json ({title,body,labels}) for the agent to file.

_ghmcp_file() { printf '%s/%s.json' "${START_TICKET_MCP_DIR:-}" "$1"; }

provider::available() {
  command -v jq >/dev/null || return 1
  { [ -n "${START_TICKET_MCP_DIR:-}" ] && [ -d "$START_TICKET_MCP_DIR" ]; } ||
    { [ -n "${TRACKER_MCP_DIR:-}" ] && [ -d "$TRACKER_MCP_DIR" ]; }
}

provider::list_issues() {  # <state> <limit>
  local state="$1" s f out="[]"
  for s in $([ "$state" = all ] && echo "open closed" || echo "$state"); do
    f="${TRACKER_MCP_DIR:-}/issues-$s.json"
    [ -f "$f" ] || { echo "no handoff file $f: list $s issues with the GitHub MCP tools first" >&2; return 1; }
    out="$(jq -s '.[0] + .[1]' <(echo "$out") "$f")" || return 1
  done
  printf '%s' "$out"
}

# A script can't call MCP: record the request for the agent and report "cannot create"
# (exit 2), so the caller queues the finding and the agent files the request.
provider::create_issue() {  # <title> <body-file> <labels-csv>
  local dir="${TRACKER_MCP_DIR:-}/create" n
  n="$(printf '%s' "$1" | cksum | cut -d' ' -f1)"
  mkdir -p "$dir" && jq -n --arg t "$1" --rawfile b "$2" --arg l "$3" \
    '{title:$t, body:$b, labels:($l | split(",") | map(select(length > 0)))}' > "$dir/$n.json" || return 1
  return 2
}

provider::fetch() {
  local id="$1" f state label
  [[ "$id" =~ ^[0-9]+$ ]] || { echo "invalid ticket id '$id': the github-mcp provider takes GitHub issue numbers" >&2; return 1; }
  f="$(_ghmcp_file "$id")"
  [ -f "$f" ] || { echo "no handoff file for #$id ($f): fetch it with the GitHub MCP tools first (see /start step 1)" >&2; return 1; }
  jq -e . "$f" >/dev/null 2>&1 || { echo "handoff file for #$id is not valid JSON: $f" >&2; return 1; }
  state="$(jq -r '.state // ""' "$f" | tr '[:lower:]' '[:upper:]')"
  [ "$state" = OPEN ] || { echo "issue #$id is ${state:-of unknown state}, not OPEN" >&2; return 1; }
  ST_TITLE="$(jq -r '.title // ""' "$f")"
  ST_BODY="$(jq -r '.body // ""' "$f")"
  ST_URL="$(jq -r '.url // ""' "$f")"
  ST_PARENT="$(jq -r '.parent // empty' "$f")"
  ST_REF="GitHub issue #${id}"
  ST_TYPE=""
  while IFS= read -r label; do
    case "$label" in
      type:*)    ST_TYPE="${label#*:}"; break ;;
      bug|bugfix|fix) ST_TYPE="fix"; break ;;
      feat|feature|enhancement) ST_TYPE="feat"; break ;;
      chore|docs|refactor|test|perf|ci|build) ST_TYPE="$label"; break ;;
      documentation) ST_TYPE="docs"; break ;;
    esac
  done < <(jq -r '.labels[]? | (.name? // .) | ascii_downcase' "$f" 2>/dev/null || true)
  ST_BRANCH=""
}

provider::create_worktree() { "$WORKTREE_MANAGER" "$ST_BRANCH" ${ST_WORKTREE:+--dir-name "$ST_WORKTREE"}; }

provider::mark_in_progress() { return 0; }

provider::read_state() { printf 'unknown'; return 1; }
