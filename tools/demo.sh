#!/usr/bin/env bash
# div:ide demo runner.
#
# One-command bootstrap for "show off div:ide to a colleague":
#   * Verifies the API is up
#   * Prints the portal URL + admin sign-in hints
#   * Lists the scenarios the demo will load
#   * (Optionally) opens the portal in the default browser
#
# This is intentionally read-only: it does NOT modify the stack,
# provision VMs, or seed users. It just tells the operator
# what's running and where to click. The actual drill orchestration
# happens in the portal (Operate tab).
#
# Usage:
#   tools/demo.sh                  # default URL = localhost:8000
#   tools/demo.sh --api http://api:8000
#   tools/demo.sh --open            # also try to open the portal in a browser
#   tools/demo.sh --admin-sub alice --admin-pw change-me
#                                   # echo a "remember this" line for the
#                                   # bootstrap admin if one was used

set -euo pipefail

API="${DIVIDE_API:-http://localhost:8000}"
OPEN_BROWSER=0
ADMIN_SUB=""
ADMIN_PW=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --api)
      API="$2"
      shift 2
      ;;
    --open)
      OPEN_BROWSER=1
      shift
      ;;
    --admin-sub)
      ADMIN_SUB="$2"
      shift 2
      ;;
    --admin-pw)
      ADMIN_PW="$2"
      shift 2
      ;;
    -h|--help)
      sed -n '2,30p' "$0"
      exit 0
      ;;
    *)
      echo "error: unknown arg $1" >&2
      exit 1
      ;;
  esac
done

PORTAL_URL="${API%/}/portal/app/"
SETUP_URL="${API%/}/portal/"

bold() { printf "\033[1m%s\033[0m\n" "$*"; }
ok()   { printf "  \033[32mok\033[0m %s\n" "$*"; }
warn() { printf "  \033[33m!\033[0m %s\n" "$*"; }
err()  { printf "  \033[31mx\033[0m %s\n" "$*"; }

echo
bold "div:ide demo runner"
echo

# --- 1. Verify the API is up ------------------------------------------
if curl -fsS --max-time 3 "${API}/healthz" >/dev/null; then
  ok "API healthy at ${API}"
else
  err "API is not reachable at ${API}"
  echo
  echo "    Start the stack with:  make up"
  echo "    Or pass --api to point at a remote deployment."
  exit 2
fi

# --- 2. Verify the portal bundle exists --------------------------------
if ! curl -fsS --max-time 3 "${PORTAL_URL}" -o /dev/null; then
  warn "Portal ${PORTAL_URL} not responding — may not be built yet."
  echo "       Run:  cd services/portal/app && npm run build"
else
  ok "Portal served at ${PORTAL_URL}"
fi

# --- 3. List the scenarios the catalog returns -------------------------
echo
bold "Scenarios in the catalog:"
SCENARIOS_JSON="$(curl -fsS "${API}/api/v1/scenarios" || true)"
if [[ -n "${SCENARIOS_JSON}" ]]; then
  # Trivial grep-based pretty-print (avoid jq dependency).
  echo "${SCENARIOS_JSON}" | grep -oE '"name": *"[^"]*"' | sed 's/"name": *"//; s/"$//' | head -10 | sed 's/^/    - /'
else
  warn "Could not fetch /api/v1/scenarios"
fi

# --- 4. Bootstrap admin hint -------------------------------------------
if [[ -n "${ADMIN_SUB}" && -n "${ADMIN_PW}" ]]; then
  echo
  bold "Bootstrap admin credentials"
  echo "    sub:     ${ADMIN_SUB}"
  echo "    password: ${ADMIN_PW}"
  echo "    Sign in at: ${PORTAL_URL}"
else
  echo
  bold "Sign-in"
  echo "    If you bootstrapped an admin (DIVIDE_BOOTSTRAP_ADMIN_SUB +"
  echo "    _PASSWORD), sign in at ${PORTAL_URL} with that sub + password."
  echo
  echo "    Otherwise paste a token via the setup wizard at ${SETUP_URL}"
  echo "    (tools/issue_token.py on the host)."
fi

# --- 5. F4-UI tabs ------------------------------------------------------
echo
bold "F4-UI tabs to demo"
echo "    Dashboard   — KPI tiles (in-progress, today, success rate, my runs)"
echo "    Operate     — pick scenario + start drill (Start button is admin/lead/red)"
echo "    Observe     — live drill console (LIVE pulse badge, topology, audit feed)"
echo "    Admin       — PVE health + scenario library + user list + operator console"
echo "    History     — past runs with status filter"
echo "    Profile     — your runs scoped to you"

echo
bold "Cyber-range identity scenarios"
echo "    red-vs-blue-baseline    — 6 assets across red/router/blue (TopologyGraph)"
echo "    first-live-drill        — single-VM smoke (try POST /api/v1/drills)"
echo "    phish-to-ransom         — story-driven (good for narrating the demo)"
echo "    lateral-movement-baseline — Blue team baseline"

# --- 6. Optionally open the browser ------------------------------------
if [[ "${OPEN_BROWSER}" == "1" ]]; then
  echo
  if command -v xdg-open >/dev/null; then
    xdg-open "${PORTAL_URL}"
  elif command -v open >/dev/null; then
    open "${PORTAL_URL}"
  else
    warn "no xdg-open or open; please visit ${PORTAL_URL} manually"
  fi
fi

echo
ok "Demo runner done. Visit ${PORTAL_URL}"
