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

# The three role bodies below are pointers, not copies: each fragment they name is
# injected into this same subagent's context window, so restating its rules here would
# be a second copy at the same altitude. The four contributions declare `onError` as
# skip, so a contribution that fails to render fails silently. That is the failsafe this
# form gives up -- on such a silent render failure the subagent now learns only that the
# capability is active and that the step carries a blocking gate, not what the gate
# wants, where before this change the banner was a full backup copy of the rule text.
# Recorded under gsd-beads-25vc.21.5, row 1.
case "$ROLE" in
  planner) FRAMING='Planning: the injected sota-numerics planner fragment carries the Alternatives Considered rules the blocking plan:post gate enforces.' ;;
  executor) FRAMING='Executing: the injected sota-numerics executor fragment carries the numerical-stability, efficiency and quiet-output rules.' ;;
  verifier) FRAMING='Verifying: the injected sota-numerics verifier fragment carries the review items; they are findings, not blockers.' ;;
  *) FRAMING='SOTA/efficiency/numerical-stability steering: prefer mathematically correct, precision-preserving, well-cited mechanism choices.' ;;
esac

printf 'SOTA-NUMERICS -- advisory steering (plan:post also carries a blocking Alternatives Considered gate)\n%s\n' "$FRAMING"

exit 0
