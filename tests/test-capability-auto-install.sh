#!/usr/bin/env bash
# Stdlib-only coverage for hooks/capability-auto-install.sh (gsd-beads-dsa).
#
# The hook enforces one invariant: `capability install --scope global` publishes
# to every project on the machine, so it may only install bytes that are already
# published in the bundle's own upstream. This file enumerates the decision the
# hook makes rather than the handful of situations anyone happened to think of
# -- three defects (gsd-beads-70t, -iy2, -ju2) survived manual verification of
# "four cases" precisely because that was a sample, not a partition.
#
# The partition, in the order the hook evaluates it:
#
#   1. git unusable                          -> refuse   (cases H1, H2)
#   2. bundle not tracked by an enclosing repo
#      (no repo at all, or an unrelated one) -> install  (cases A, F, G)
#   3. tracked, uncommitted or ignored bytes -> refuse   (cases B, E)
#   4. tracked, clean, no upstream ref       -> refuse   (case C2)
#   5. tracked, clean, HEAD not upstream     -> refuse   (case C)
#   6. tracked, clean, HEAD published        -> install  (case D)
#
# Plus two properties that cut across it: a refusal must never write the hash
# sidecar (so a later session retries), and the sidecar must never serve a fast
# path for a mirror some other plugin root has since overwritten (cases I1, I2).
#
# Nothing here can perform a real global install: HOME and GSD_HOME are
# redirected into a per-case mktemp sandbox and gsd-tools is a stub that only
# appends to a log (gsd-beads-fma). Assertion I0 proves that redirect held.
set -u

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$REPO_ROOT/hooks/capability-auto-install.sh"
CAP_ID="sota-numerics"

fail() { echo "FAIL: $1"; exit 1; }
pass() { echo "PASS: $1"; }

REAL_GSD="${GSD_HOME:-$HOME}/.gsd"
real_gsd_state() {
  ls -d "$REAL_GSD/capabilities/$CAP_ID" \
        "$REAL_GSD/capability-auto-install-$CAP_ID.hash" 2>&1
}
REAL_GSD_BEFORE="$(real_gsd_state)"

SANDBOX_ROOT="$(mktemp -d)"
trap 'rm -rf "$SANDBOX_ROOT" 2>/dev/null' EXIT

# Commit without depending on the developer's git identity or signing config.
GIT_ID=(-c user.name=test -c user.email=test@example.invalid -c commit.gpgsign=false)

PATH_OVERRIDE=""

# new_sandbox <name> [plugin-root-subpath]
# Fresh sandbox with a redirected home, a stub gsd-tools, and a bundle.
new_sandbox() {
  SB="$SANDBOX_ROOT/$1"
  ROOT="$SB/${2:-root}"
  BUNDLE="$ROOT/.gsd/capabilities/$CAP_ID"
  PATH_OVERRIDE=""
  mkdir -p "$BUNDLE/scripts" "$SB/home" "$SB/bin"
  printf '{"id":"%s","version":"0.2.0"}\n' "$CAP_ID" > "$BUNDLE/capability.json"
  printf 'print("gate")\n' > "$BUNDLE/scripts/check.py"
  cat > "$SB/bin/gsd-tools" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GSD_TOOLS_LOG"
exit 0
STUB
  chmod +x "$SB/bin/gsd-tools"
  : > "$SB/installs"
}

# run_hook [cwd] [CLAUDE_PLUGIN_ROOT value]
# The two are separate because the host sets CLAUDE_PLUGIN_ROOT and the hook
# must not depend on it being absolute (case I3).
run_hook() {
  local _root="${1:-$ROOT}"
  ( cd "$_root" &&
    PATH="${PATH_OVERRIDE:-$SB/bin:$PATH}" \
    HOME="$SB/home" GSD_HOME="$SB/home" GSD_TOOLS_LOG="$SB/installs" \
    CLAUDE_PLUGIN_ROOT="${2:-$_root}" \
    bash "$HOOK" "$CAP_ID" ) >"$SB/out" 2>"$SB/err"
}

installs() { wc -l < "$SB/installs" | tr -d ' '; }
sidecar()  { echo "$SB/home/.gsd/capability-auto-install-$CAP_ID.hash"; }
err_has()  { grep -qF "$1" "$SB/err"; }

# git_init <dir> [pathspec...] -- repo committing <pathspec>, default everything
git_init() {
  local _dir="$1"; shift
  git -C "$_dir" init -q 2>/dev/null
  if [ $# -eq 0 ]; then git -C "$_dir" add -A; else git -C "$_dir" add -- "$@"; fi
  git "${GIT_ID[@]}" -C "$_dir" commit -qm "initial"
}

# publish <dir> -- give <dir> an origin whose main holds its current HEAD
publish() {
  git init -q --bare "$SB/origin"
  git -C "$1" remote add origin "$SB/origin"
  git -C "$1" push -q origin HEAD:refs/heads/main
  git -C "$1" fetch -q origin
}

# --- A: bundle inside no git repository (the real plugin-cache shape) ---
new_sandbox a
run_hook
[ "$(installs)" = 1 ] || fail "A: plugin-cache bundle did not install (err: $(cat "$SB/err"))"
grep -q -- "--scope global" "$SB/installs" || fail "A: install was not at global scope"
[ -f "$(sidecar)" ] || fail "A: successful install did not write the hash sidecar"
pass "A: bundle outside any git repo installs"

# --- B: tracked bundle with uncommitted changes ---
new_sandbox b
git_init "$ROOT"
publish "$ROOT"
printf 'work in progress\n' >> "$BUNDLE/scripts/check.py"
run_hook
[ "$(installs)" = 0 ] || fail "B: dirty bundle was installed"
err_has "uncommitted or ignored" || fail "B: no dirty refusal (err: $(cat "$SB/err"))"
[ ! -f "$(sidecar)" ] || fail "B: refusal wrote the sidecar, so a later session would not retry"
pass "B: tracked bundle with uncommitted changes refuses, leaves no sidecar"

# --- C: tracked, clean, HEAD ahead of the published upstream ---
new_sandbox c
git_init "$ROOT"
publish "$ROOT"
printf 'committed but unpushed\n' >> "$BUNDLE/scripts/check.py"
git -C "$ROOT" add -A
git "${GIT_ID[@]}" -C "$ROOT" commit -qm "unpublished"
run_hook
[ "$(installs)" = 0 ] || fail "C: unpublished HEAD was installed"
err_has "not published" || fail "C: no publication refusal (err: $(cat "$SB/err"))"
[ ! -f "$(sidecar)" ] || fail "C: refusal wrote the sidecar"
pass "C: tracked, clean, unpublished HEAD refuses"

# --- C2: tracked, clean, no upstream ref at all -> fail closed ---
new_sandbox c2
git_init "$ROOT"
run_hook
[ "$(installs)" = 0 ] || fail "C2: bundle with no upstream was installed"
err_has "no origin/HEAD or origin/main" || fail "C2: wrong refusal (err: $(cat "$SB/err"))"
pass "C2: no upstream ref fails closed"

# --- D: tracked, clean, published ---
new_sandbox d
git_init "$ROOT"
publish "$ROOT"
run_hook
[ "$(installs)" = 1 ] || fail "D: published bundle did not install (err: $(cat "$SB/err"))"
[ -f "$(sidecar)" ] || fail "D: successful install did not write the hash sidecar"
pass "D: tracked, clean, published bundle installs"

# --- E: published bundle carrying gitignored bytes (gsd-beads-ju2) ---
# `capability install` copies the directory, not the index, so these bytes would
# be mirrored machine-wide while `git status --porcelain` reports clean.
new_sandbox e
printf '__pycache__/\n*.pyc\n' > "$ROOT/.gitignore"
git_init "$ROOT"
publish "$ROOT"
mkdir -p "$BUNDLE/scripts/__pycache__"
printf 'unpublished bytecode\n' > "$BUNDLE/scripts/__pycache__/check.pyc"
[ -z "$(git -C "$BUNDLE" status --porcelain -- .)" ] ||
  fail "E: precondition -- plain porcelain should report this bundle clean"
run_hook
[ "$(installs)" = 0 ] || fail "E: bundle with gitignored bytes was installed"
err_has "uncommitted or ignored" || fail "E: no refusal for ignored bytes (err: $(cat "$SB/err"))"
pass "E: gitignored bytes inside a clean published bundle refuse"

# --- F: bundle merely enclosed by an unrelated repo, untracked (gsd-beads-70t) ---
# The ~/.claude-in-git consumer. Enclosure is not ownership; that repo has
# nothing to say about these bytes, so the guard must not apply at all.
new_sandbox f "dotfiles/plugins/cache/$CAP_ID/0.2.0"
printf 'export EDITOR=vi\n' > "$SB/dotfiles/rc"
git_init "$SB/dotfiles" rc   # commits the dotfiles only; the bundle stays untracked
[ -n "$(git -C "$BUNDLE" status --porcelain -- .)" ] ||
  fail "F: precondition -- the bundle should look untracked to the enclosing repo"
run_hook
[ "$(installs)" = 1 ] || fail "F: bundle in an unrelated repo did not install (err: $(cat "$SB/err"))"
err_has "uncommitted" && fail "F: reported the bundle as uncommitted in a repo that does not track it"
pass "F: untracked bundle inside an unrelated repo installs"

# --- F2: a repo that *does* track the bundle stays guarded, whatever its name ---
# The residual case ownership cannot separate from development: a monorepo that
# vendors this plugin. Refusing is the direction an unverifiable case must err
# in, and pinning it here keeps that a decision rather than an accident.
new_sandbox f2 "mono/packages/$CAP_ID"
printf 'monorepo\n' > "$SB/mono/README"
git_init "$SB/mono"
run_hook
[ "$(installs)" = 0 ] || fail "F2: a repo tracking the bundle skipped the guard"
err_has "no origin/HEAD or origin/main" || fail "F2: wrong refusal (err: $(cat "$SB/err"))"
pass "F2: bundle tracked by an enclosing monorepo stays guarded"

# --- G: same, but the unrelated repo gitignores the plugin path and has no origin ---
new_sandbox g "dotfiles/plugins/cache/$CAP_ID/0.2.0"
printf 'plugins/\n' > "$SB/dotfiles/.gitignore"
git_init "$SB/dotfiles"
run_hook
[ "$(installs)" = 1 ] || fail "G: gitignored bundle in an unrelated repo did not install (err: $(cat "$SB/err"))"
err_has "no origin/HEAD or origin/main" &&
  fail "G: gated the capability on an unrelated repository's publication state"
pass "G: gitignored bundle inside an unrelated origin-less repo installs"

# --- H1: git on PATH but non-functional, bundle both dirty and unpublished ---
new_sandbox h1
git_init "$ROOT"
printf 'work in progress\n' >> "$BUNDLE/scripts/check.py"
cat > "$SB/bin/git" <<'BROKEN'
#!/usr/bin/env bash
exit 127
BROKEN
chmod +x "$SB/bin/git"
run_hook
[ "$(installs)" = 0 ] || fail "H1: broken git let a dirty, unpublished bundle install"
err_has "git is unusable" || fail "H1: wrong refusal (err: $(cat "$SB/err"))"
pass "H1: non-functional git fails closed"

# --- H2: git absent from PATH entirely ---
new_sandbox h2
git_init "$ROOT"
mkdir -p "$SB/nogit"
for _t in bash find sort awk sha256sum shasum cat mkdir dirname wc; do
  _p="$(command -v "$_t" 2>/dev/null)" && ln -sf "$_p" "$SB/nogit/$_t"
done
ln -sf "$SB/bin/gsd-tools" "$SB/nogit/gsd-tools"
PATH_OVERRIDE="$SB/nogit"
run_hook
[ "$(installs)" = 0 ] || fail "H2: missing git let an unpublished bundle install"
err_has "git is unusable" || fail "H2: wrong refusal (err: $(cat "$SB/err"))"
pass "H2: absent git fails closed"

# --- I1: unchanged bundle takes the fast path on the next session ---
new_sandbox i1
run_hook
run_hook
[ "$(installs)" = 1 ] || fail "I1: unchanged bundle reinstalled ($(installs) installs in 2 runs)"
pass "I1: unchanged bundle takes the hash fast path"

# --- I2: a second plugin root serving the same id reinstalls (gsd-beads-9ap) ---
# One capability id owns one global mirror and therefore one sidecar. The two
# roots hold byte-identical bundles, so only the absolute paths in the hash stop
# root B from taking a fast path over a mirror that still holds root A's bytes.
new_sandbox i2
ROOT_B="$SB/root-b"
mkdir -p "$(dirname "$ROOT_B")"
cp -r "$ROOT" "$ROOT_B"
run_hook "$ROOT"
run_hook "$ROOT_B"
run_hook "$ROOT"
[ "$(installs)" = 3 ] ||
  fail "I2: alternating plugin roots took a false fast path ($(installs) installs in 3 runs)"
pass "I2: a different plugin root for the same id reinstalls the mirror"

# --- I3: I2 must hold for a relative CLAUDE_PLUGIN_ROOT too ---
# I2's property is that the absolute paths inside NEW_HASH separate two roots
# serving one id. That is only true if BUNDLE_DIR is absolute. The host supplies
# CLAUDE_PLUGIN_ROOT and nothing in the protocol says it is absolute, so pin the
# relative case rather than inheriting it.
new_sandbox i3
ROOT_B="$SB/root-b"
mkdir -p "$(dirname "$ROOT_B")"
cp -r "$ROOT" "$ROOT_B"
run_hook "$ROOT" .
run_hook "$ROOT_B" .
run_hook "$ROOT" .
[ "$(installs)" = 3 ] ||
  fail "I3: a relative CLAUDE_PLUGIN_ROOT made the hash root-independent ($(installs) installs in 3 runs)"
pass "I3: a relative CLAUDE_PLUGIN_ROOT still separates two roots"

# --- I4: a symlink added or retargeted inside the bundle is drift ---
# `capability install` copies the directory, so a symlink is bytes the mirror
# will carry. If it does not reach the hash, the fast path at the top of the
# hook skips the publication guard and the install itself, and the mirror keeps
# serving a link whose target has since moved.
new_sandbox i4
run_hook
[ "$(installs)" = 1 ] || fail "I4: precondition -- first run should install"
ln -s ../capability.json "$BUNDLE/scripts/link"
run_hook
[ "$(installs)" = 2 ] || fail "I4: an added symlink did not change the bundle hash"
ln -sfn ../scripts/check.py "$BUNDLE/scripts/link"
run_hook
[ "$(installs)" = 3 ] || fail "I4: a retargeted symlink did not change the bundle hash"
pass "I4: symlink drift inside the bundle defeats the fast path"

# --- I0: no case above touched the developer's real global GSD state ---
[ "$(real_gsd_state)" = "$REAL_GSD_BEFORE" ] ||
  fail "I0: suite changed the real $REAL_GSD -- HOME/GSD_HOME redirect leaked"
pass "I0: real GSD_HOME untouched by the suite"

echo "ALL PASS"
exit 0
