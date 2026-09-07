#!/usr/bin/env bash
# Vendored auto-install hook (D-05: vendored copy per plugin, not shared at
# runtime -- see hooks/capability-auto-install.sh in the ponytail-everywhere repo
# for the byte-identical sibling copy, Phase 10.1 Plan 02).
#
# Detects bundle drift via a whole-directory hash and re-grants the
# capability at global ("user") scope on every SessionStart (D-01..D-03).
# Never aborts the session: no `set -e`.
set -u

CAP_ID="${1:-}"

# Defense in depth (ASVS V5): call sites only ever pass a hard-coded literal,
# but validate the id shape gsd-core itself enforces before it reaches any
# path construction.
[[ "$CAP_ID" =~ ^[a-z][a-z0-9-]*$ ]] || exit 0

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
BUNDLE_DIR="$PLUGIN_ROOT/.gsd/capabilities/$CAP_ID"
[ -d "$BUNDLE_DIR" ] || exit 0

# Portable hash tool selection (Assumption A3: macOS ships no sha256sum).
if command -v sha256sum >/dev/null 2>&1; then
  HASH_CMD=(sha256sum)
elif command -v shasum >/dev/null 2>&1; then
  HASH_CMD=(shasum -a 256)
else
  exit 0
fi

# Whole-bundle-directory hash (D-03): LC_ALL=C-sorted list of every path
# under the bundle (files AND directories, so an added empty directory is
# caught -- Assumption A1) followed by the concatenated contents of the
# sorted regular files.
bundle_hash() {
  {
    find "$BUNDLE_DIR" \( -type f -o -type d \) | LC_ALL=C sort
    find "$BUNDLE_DIR" -type f | LC_ALL=C sort | while IFS= read -r _f; do cat "$_f"; done
  } | "${HASH_CMD[@]}" | awk '{print $1}'
}

# One sidecar file per capability id (Pitfall 4) so vendored copies in
# different plugins cannot race or stomp each other's cached hash. Never
# gsd-core's own .gsd-capabilities.json / ~/.gsd/consent.json -- those are
# gsd-core-owned schemas this script must not write into.
STATE_FILE="${GSD_HOME:-$HOME}/.gsd/capability-auto-install-$CAP_ID.hash"

OLD_HASH=""
[ -r "$STATE_FILE" ] && OLD_HASH="$(cat "$STATE_FILE" 2>/dev/null)"
NEW_HASH="$(bundle_hash)"

# D-02 fast path: unchanged bundle exits silently, never spawns node.
[ "$NEW_HASH" = "$OLD_HASH" ] && exit 0

# Fail closed before the guard runs: every question below is asked through git,
# and a git that cannot answer is not an answer of "safe" (gsd-beads-iy2).
# `command -v` alone is insufficient -- a git that is on PATH but non-functional
# makes every probe below exit non-zero, which the guard would read as "not a
# repo" and proceed. Probing an actual invocation covers both.
if ! command -v git >/dev/null 2>&1 || ! git --version >/dev/null 2>&1; then
  echo "capability-auto-install: git is unusable, so $CAP_ID bundle provenance cannot be verified; refusing to install it at global scope" >&2
  exit 0
fi

# Installing at global scope publishes to every project on the machine, so only
# already-published bytes may be installed. When this plugin is developed in a
# git worktree that sits inside another project, the host loads that worktree as
# a plugin and this hook would otherwise install work in progress machine-wide
# (gsd-beads-d2b, gsd-beads-28g). Two refusals express that one invariant: the
# tree must be clean, and HEAD must already be reachable from the published
# upstream. Neither refusal writes STATE_FILE, so a later session retries once
# the bundle is published.
#
# The predicate is ownership, not enclosure (gsd-beads-70t): the guard applies
# exactly when the enclosing repository *tracks* this bundle, which is the only
# repository whose publication state says anything about these bytes. Enclosure
# was wrong in both directions -- a consumer who versions ~/.claude in git had
# the bundle reported as untracked ("uncommitted changes", forever) or, if
# plugins/ was gitignored, had the capability gated on an unrelated repo's
# origin. Both of those are untracked here, so both skip; a plugin-cache bundle
# is inside no repository at all, so ls-files fails and it skips too. A bundle
# tracked by a monorepo that vendors this plugin is still guarded, which is the
# direction an unverifiable case must err in.
if git -C "$BUNDLE_DIR" ls-files --error-unmatch . >/dev/null 2>&1; then
  if [ -n "$(git -C "$BUNDLE_DIR" status --porcelain -- . 2>/dev/null)" ]; then
    echo "capability-auto-install: $CAP_ID bundle has uncommitted changes; refusing to install it at global scope" >&2
    exit 0
  fi
  PUBLISHED_REF=""
  for _ref in origin/HEAD origin/main; do
    if git -C "$BUNDLE_DIR" rev-parse --verify --quiet "$_ref" >/dev/null 2>&1; then
      PUBLISHED_REF="$_ref"
      break
    fi
  done
  # Fail closed: an unresolvable upstream means we cannot prove the bytes are
  # published, and a guard that cannot verify must not answer "safe".
  if [ -z "$PUBLISHED_REF" ] ||
     ! git -C "$BUNDLE_DIR" merge-base --is-ancestor HEAD "$PUBLISHED_REF" 2>/dev/null; then
    echo "capability-auto-install: $CAP_ID bundle HEAD is not published (${PUBLISHED_REF:-no upstream ref found}); refusing to install it at global scope" >&2
    exit 0
  fi
fi

# gsd_tools() resolver, inlined verbatim from
# hooks/gsd-tools.sh in the ponytail-everywhere repo rather than sourced -- the
# root plugin ships no gsd-tools.sh, and an inline copy keeps this script
# dependency-free within its own plugin (D-05).
gsd_tools() {
  if [ -z "${_GSD_TOOLS_ARGS_SET+x}" ]; then
    _GSD_TOOLS_ARGS_SET=1
    local _root
    _root="$(git rev-parse --show-toplevel 2>/dev/null)"
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

# Spec is always the absolute bundle dir (Pattern 2) -- a relative spec would
# resolve against the end user's cwd, not the plugin. Prose "user scope"
# (D-01) maps to the CLI's literal --scope global value (Pitfall 1).
gsd_tools capability install "$BUNDLE_DIR" --scope global --yes >/dev/null 2>&1
INSTALL_STATUS=$?

if [ "$INSTALL_STATUS" -eq 0 ]; then
  printf 'Auto-installed capability: %s (user scope)\n' "$CAP_ID"
  mkdir -p "$(dirname "$STATE_FILE")" 2>/dev/null
  printf '%s' "$NEW_HASH" > "$STATE_FILE" 2>/dev/null
elif [ "$INSTALL_STATUS" -eq 127 ]; then
  # D-04: deliberate divergence from this repo's usual silent `|| true`
  # fail-open convention -- this path is unattended, so silence would leave
  # a capability permanently inactive with nobody the wiser. Do not "fix"
  # this back to silent. Do NOT write STATE_FILE, so the next session retries.
  echo "capability-auto-install: gsd-tools not found; $CAP_ID not installed" >&2
else
  # D-04, same rationale as above -- install command ran and failed.
  echo "capability-auto-install: capability install failed for $CAP_ID (exit $INSTALL_STATUS)" >&2
fi

exit 0
