#!/usr/bin/env bash
# Vendored auto-install hook: each plugin ships its own copy of this file
# rather than sourcing a shared one, so a plugin stays self-contained and one
# plugin's edit cannot change another's behaviour.
#
# Detects bundle drift via a whole-directory hash and re-grants the
# capability at global ("user") scope on every SessionStart. Global scope is
# what the CLI calls --scope global and what the prose calls "user scope".
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

# Portable hash tool selection: macOS ships shasum, not sha256sum.
if command -v sha256sum >/dev/null 2>&1; then
  HASH_CMD=(sha256sum)
elif command -v shasum >/dev/null 2>&1; then
  HASH_CMD=(shasum -a 256)
else
  exit 0
fi

# Whole-bundle-directory hash. `capability install` copies the directory, so
# what this has to detect is a change in what that copy would carry. Three
# properties of each entry reach the hash and one does not. Content: a file
# contributes its own digest, bound to its path. Link target: a symlink
# contributes what it points at, so adding or retargeting one is drift. Path:
# everything else -- directories, and any FIFO or socket that should not be
# there -- contributes its path, so an added empty directory is caught. Mode
# does not: `chmod 755` on a bundle file leaves this digest identical while the
# directory copy carries the bit. That miss is stale, not unsafe -- an unmirrored
# local chmod is drift the mirror does not receive, and the mirror keeps the
# mode it was installed with -- but it is a miss. `-exec sh -c` rather than GNU
# `find -printf`, which BSD find does not have.
# A partial walk is not a hash of this bundle, so the status is read rather than
# piped into sort, and find's stderr is suppressed so the refusal reaches the
# user instead of `find: Permission denied` (case J5).
bundle_hash() {
  local _list
  _list="$(find "$BUNDLE_DIR" \
       -type l -exec sh -c 'for p in "$@"; do printf "%s -> %s\n" "$p" "$(readlink "$p")"; done' _ {} + \
    -o -type f -exec "${HASH_CMD[@]}" {} + \
    -o -print 2>/dev/null)" || return 1
  printf '%s\n' "$_list" | LC_ALL=C sort | "${HASH_CMD[@]}" | awk '{print $1}'
}

# One sidecar file per capability id, matching the single global
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
if ! NEW_HASH="$(bundle_hash)"; then
  echo "capability-auto-install: the $CAP_ID bundle directory could not be read in full, so what the global mirror would receive cannot be verified; refusing to install it at global scope" >&2
  exit 0
fi

# Fast path: an unchanged bundle exits silently and never spawns node, which
# is what keeps this affordable on every SessionStart.
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
# Ownership, not enclosure: only a repository that *tracks* the bundle says
# anything about these bytes. Versioning ~/.claude encloses without tracking and
# is unaffected; a monorepo vendoring the plugin tracks it and stays guarded.
# README's "What the Claude hooks do" works the marketplace-cache shapes through.
#
# `ls-files --error-unmatch` answers with three exit codes and this guard has to
# keep all three apart: 0 tracked, so the publication checks below apply; 1 a
# repository answered and does not track these bytes, so the guard does not; 128
# git did not answer, which must not be read as "untracked". The eleven rows
# those three split into are enumerated in tests/test-capability-auto-install.sh.
#
# unverifiable_repo() decides that last case on evidence git cannot supply.
# `--git-dir` succeeding means git found a repository it can open, so the 128
# came from the index alone -- there is a repository and it did not answer.
# Otherwise walk the ancestors: a .git we cannot inspect might be a repository
# and must be assumed to be one, and a .git holding a HEAD is a repository git
# declined for ownership or format. A .git that is inspectable and holds no
# HEAD -- a stray empty directory -- is not a repository and is walked past.
unverifiable_repo() {
  git -C "$BUNDLE_DIR" rev-parse --git-dir >/dev/null 2>&1 && return 0
  local _d="$BUNDLE_DIR" _g _prev
  while :; do
    _g="$_d/.git"
    if [ -e "$_g" ] &&
       ! { [ -d "$_g" ] && [ -r "$_g" ] && [ -x "$_g" ] && [ ! -e "$_g/HEAD" ]; }; then
      return 0
    fi
    # Stop when dirname stops moving, not at a literal "/": a relative path
    # converges on "." and would hang here. Keying on the walk, not on how
    # PLUGIN_ROOT is built, keeps that unreachable.
    _prev="$_d"
    _d="$(dirname "$_d")"
    [ "$_d" = "$_prev" ] && return 1
  done
}

TRACKED=0
git -C "$BUNDLE_DIR" ls-files --error-unmatch . >/dev/null 2>&1 || TRACKED=$?
if [ "$TRACKED" -eq 0 ]; then
  # `status` answers out of the index, and the index can be told to stop
  # looking. `update-index --assume-unchanged` -- the flag a developer sets on a
  # file they are hand-editing, not an exotic attack -- and `--skip-worktree`
  # both make an edited tracked file report clean, and the sidecar then makes
  # that miss permanent. `-v` tags a plain cached entry H, lower-cases the tag
  # for assume-unchanged and uses S for skip-worktree, so anything that is not H
  # is an entry git has been told not to check. `diff --quiet HEAD` is not an
  # alternative here: it honours the same bit and reports no difference.
  # core.sparseCheckout needs no separate handling: it excludes paths by setting
  # skip-worktree, so an out-of-cone bundle entry is tagged S and refused here
  # (case J9). `-c core.sparseCheckout=false` would not have helped -- sparse
  # checkout also removes the file from disk, so there is nothing for `status`
  # to compare (measured, not assumed).
  #
  # The status is captured before the output, for the same reason `status`'s is
  # below: piping straight into `grep` makes the pipeline exit with grep's
  # status, so an `ls-files` that failed reads as "no suspicious tags" and the
  # guard proceeds on evidence it never obtained (case J10).
  if ! INDEX_TAGS="$(git -C "$BUNDLE_DIR" ls-files -v -- . 2>/dev/null)"; then
    echo "capability-auto-install: git could not list the index entries for the $CAP_ID bundle, so whether the index hides edits cannot be determined; refusing to install it at global scope" >&2
    exit 0
  fi
  if printf '%s\n' "$INDEX_TAGS" | grep -q '^[^H]'; then
    echo "capability-auto-install: the index marks $CAP_ID bundle entries assume-unchanged or skip-worktree, so git will not report edits to them; refusing to install it at global scope" >&2
    exit 0
  fi
  # Every option below states what this question needs rather than inheriting
  # whatever the repository configured: each is a setting that redirects
  # `status` away from the worktree bytes the directory copy would carry.
  #
  # --untracked-files=all, because `status.showUntrackedFiles=no` suppresses
  # untracked *and* ignored output, the whole mechanism the check below needs.
  # --ignored, because `capability install` copies the directory, not the index:
  # an ignored file inside the bundle is unpublished bytes the mirror would
  # carry, and plain `status --porcelain` reports it clean (e.g. __pycache__/).
  # --ignore-submodules=none, because `submodule.<name>.ignore` is equally valid
  # in tracked .gitmodules, so a repository can ship the setting to every clone;
  # the gitlink keeps an H tag, so the index check above misses it (cases J6, J7).
  # -c core.fsmonitor=, because that hands "which paths changed" to an external
  # command, and one answering "none" makes `status` skip the stat entirely --
  # an edited tracked file reports clean with no index bit anywhere (case J8).
  #
  # What this still cannot see: a `.gitattributes` clean filter maps edited
  # worktree bytes onto the committed blob, so `status` is honestly clean while
  # the copy carries the edit. The filter driver lives in local config, which no
  # clone carries, so it stops at the machine that set it (gsd-beads-5yy).
  #
  # The exit status is read before the output: empty output from a `status` that
  # failed is indistinguishable from empty output from a clean tree (case J1).
  if ! DIRTY="$(git -c core.fsmonitor= -C "$BUNDLE_DIR" status --porcelain --ignored \
                    --untracked-files=all --ignore-submodules=none -- . 2>/dev/null)"; then
    echo "capability-auto-install: git could not report the state of the $CAP_ID bundle, so its contents cannot be verified; refusing to install it at global scope" >&2
    exit 0
  fi
  if [ -n "$DIRTY" ]; then
    echo "capability-auto-install: $CAP_ID bundle has uncommitted or ignored files; refusing to install it at global scope" >&2
    exit 0
  fi
  # What the two checks below prove, exactly: origin/HEAD and origin/main are
  # local refs under refs/remotes, so passing means HEAD is an ancestor of the
  # tip the last fetch recorded -- not that any server holds these bytes now.
  # Closing that gap needs a round trip to the remote on every SessionStart,
  # which would put the capability behind
  # the network and behind credentials; this guard exists for the accident of
  # running a plugin out of a development worktree, and against that accident a
  # local ref is the right evidence and the only affordable one. Case K1 pins
  # the limit so it stays a decision rather than an assumption.
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

# gsd_tools() resolver. Sourced after the guard above, not before, so nothing
# here can run before the decision to install. If it is missing, `gsd_tools`
# stays undefined and the exit-127 branch below reports it and writes no
# sidecar, so a repaired install retries (case L2).
[ -f "$PLUGIN_ROOT/hooks/gsd-tools.sh" ] && . "$PLUGIN_ROOT/hooks/gsd-tools.sh"

# Absolute spec: a relative one would resolve against the end user's
# cwd, not the plugin.
gsd_tools capability install "$BUNDLE_DIR" --scope global --yes >/dev/null 2>&1
INSTALL_STATUS=$?

# Both failure branches below break this repo's silent `|| true` convention and
# write no STATE_FILE: the path is unattended, so silence would leave a
# capability permanently inactive, and the next session must retry.
if [ "$INSTALL_STATUS" -eq 0 ]; then
  printf 'Auto-installed capability: %s (user scope)\n' "$CAP_ID"
  mkdir -p "$(dirname "$STATE_FILE")" 2>/dev/null
  printf '%s' "$NEW_HASH" > "$STATE_FILE" 2>/dev/null
elif [ "$INSTALL_STATUS" -eq 127 ]; then
  echo "capability-auto-install: gsd-tools not found; $CAP_ID not installed" >&2
else
  echo "capability-auto-install: capability install failed for $CAP_ID (exit $INSTALL_STATUS)" >&2
fi

exit 0
