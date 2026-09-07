#!/usr/bin/env bash
# Vendored auto-install hook (D-05: vendored copy per plugin, not shared at
# runtime). The ponytail-everywhere repo carries a sibling copy of this file
# which has not yet taken the publication guard added in sota-numerics 0.2.0,
# so the two have diverged and neither may be edited as a copy of the other.
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

# Absolute, whatever the host supplied: the bundle hash below is what keeps two
# plugin roots serving one capability id from sharing a fast path, and it can
# only do that if the paths it covers are rooted. A relative CLAUDE_PLUGIN_ROOT
# would make the hash identical for every root.
PLUGIN_ROOT="$(cd "${CLAUDE_PLUGIN_ROOT:-$(dirname "$0")/..}" 2>/dev/null && pwd)" || exit 0
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

# Whole-bundle-directory hash (D-03). `capability install` copies the directory,
# so every entry in it becomes bytes the global mirror serves and every entry
# must therefore reach the hash: files contribute their own digest, which binds
# content to path; symlinks contribute their target, so adding or retargeting
# one is drift; everything else -- directories, and any FIFO or socket that
# should not be there -- contributes its path, so an added empty directory is
# caught (Assumption A1). Concatenating raw contents instead, as this did, is
# ambiguous at file boundaries: {a:"xy", b:""} and {a:"x", b:"y"} produce the
# same path list and the same byte stream. `-exec sh -c` rather than GNU
# `find -printf`, which BSD find does not have.
bundle_hash() {
  find "$BUNDLE_DIR" \
       -type l -exec sh -c 'for p in "$@"; do printf "%s -> %s\n" "$p" "$(readlink "$p")"; done' _ {} + \
    -o -type f -exec "${HASH_CMD[@]}" {} + \
    -o -print |
    LC_ALL=C sort | "${HASH_CMD[@]}" | awk '{print $1}'
}

# One sidecar file per capability id (Pitfall 4), matching the single global
# mirror that id owns: the file records which bytes that mirror currently holds.
# Two plugin roots exporting the same id do share this file, and that is
# correct, not a race -- they share the mirror it describes. NEW_HASH covers the
# bundle's absolute paths as well as its contents (bundle_hash above), so a
# switch between roots is a hash mismatch and reinstalls, rather than a fast
# path that would leave the mirror holding the other root's bytes. The sidecar
# is never gsd-core's own .gsd-capabilities.json or ~/.gsd/consent.json --
# those are gsd-core-owned schemas this script must not write into.
STATE_FILE="${GSD_HOME:-$HOME}/.gsd/capability-auto-install-$CAP_ID.hash"

OLD_HASH=""
[ -r "$STATE_FILE" ] && OLD_HASH="$(cat "$STATE_FILE" 2>/dev/null)"
NEW_HASH="$(bundle_hash)"

# D-02 fast path: unchanged bundle exits silently, never spawns node.
[ "$NEW_HASH" = "$OLD_HASH" ] && exit 0

# Fail closed: every question below is asked through git, and a git that cannot
# answer is not an answer of "safe". `command -v` alone misses a
# git that is on PATH but exits non-zero, which reads as "not a repo".
if ! command -v git >/dev/null 2>&1 || ! git --version >/dev/null 2>&1; then
  echo "capability-auto-install: git is unusable, so $CAP_ID bundle provenance cannot be verified; refusing to install it at global scope" >&2
  exit 0
fi

# Installing at global scope publishes to every project on the machine, so only
# already-published bytes may be installed: this plugin is developed in a git
# worktree the host loads as a plugin, and the hook would otherwise mirror work
# in progress machine-wide. No refusal writes
# STATE_FILE, so a later session retries once the bundle is published.
#
# Ownership, not enclosure: only a repository that *tracks* the
# bundle says anything about these bytes. A plugin cache belongs to no
# repository, and a consumer who versions ~/.claude does not track the bundle
# either, so both skip the guard; a monorepo vendoring the plugin does track it
# and stays guarded, the direction an unverifiable case must err in.
if git -C "$BUNDLE_DIR" ls-files --error-unmatch . >/dev/null 2>&1; then
  # --ignored, because `capability install` copies the directory, not the index:
  # an ignored file inside the bundle is unpublished byte that would be mirrored
  # machine-wide, and plain `status --porcelain` reports it as clean
  # (running the test suite leaves __pycache__/ inside the bundle).
  if [ -n "$(git -C "$BUNDLE_DIR" status --porcelain --ignored -- . 2>/dev/null)" ]; then
    echo "capability-auto-install: $CAP_ID bundle has uncommitted or ignored files; refusing to install it at global scope" >&2
    exit 0
  fi
  # Fail closed: an unresolvable upstream means we cannot prove the bytes are
  # published, and a guard that cannot verify must not answer "safe".
  PUBLISHED="$(git -C "$BUNDLE_DIR" rev-parse --verify --quiet origin/HEAD ||
               git -C "$BUNDLE_DIR" rev-parse --verify --quiet origin/main)"
  if [ -z "$PUBLISHED" ]; then
    echo "capability-auto-install: $CAP_ID bundle has no origin/HEAD or origin/main to prove it is published; refusing to install it at global scope" >&2
    exit 0
  fi
  if ! git -C "$BUNDLE_DIR" merge-base --is-ancestor HEAD "$PUBLISHED" 2>/dev/null; then
    echo "capability-auto-install: $CAP_ID bundle HEAD is not published (not an ancestor of $PUBLISHED); refusing to install it at global scope" >&2
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

# Absolute spec (Pattern 2): a relative one would resolve against the end user's
# cwd, not the plugin.
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
