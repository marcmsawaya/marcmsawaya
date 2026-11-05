#!/usr/bin/env bash
#
# Push the Istio memory dashboard and monitors into Datadog.
#
# Credentials are read from the environment and are never written to disk or
# passed on the command line (argv is visible to other processes via ps):
#
#   export DD_API_KEY=...     # Organization Settings -> API Keys
#   export DD_APP_KEY=...     # Organization Settings -> Application Keys
#   export DD_SITE=datadoghq.com   # or datadoghq.eu, us3/us5.datadoghq.com, ap1.datadoghq.com
#
#   ./apply.sh            # dry run: validate payloads, create nothing
#   ./apply.sh --push     # actually create the dashboard and monitors
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SITE="${DD_SITE:-datadoghq.com}"
API="https://api.${SITE}"
PUSH=0
[[ "${1:-}" == "--push" ]] && PUSH=1

die() { printf 'error: %s\n' "$1" >&2; exit 1; }

command -v curl >/dev/null || die "curl is required"
command -v python3 >/dev/null || die "python3 is required"

# Validate every payload before touching the network, so a typo fails locally
# rather than half way through creating resources.
for f in "$HERE"/dashboards/*.json "$HERE"/monitors/*.json; do
  python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$f" \
    || die "invalid JSON: $f"
done
echo "✓ all payloads are valid JSON"

if grep -rq 'REPLACE-ME' "$HERE/monitors"; then
  echo "! monitors still contain REPLACE-ME placeholders (notification handle / team tag)."
  echo "  Fill those in before pushing, or the alerts will fire into the void."
  [[ $PUSH -eq 1 ]] && die "refusing to push monitors with placeholder handles"
fi

if [[ $PUSH -eq 0 ]]; then
  echo
  echo "Dry run complete. Re-run with --push to create these in Datadog:"
  echo "  dashboard: $(python3 -c "import json;print(json.load(open('$HERE/dashboards/istio-memory.json'))['title'])")"
  for f in "$HERE"/monitors/*.json; do
    echo "  monitor:   $(python3 -c "import json;print(json.load(open('$f'))['name'])")"
  done
  exit 0
fi

[[ -n "${DD_API_KEY:-}" ]] || die "DD_API_KEY is not set"
[[ -n "${DD_APP_KEY:-}" ]] || die "DD_APP_KEY is not set"

post() { # post <api-path> <file>
  local path="$1" file="$2" body status
  body="$(curl -sS -w $'\n%{http_code}' -X POST "${API}${path}" \
    -H "Content-Type: application/json" \
    -H "DD-API-KEY: ${DD_API_KEY}" \
    -H "DD-APPLICATION-KEY: ${DD_APP_KEY}" \
    --data-binary "@${file}")"
  status="$(tail -n1 <<<"$body")"
  body="$(sed '$d' <<<"$body")"
  if [[ "$status" != 2* ]]; then
    printf 'FAILED (HTTP %s) %s\n%s\n' "$status" "$file" "$body" >&2
    return 1
  fi
  printf '%s' "$body"
}

echo "→ creating dashboard"
resp="$(post /api/v1/dashboard "$HERE/dashboards/istio-memory.json")"
echo "  https://app.${SITE}$(python3 -c "import json,sys;print(json.load(sys.stdin)['url'])" <<<"$resp")"

for f in "$HERE"/monitors/*.json; do
  echo "→ creating monitor $(basename "$f")"
  resp="$(post /api/v1/monitor "$f")"
  echo "  https://app.${SITE}/monitors/$(python3 -c "import json,sys;print(json.load(sys.stdin)['id'])" <<<"$resp")"
done

echo "done."
