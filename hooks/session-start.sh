#!/usr/bin/env bash
set -u

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

bash "$PLUGIN_ROOT/hooks/capability-auto-install.sh" sota-numerics || true

if [ -f "$PLUGIN_ROOT/hooks/gsd-tools.sh" ]; then
  . "$PLUGIN_ROOT/hooks/gsd-tools.sh"
  ENABLED="$(gsd_tools config-get sota-numerics.enabled --default true 2>/dev/null)"; ENABLED_STATUS=$?
  if [ "$ENABLED_STATUS" -eq 127 ]; then
    ENABLED=true
  elif [ "$ENABLED_STATUS" -ne 0 ]; then
    echo "sota-numerics: gsd_tools config-get sota-numerics.enabled failed (exit $ENABLED_STATUS); disabling advisory banner" >&2
    ENABLED=false
  fi
else
  ENABLED=true
fi
ENABLED="$(printf '%s' "$ENABLED" | tr -d '"')"

if [ "$ENABLED" != "true" ]; then
  exit 0
fi

ROLE="${1:-}"
case "$ROLE" in
  planner|executor|verifier) ;;
  *) ROLE=generic ;;
esac

case "$ROLE" in
  planner) FRAMING='Planning: name 2+ current alternatives per non-trivial mechanism choice, each with a dated citation, and state which ranked criterion (performance > simplicity/LOC > ecosystem > maintenance) decided the pick -- pair foundational citations (Kahan, IEEE 754) with a current in-window source. This capability ALSO declares a blocking plan:post gate that mechanically enforces this on every plan -- the advisory framing below is qualified here, not purely advisory.' ;;
  executor) FRAMING="Executing: derive numeric parameters from first principles or the problem's actual scale, prefer numerically stable formulations, avoid cancellation and silent error propagation, and favor efficiency over simplicity where they conflict." ;;
  verifier) FRAMING="Verifying: flag shipped-mechanism drift from the plan's justified pick, silent precision or scope loss, and unmeasured performance claims as findings, not blockers -- this capability's only gate already fired at plan:post, not here." ;;
  *) FRAMING='SOTA/efficiency/numerical-stability steering: prefer mathematically correct, precision-preserving, well-cited mechanism choices.' ;;
esac

printf 'SOTA-NUMERICS -- advisory steering (plan:post also carries a blocking Alternatives Considered gate)\n%s\n' "$FRAMING"

exit 0
