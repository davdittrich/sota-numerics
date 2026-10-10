#!/usr/bin/env bash
# Vendored per plugin so one plugin's edit cannot change another's. Re-grants the
# capability at global ("user") scope on SessionStart when the bundle hash
# drifts. Never aborts the session: no `set -e`.
set -u

CAP_ID="${1:-}"

# Defense in depth (ASVS V5): validate the id shape gsd-core enforces.
[[ "$CAP_ID" =~ ^[a-z][a-z0-9-]*$ ]] || exit 0

# Absolute: the bundle hash only separates plugin roots if its paths are rooted.
PLUGIN_ROOT="$(CDPATH= cd "${CLAUDE_PLUGIN_ROOT:-$(dirname "$0")/..}" 2>/dev/null && pwd)" || exit 0
# The plugin root is the capability: `capability install` reads its
# capability.json and copies the whole directory. Only these paths are what the
# capability runs, so only they are hashed: an edit to tests or docs must not
# reinstall. The trailing slash walks a directory even when it is a symlink.
BUNDLE_DIR="$PLUGIN_ROOT"
BUNDLE_PATHS=(capability.json fragments/ scripts/)
[ -f "$BUNDLE_DIR/capability.json" ] || exit 0

# Portable hash tool selection: macOS ships shasum, not sha256sum.
if command -v sha256sum >/dev/null 2>&1; then
  HASH_CMD=(sha256sum)
elif command -v shasum >/dev/null 2>&1; then
  HASH_CMD=(shasum -a 256)
else
  exit 0
fi

# _esc <string> -- fork-free; sets global _E. Backslash first, so any later
# backslash is an escape introducer, then newline and space: injective.
_esc() {
  _E="${1//\\/\\\\}"
  _E="${_E//$'\n'/\\n}"
  _E="${_E// /\\s}"
}

# _bundle_records -- NUL-delimited paths on stdin, one tagged line each: `l`
# symlink (tested before -f, so a link to a directory is not followed), `f`
# regular file, `o` anything else. readlink runs with a sentinel `.` appended
# and stripped: command substitution would otherwise drop a trailing newline in
# the target, itself a collision. Files are hashed via stdin so the tool never
# prints a path (GNU sha256sum escapes it, perl shasum does not). A failed
# readlink or hash returns 1 rather than record bytes never read.
_bundle_records() {
  local p _t _h _pe
  while IFS= read -r -d '' p; do
    if [ -L "$p" ]; then
      _t="$(readlink "$p" && printf '.')" || return 1
      _t="${_t%.}"
      _esc "$p"; _pe="$_E"
      _esc "$_t"
      printf 'l %s %s\n' "$_pe" "$_E"
    elif [ -f "$p" ]; then
      _h="$("${HASH_CMD[@]}" < "$p")" || return 1
      _h="${_h%% *}"
      _esc "$p"
      printf 'f %s %s\n' "$_E" "$_h"
    else
      _esc "$p"
      printf 'o %s\n' "$_E"
    fi
  done
}

# Hash of the BUNDLE_PATHS the install copies: file content (bound to path),
# symlink target, and the path of everything else (an added empty directory).
# A missing path fails the walk. Mode is not hashed: a chmod is a stale miss, not unsafe.
# The stream is only hashed, never parsed, so it need only be injective: kind
# tag, `_esc`, one record per entry.
# `set -o pipefail` is load-bearing: without it an unreadable directory is
# masked by `_bundle_records`' exit status and a partial walk reads as
# complete (case J5). find's stderr is dropped so the refusal below reaches
# the user.
bundle_hash() {
  local _list _p _abs=()
  for _p in "${BUNDLE_PATHS[@]}"; do _abs+=("$BUNDLE_DIR/$_p"); done
  _list="$(set -o pipefail; find "${_abs[@]}" -print0 2>/dev/null | _bundle_records)" || return 1
  printf '%s\n' "$_list" | LC_ALL=C sort | "${HASH_CMD[@]}" | awk '{print $1}'
}

# One sidecar per capability id, matching the single global mirror it
# describes; roots sharing an id share it by design (NEW_HASH covers absolute
# paths, so a root switch reinstalls). Never gsd-core's own
# .gsd-capabilities.json or ~/.gsd/consent.json (its schemas).
STATE_FILE="${GSD_HOME:-$HOME}/.gsd/capability-auto-install-$CAP_ID.hash"

OLD_HASH=""
# A symlinked sidecar is read as no recorded hash, not followed: a writer could
# otherwise point it at the current digest and switch auto-install off. That
# fails safe (installs) and the install recreates a regular file. Residual:
# the -L test and the cat are two syscalls (no shell offers O_NOFOLLOW).
[ ! -L "$STATE_FILE" ] && [ -f "$STATE_FILE" ] && [ -r "$STATE_FILE" ] && OLD_HASH="$(cat "$STATE_FILE" 2>/dev/null)"
if ! NEW_HASH="$(bundle_hash)"; then
  echo "capability-auto-install: the $CAP_ID bundle directory could not be read in full, so what the global mirror would receive cannot be verified; refusing to install it at global scope" >&2
  exit 0
fi

# Fast path: an unchanged bundle exits silently without spawning node. The
# sidecar only records what the mirror held when written, so also require the
# mirror's directory, manifest and checker (a deleted mirror must be repaired).
_MIRROR="${GSD_HOME:-$HOME}/.gsd/capabilities/$CAP_ID"
[ "$NEW_HASH" = "$OLD_HASH" ] && [ -d "$_MIRROR" ] && [ -f "$_MIRROR/capability.json" ] &&
  [ -f "$_MIRROR/scripts/check-alternatives.py" ] && exit 0

# Fail closed: a git that cannot answer is not "safe" (`command -v` alone
# misses a git on PATH that exits non-zero).
if ! command -v git >/dev/null 2>&1 || ! git --version >/dev/null 2>&1; then
  echo "capability-auto-install: git is unusable, so $CAP_ID bundle provenance cannot be verified; refusing to install it at global scope" >&2
  exit 0
fi

# Global install publishes machine-wide, so only already-published bytes may
# be installed: this plugin is developed in a worktree the host loads. No
# refusal writes STATE_FILE, so a later session retries once published.
# Ownership, not enclosure: only a repository that *tracks* the bundle speaks
# for its bytes (README "What the Claude hooks do").
#
# TRACKED is 0 when the repository tracks any BUNDLE_PATHS entry (apply the
# publication checks), 1 when it answered and tracks none (guard does not
# apply), 128 when git did not answer -- never read as "untracked". Not
# `--error-unmatch`: with several pathspecs it exits 1 when any one is
# unmatched, so a partly tracked bundle would skip the checks (case S3). The
# rows are enumerated in the tests header.
#
# unverifiable_repo() decides the 128 case: `--git-dir` succeeding means a
# repository exists and did not answer; otherwise walk the ancestors -- an
# uninspectable .git is assumed a repository, one holding a HEAD is one git
# declined, an inspectable .git without HEAD is walked past.
unverifiable_repo() {
  git -C "$BUNDLE_DIR" rev-parse --git-dir >/dev/null 2>&1 && return 0
  local _d="$BUNDLE_DIR" _g _prev
  while :; do
    _g="$_d/.git"
    if [ -e "$_g" ] &&
       ! { [ -d "$_g" ] && [ -r "$_g" ] && [ -x "$_g" ] && [ ! -e "$_g/HEAD" ]; }; then
      return 0
    fi
    # Stop when dirname stops moving, not at "/": a relative path converges on
    # "." and would hang.
    _prev="$_d"
    _d="$(dirname "$_d")"
    [ "$_d" = "$_prev" ] && return 1
  done
}

TRACKED=0
if ! _LS="$(git -C "$BUNDLE_DIR" ls-files -- "${BUNDLE_PATHS[@]}" 2>/dev/null)"; then
  TRACKED=128
elif [ -z "$_LS" ]; then
  TRACKED=1
fi
if [ "$TRACKED" -eq 0 ]; then
  # gsd-core rejects symlinks, and a committed link passes every check below
  # (git compares the link, not its target). Each path is tested bare as well:
  # find on `fragments/` follows a symlinked top-level directory.
  _LINKS="$(for _p in "${BUNDLE_PATHS[@]}"; do [ -L "$BUNDLE_DIR/${_p%/}" ] && echo "$_p"; done
            find "${BUNDLE_PATHS[@]/#/$BUNDLE_DIR/}" -type l -print -quit 2>/dev/null)"
  if [ -n "$_LINKS" ]; then
    echo "capability-auto-install: the $CAP_ID bundle contains a symlink, which gsd-core rejects; refusing to install it at global scope" >&2
    exit 0
  fi
  # `status` reads the index, which `update-index --assume-unchanged` and
  # `--skip-worktree` silence, so an edit would report clean and the sidecar
  # make the miss permanent (cases J2, J3). `ls-files -v` tags a plain entry H;
  # anything else was told not to be checked. Sparse checkout sets
  # skip-worktree, so it is refused too (case J9; the file is gone from disk).
  #
  # Capture the status before the output: piping into `grep` takes grep's
  # status and hides a failed `ls-files` (case J10).
  if ! INDEX_TAGS="$(git -C "$BUNDLE_DIR" ls-files -v -- "${BUNDLE_PATHS[@]}" 2>/dev/null)"; then
    echo "capability-auto-install: git could not list the index entries for the $CAP_ID bundle, so whether the index hides edits cannot be determined; refusing to install it at global scope" >&2
    exit 0
  fi
  if printf '%s\n' "$INDEX_TAGS" | grep -q '^[^H]'; then
    echo "capability-auto-install: the index marks $CAP_ID bundle entries assume-unchanged or skip-worktree, so git will not report edits to them; refusing to install it at global scope" >&2
    exit 0
  fi
  # Each option states what this question needs, not what repo config gives;
  # the flag -> case map is in the tests header, as is the residual (a
  # `.gitattributes` clean filter).
  #
  # The exit status is read before the output: empty output from a `status` that
  # failed is indistinguishable from empty output from a clean tree (case J1).
  if ! DIRTY="$(git -c core.fsmonitor= -C "$BUNDLE_DIR" status --porcelain --ignored \
                    --untracked-files=all --ignore-submodules=none -- "${BUNDLE_PATHS[@]}" 2>/dev/null)"; then
    echo "capability-auto-install: git could not report the state of the $CAP_ID bundle, so its contents cannot be verified; refusing to install it at global scope" >&2
    exit 0
  fi
  if [ -n "$DIRTY" ]; then
    echo "capability-auto-install: $CAP_ID bundle has uncommitted or ignored files; refusing to install it at global scope" >&2
    exit 0
  fi
  # origin/HEAD and origin/main are local refs: passing proves HEAD is an
  # ancestor of the last fetched tip, not that a server holds it now. A round
  # trip per SessionStart would put the capability behind network and
  # credentials; a local ref suffices against the dev-worktree accident (K1).
  #
  # Fail closed: an unresolvable upstream means we cannot prove even that much,
  # and a guard that cannot verify must not answer "safe".
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
elif [ "$TRACKED" -ne 1 ] && unverifiable_repo; then
  echo "capability-auto-install: git cannot read the repository holding the $CAP_ID bundle, so its provenance cannot be verified; refusing to install it at global scope" >&2
  exit 0
fi

# gsd_tools() is sourced inside the timed child so nothing outside the timeout
# runs before the install decision. A missing hooks/gsd-tools.sh leaves it
# undefined: exit 127, no sidecar, retry (case L2). Sourcing in the child
# keeps the resolver's BASH_SOURCE fallback on the real file.

# A directory copy and a JSON write behind one `node` start: seconds. 60 is a
# loose bound for a cold start on a loaded or network-mounted home. The
# invocation and the message both read it, so they cannot drift.
INSTALL_TIMEOUT=60

# -k 5: SIGKILL a child that ignores SIGTERM. `timeout` is coreutils; macOS has
# `gtimeout` only with coreutils, and with neither _TIMEOUT is empty and the
# install runs unbounded. -k is GNU: probe it, else use a bare bound (not exit 125).
_TIMEOUT=()
for _t in timeout gtimeout; do
  command -v "$_t" >/dev/null 2>&1 || continue
  if "$_t" -k 1 1 true >/dev/null 2>&1; then _TIMEOUT=("$_t" -k 5 "$INSTALL_TIMEOUT")
  else _TIMEOUT=("$_t" "$INSTALL_TIMEOUT"); fi
  break
done

# gsd_tools is a shell function, so run it inside `bash -c`; PLUGIN_ROOT and
# BUNDLE_DIR arrive as $1/$2 so neither must survive quoting twice.
_INSTALL_CHILD='[ -f "$1/hooks/gsd-tools.sh" ] && . "$1/hooks/gsd-tools.sh"; gsd_tools capability install "$2" --scope global --yes'

# Absolute spec: a relative one would resolve against the user's cwd. The
# "${_TIMEOUT[@]+...}" form is deliberate: a bare empty array aborts under
# `set -u` on bash 3.2 (macOS).
"${_TIMEOUT[@]+"${_TIMEOUT[@]}"}" bash -c "$_INSTALL_CHILD" _ "$PLUGIN_ROOT" "$BUNDLE_DIR" >/dev/null 2>&1
INSTALL_STATUS=$?

# Failure branches break the silent `|| true` convention and write no
# STATE_FILE: unattended, silence would leave the capability inactive for good.
# Re-hash after the install: if the bytes moved while it ran, the mirror is not
# described by NEW_HASH, so record nothing and retry next session.
REHASH=""; REHASH_STATUS=0
[ "$INSTALL_STATUS" -eq 0 ] && { REHASH="$(bundle_hash)"; REHASH_STATUS=$?; }
if [ "$INSTALL_STATUS" -eq 0 ] && [ "$REHASH_STATUS" -ne 0 ]; then
  echo "capability-auto-install: the $CAP_ID bundle could not be re-read after the install; not recording it as installed" >&2
elif [ "$INSTALL_STATUS" -eq 0 ] && [ "$REHASH" != "$NEW_HASH" ]; then
  echo "capability-auto-install: the $CAP_ID bundle changed during the install; not recording it as installed" >&2
elif [ "$INSTALL_STATUS" -eq 0 ]; then
  printf 'Auto-installed capability: %s (user scope)\n' "$CAP_ID"
  mkdir -p "$(dirname "$STATE_FILE")" 2>/dev/null
  # Unlink first so the redirection creates a fresh regular file instead of
  # following a link at STATE_FILE (`rm -f` removes the link, not its target).
  # A directory there makes both fail harmlessly: no sidecar, retry next
  # session. Residual: a racing attacker could re-plant the link between rm
  # and redirection; closing it needs O_NOFOLLOW, which no shell offers, and
  # the threat model already grants write access to this directory.
  rm -f "$STATE_FILE" 2>/dev/null
  printf '%s' "$NEW_HASH" > "$STATE_FILE" 2>/dev/null
elif [ "$INSTALL_STATUS" -eq 127 ]; then
  echo "capability-auto-install: gsd-tools not found; $CAP_ID not installed" >&2
elif { [ "$INSTALL_STATUS" -eq 124 ] || [ "$INSTALL_STATUS" -eq 137 ]; } && [ "${#_TIMEOUT[@]}" -gt 0 ]; then
  # 137 is the -k SIGKILL of a child that ignored SIGTERM. Only when the
  # wrapper was used: an install that itself exits 124 with no `timeout` must
  # not be mislabelled a kill. No refusal tail on the message -- D0 selects on
  # that tail, and a killed install is a failure, not a refusal.
  echo "capability-auto-install: capability install for $CAP_ID exceeded ${INSTALL_TIMEOUT}s and was killed; not installed" >&2
else
  echo "capability-auto-install: capability install failed for $CAP_ID (exit $INSTALL_STATUS)" >&2
fi

exit 0
