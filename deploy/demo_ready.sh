#!/usr/bin/env bash
# Wait until every demo surface of a MarisAI deployment answers, and show how
# old each layer's data is.
#
#   deploy/demo_ready.sh http://<public-ip> [--ask] [--timeout SECONDS]
#
# Polls every 10 s (default limit 15 min). Exits 0 once every row is green,
# 1 if the limit is reached. --ask also sends one real question to the
# assistant (costs one LLM turn).
set -uo pipefail

BASE="${1:?usage: demo_ready.sh BASE_URL [--ask] [--timeout SECONDS]}"
BASE="${BASE%/}"
shift
ASK=0
LIMIT=900
while [ $# -gt 0 ]; do
  case "$1" in
    --ask) ASK=1 ;;
    --timeout) LIMIT="$2"; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

# name|path|json field holding the data time ("" = none)
SURFACES=(
  "site|/|"
  "dashboard health|/api/dashboard/health|generated_at"
  "sea surface temp|/api/ocean/sst/meta|timestamp"
  "wind|/api/ocean/wind/meta|timestamp"
  "currents|/api/ocean/currents/meta|timestamp"
  "stokes drift|/api/ocean/stokes/meta|timestamp"
  "drift|/api/ocean/drift/meta|timestamp"
  "eddies|/api/ocean/eddies|timestamp"
  "heatwaves|/api/ocean/heatwaves|timestamp"
)

json_field() {
  python3 -c '
import json, sys
from datetime import datetime, timezone
field = sys.argv[1]
try:
    data = json.load(sys.stdin)
except Exception:
    print("-|-"); sys.exit()
value = data.get(field) if isinstance(data, dict) else None
if not value:
    print("-|-"); sys.exit()
try:
    when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    hours = (datetime.now(timezone.utc) - when).total_seconds() / 3600
    age = f"{hours:.0f} h" if hours < 48 else f"{hours / 24:.1f} d"
    print(f"{when:%Y-%m-%d %H:%M}Z|{age}")
except ValueError:
    print(f"{value}|-")
' "$1"
}

start=$(date +%s)
while true; do
  all_green=1
  rows=()
  for entry in "${SURFACES[@]}"; do
    IFS='|' read -r name path field <<<"$entry"
    body=$(mktemp)
    code=$(curl -s -m 20 -o "$body" -w '%{http_code}' "$BASE$path" || echo 000)
    if [ -n "$field" ] && [ "$code" = "200" ]; then
      IFS='|' read -r when age < <(json_field "$field" < "$body")
    else
      when="-"; age="-"
    fi
    rm -f "$body"
    if [ "$code" = "200" ]; then status="OK"; else status="WAIT ($code)"; all_green=0; fi
    rows+=("$(printf '%-18s %-12s %-18s %s' "$name" "$status" "$when" "$age")")
  done

  if [ "$ASK" = "1" ] && [ "$all_green" = "1" ]; then
    answer=$(curl -s -m 120 -X POST "$BASE/api/v1/chat" -H 'content-type: application/json' \
      -d '{"message":"In one sentence, what can you do?","client_id":"demo-ready-check"}' \
      | python3 -c 'import json,sys
try: print("OK" if json.load(sys.stdin).get("answer") else "NO ANSWER")
except Exception: print("ERROR")')
    [ "$answer" = "OK" ] || all_green=0
    rows+=("$(printf '%-18s %-12s' "assistant" "$answer")")
  fi

  elapsed=$(( $(date +%s) - start ))
  clear 2>/dev/null || true
  printf 'MarisAI readiness - %s - %ss elapsed\n\n' "$BASE" "$elapsed"
  printf '%-18s %-12s %-18s %s\n' "SURFACE" "STATUS" "DATA TIME" "AGE"
  printf '%s\n' "${rows[@]}"

  if [ "$all_green" = "1" ]; then
    printf '\nAll surfaces ready. Open %s/\n' "$BASE"
    exit 0
  fi
  if [ "$elapsed" -ge "$LIMIT" ]; then
    printf '\nNot all surfaces ready after %ss.\n' "$elapsed"
    exit 1
  fi
  sleep 10
done
