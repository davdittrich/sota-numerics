gsd_tools() {
  if [ -z "${_GSD_TOOLS_ARGS_SET+x}" ]; then
    _GSD_TOOLS_ARGS_SET=1
    local _root
    # Anchored to the sourced file's own location, not the caller's working
    # directory (D-13): a host-set plugin-root variable wins when present,
    # matching the convention session-start.sh's own line 4 already uses;
    # BASH_SOURCE[0] falls back to this file's physical path for direct,
    # non-host invocation, where no such variable is set. There is
    # deliberately no `git rev-parse --show-toplevel` rung here any more --
    # that resolved the repository enclosing the invoking working directory,
    # so a hostile repository placed there could supply a node entry point
    # this function would then execute.
    _root="${CLAUDE_PLUGIN_ROOT:-}"
    if [ -z "$_root" ] && [ -n "${BASH_SOURCE[0]:-}" ]; then
      _root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)"
    fi
    if [ -n "$_root" ] && [ -f "$_root/gsd-core/bin/gsd-tools.cjs" ]; then
      _GSD_TOOLS_ARGS=(node "$_root/gsd-core/bin/gsd-tools.cjs")
    elif command -v gsd-tools >/dev/null 2>&1; then
      _GSD_TOOLS_ARGS=(gsd-tools)
    elif [ -f "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/gsd-core/bin/gsd-tools.cjs" ]; then
      _GSD_TOOLS_ARGS=(node "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/gsd-core/bin/gsd-tools.cjs")
    else
      _GSD_TOOLS_ARGS=()
    fi
  fi
  [ "${#_GSD_TOOLS_ARGS[@]}" -gt 0 ] || return 127
  "${_GSD_TOOLS_ARGS[@]}" "$@"
}
