#!/usr/bin/env bash
# Stdlib-only coverage for hooks/capability-auto-install.sh.
#
# The hook enforces one invariant: `capability install --scope global` publishes
# to every project on the machine, so it may only install bytes it can still see
# in the bundle's own upstream -- concretely, in the last upstream tip this
# checkout fetched, which is as far as a hook that must not touch the network
# can see (case K1). This file enumerates the decision the
# hook makes rather than the handful of situations anyone happened to think of
# -- three defects survived manual verification of
# "four cases" precisely because that was a sample, not a partition.
#
# The partition, in the order the hook evaluates it. It is a partition and not
# a list because it branches on `git ls-files --error-unmatch`, whose three
# exit codes are exhaustive by construction -- 0, 1, and everything else -- and
# because each of those three is then split on conditions that are themselves
# complementary. An earlier version of this header stopped at six rows by
# reading every non-zero exit code as "untracked", and rows 10 and 11 are the
# two halves of what that concealed. A later one stopped at nine by trusting
# `status`'s answer without asking whether it had answered at all; rows 2 and 3
# are what that concealed.
#
#   1. git binary unusable                    -> refuse   (cases H1, H2)
#
#   ls-files 0 -- a repository tracks the bundle:
#   2. index told not to check some entries   -> refuse   (cases J2, J3)
#   3. `status` could not answer at all       -> refuse   (case J1)
#   4. uncommitted or ignored bytes           -> refuse   (cases B, E, J4)
#   5. clean, no origin/HEAD or origin/main   -> refuse   (cases C2, F2)
#   6. clean, HEAD not an ancestor of it      -> refuse   (case C)
#   7. clean, HEAD an ancestor of that ref    -> install  (cases D, A2, K1)
#
#   ls-files 1 -- a repository answered and does not track the bundle:
#   8. it has nothing to say about the bytes  -> install  (cases F, G)
#
#   ls-files 128 -- git did not answer, which is not the same as "no":
#   9. no repository on disk                  -> install  (cases A, A3)
#  10. a repository git will not open         -> refuse   (cases H3, H5)
#  11. a repository whose index it cannot read-> refuse   (case H4)
#
# Rows 2 to 7 are complementary because they qualify `status`'s answer before
# reading it: first whether the index has been told to hide entries from it,
# then whether it exited non-zero, then whether it printed anything, then the
# only remaining state. Rows 10 and 11 are separate because they need different
# evidence: in row 11 git has already opened the repository, so
# `rev-parse --git-dir` sees it, while in row 10 discovery itself fails and only
# the filesystem can answer.
#
# The partition is reached at all only if the bundle can be read: the walk that
# produces the hash runs first, and a walk that could not finish describes no
# bundle (case J5).
#
# Plus properties that cut across the partition: a refusal must never write the
# hash sidecar (so a later session retries), and the sidecar must never serve a
# fast path over a mirror that no longer matches the bundle -- whether another
# plugin root overwrote it (I1, I2), the host passed a relative plugin root
# (I3), or the drift is a symlink rather than a file (I4).
#
# Nothing here can perform a real global install. Three things hold that up and
# each is enforced rather than asserted: HOME and GSD_HOME are redirected into a
# per-case mktemp sandbox; GIT_CEILING_DIRECTORIES stops every git command the
# hook runs from discovering a repository above that sandbox, which is what
# keeps the hook's first gsd-tools rung (`git rev-parse --show-toplevel`, then
# $toplevel/gsd-core/bin/gsd-tools.cjs) from reaching a real binary when TMPDIR
# happens to sit inside a checkout; and the PATH stub then answers instead. The
# precondition below refuses to run at all if the sandbox is inside a
# repository, because the cases would then be exercising a different partition
# row than the one they name. Assertion I0 compares the real mirror's contents
# and its sidecar's contents, not their existence: a real install overwrites
# both in place, which leaves any check of "are these two paths still there"
# passing.
set -u

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$REPO_ROOT/hooks/capability-auto-install.sh"
CAP_ID="sota-numerics"

# Record and continue rather than exit: one broken case otherwise masks every
# case after it, and a partition is only useful if a run reports which of its
# rows are red. Continuing also reaches the chmod that each unreadable-repo case
# undoes, without which the sandbox cannot be removed on the way out.
FAILURES=0
fail() { echo "FAIL: $1"; FAILURES=$((FAILURES + 1)); }
pass() { echo "PASS: $1"; }

if command -v sha256sum >/dev/null 2>&1; then HASH_CMD=(sha256sum)
elif command -v shasum >/dev/null 2>&1; then HASH_CMD=(shasum -a 256)
else echo "FAIL: no sha256 tool, so I0 could not tell whether the real mirror changed"; exit 1
fi

REAL_GSD="${GSD_HOME:-$HOME}/.gsd"
# Contents, not existence. The failure this guards against -- the hook
# installing an uncommitted bundle over the developer's own global mirror -- has
# happened on this project, and it adds and removes no path: it overwrites the
# mirror's files and rewrites the sidecar. The digest is the one 23-01-PLAN.md
# quotes for this directory, so a mismatch can be read against that recorded
# value rather than only against this run's own baseline.
real_gsd_state() {
  ( cd "$REAL_GSD/capabilities/$CAP_ID" 2>/dev/null &&
    find . -name __pycache__ -prune -o -type f -print |
      LC_ALL=C sort | xargs "${HASH_CMD[@]}" | "${HASH_CMD[@]}"
  ) 2>&1
  cat "$REAL_GSD/capability-auto-install-$CAP_ID.hash" 2>&1
}
REAL_GSD_BEFORE="$(real_gsd_state)"

SANDBOX_ROOT="$(mktemp -d)"
trap 'rm -rf "$SANDBOX_ROOT" 2>/dev/null' EXIT

# TMPDIR decides where the sandbox lands, and a sandbox inside a checkout is not
# a sandbox: the hook's git commands would discover that repository, which both
# moves cases into partition rows they do not name and points gsd-tools
# resolution at whatever gsd-core that checkout ships.
if OUTER="$(git -C "$SANDBOX_ROOT" rev-parse --show-toplevel 2>/dev/null)"; then
  echo "FAIL: sandbox $SANDBOX_ROOT lies inside the repository $OUTER; point TMPDIR at a directory outside any checkout"
  exit 1
fi

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
    GIT_CEILING_DIRECTORIES="$SANDBOX_ROOT" \
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
# symbolic-ref because init.defaultBranch is the developer's, not ours: a bare
# origin whose HEAD names a branch nobody pushed cannot be cloned (case A2).
publish() {
  git init -q --bare "$SB/origin"
  git -C "$SB/origin" symbolic-ref HEAD refs/heads/main
  git -C "$1" remote add origin "$SB/origin"
  git -C "$1" push -q origin HEAD:refs/heads/main
  git -C "$1" fetch -q origin
}

# --- A: bundle with no repository anywhere above it ---
# Not the marketplace shape -- that is a git clone, see A2. This is the
# unpacked-tarball case: nothing on disk has anything to say about these bytes.
new_sandbox a
run_hook
[ "$(installs)" = 1 ] || fail "A: bundle under no repository did not install (err: $(cat "$SB/err"))"
grep -q -- "--scope global" "$SB/installs" || fail "A: install was not at global scope"
[ -f "$(sidecar)" ] || fail "A: successful install did not write the hash sidecar"
pass "A: bundle outside any git repo installs"

# --- A2: the real marketplace shape -- a depth-1 clone of the plugin repo ---
# `source: url` in a marketplace entry installs by cloning, so the plugin cache
# IS a repository and it DOES track the bundle. The guard therefore runs on
# every consumer machine, not only in development. Pin that it passes there.
# This is also the only case where origin/HEAD resolves, so it is what keeps the
# first arm of the hook's `origin/HEAD || origin/main` from being dead in test.
new_sandbox a2
git_init "$ROOT"
publish "$ROOT"
printf 'print("gate v2")\n' > "$BUNDLE/scripts/check.py"   # history above the tip
git -C "$ROOT" add -A
git "${GIT_ID[@]}" -C "$ROOT" commit -qm "release"
git -C "$ROOT" push -q origin HEAD:refs/heads/main
git clone -q --depth 1 "file://$SB/origin" "$SB/cache"
CACHE_BUNDLE="$SB/cache/.gsd/capabilities/$CAP_ID"
[ -f "$SB/cache/.git/shallow" ] &&
  [ "$(git -C "$SB/cache" rev-list --count HEAD)" = 1 ] ||
  fail "A2: precondition -- clone should be shallow with a single commit"
git -C "$CACHE_BUNDLE" ls-files --error-unmatch . >/dev/null 2>&1 ||
  fail "A2: precondition -- the cached bundle should be tracked by the clone"
git -C "$CACHE_BUNDLE" rev-parse --verify --quiet origin/HEAD >/dev/null ||
  fail "A2: precondition -- a clone should resolve origin/HEAD"
run_hook "$SB/cache"
[ "$(installs)" = 1 ] || fail "A2: marketplace clone did not install (err: $(cat "$SB/err"))"
[ -f "$(sidecar)" ] || fail "A2: successful install did not write the hash sidecar"
pass "A2: marketplace depth-1 clone is guarded and passes the guard"

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

# --- K1: publication is proved against a local ref, never against the remote ---
# The limit of row 7, written where it can be executed rather than trusted.
# origin/main is a ref under refs/remotes that some earlier fetch wrote, so the
# ancestry test says HEAD is contained in the last tip this checkout recorded --
# it does not say a server holds those bytes now. Deleting the origin repository
# outright leaves the answer unchanged. That is deliberate: a SessionStart hook
# that reached the network would put the capability behind connectivity and
# credentials. It is also why the prose may not say the bundle is published,
# only that it matches the last upstream tip fetched.
new_sandbox k1
git_init "$ROOT"
publish "$ROOT"
rm -rf "$SB/origin"
git -C "$BUNDLE" ls-remote origin >/dev/null 2>&1 &&
  fail "K1: precondition -- the origin repository should be unreachable"
run_hook
[ "$(installs)" = 1 ] ||
  fail "K1: the guard contacted the remote, or refused without one (err: $(cat "$SB/err"))"
pass "K1: ancestry is proved against the last fetched ref, offline"

# --- E: published bundle carrying gitignored bytes ---
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

# --- F: bundle merely enclosed by an unrelated repo, untracked ---
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

# --- H3: git runs, but will not open the repository that tracks the bundle ---
# `ls-files --error-unmatch` answers 128 both for "no repository" and for "a
# repository I refuse to read", and the second must not be read as the first.
# chmod 000 stands in for the field cases: another UID's checkout git rejects
# for dubious ownership (a root- or service-installed plugin, a shared checkout,
# a container UID remap) and a partially readable .git. The bundle here is both
# dirty and unpublished, so reading 128 as "untracked" installs bytes that two
# separate refusals exist to stop.
new_sandbox h3
git_init "$ROOT"
printf 'work in progress\n' >> "$BUNDLE/scripts/check.py"
chmod 000 "$ROOT/.git"
run_hook
chmod 755 "$ROOT/.git"
[ "$(installs)" = 0 ] || fail "H3: an unreadable repository let a dirty, unpublished bundle install"
err_has "git cannot read the repository" || fail "H3: wrong refusal (err: $(cat "$SB/err"))"
[ ! -f "$(sidecar)" ] || fail "H3: refusal wrote the sidecar, making the miss permanent"
pass "H3: a repository git refuses to open fails closed"

# --- H4: git opens the repository but cannot read its index ---
# Distinct from H3 and not reachable by testing `rev-parse --show-toplevel`:
# discovery succeeds here, so a --show-toplevel gate routes this case into the
# tracked branch, where ls-files then fails and every refusal is skipped. Only
# discriminating ls-files' own exit codes closes it. Precondition asserted
# below so the distinction cannot be refactored away by accident.
new_sandbox h4
git_init "$ROOT"
printf 'work in progress\n' >> "$BUNDLE/scripts/check.py"
chmod 000 "$ROOT/.git/index"
git -C "$BUNDLE" rev-parse --show-toplevel >/dev/null 2>&1 ||
  fail "H4: precondition -- git should still discover this repository"
git -C "$BUNDLE" ls-files --error-unmatch . >/dev/null 2>&1 &&
  fail "H4: precondition -- ls-files should fail on an unreadable index"
run_hook
chmod 644 "$ROOT/.git/index"
[ "$(installs)" = 0 ] || fail "H4: an unreadable index let a dirty, unpublished bundle install"
err_has "git cannot read the repository" || fail "H4: wrong refusal (err: $(cat "$SB/err"))"
[ ! -f "$(sidecar)" ] || fail "H4: refusal wrote the sidecar, making the miss permanent"
pass "H4: a repository whose index git cannot read fails closed"

# --- H5: a readable .git that git still refuses to open ---
# The dubious-ownership shape -- .git is perfectly readable, git just declines
# -- which cannot be built here without a second uid. An unknown repository
# format reaches the guard through the same branch: discovery fails, yet an
# ancestor .git holds a HEAD, so a repository is there and git did not answer.
new_sandbox h5
git_init "$ROOT"
printf 'work in progress\n' >> "$BUNDLE/scripts/check.py"
git -C "$ROOT" config core.repositoryformatversion 99
[ -r "$ROOT/.git/HEAD" ] || fail "H5: precondition -- .git should stay readable"
run_hook
[ "$(installs)" = 0 ] || fail "H5: a repository git declined let a dirty, unpublished bundle install"
err_has "git cannot read the repository" || fail "H5: wrong refusal (err: $(cat "$SB/err"))"
pass "H5: a readable repository git declines fails closed"

# --- A3: a .git that is not a repository must not block the install ---
# The other side of H3/H5. Refusing on the mere existence of a name is a false
# positive that disables the capability: a stray empty /tmp/.git would then
# refuse every bundle unpacked under /tmp, this suite included. The evidence
# that separates them is a HEAD, not a name.
new_sandbox a3
mkdir -p "$SB/.git"
run_hook
[ "$(installs)" = 1 ] || fail "A3: an empty .git above the bundle blocked the install (err: $(cat "$SB/err"))"
pass "A3: a .git holding no repository is walked past"

# --- J1: git tracks the bundle but cannot report its state ---
# The third state hiding between rows 2 and 3-5: `status` printing nothing
# because it failed is not `status` printing nothing because the tree is clean.
# A missing HEAD tree object produces exactly that -- ls-files still answers 0
# from the index alone, and merge-base still proves HEAD published from the
# commit objects alone, so every other check says "safe" while the one check
# that reads the worktree never ran. The bundle here carries uncommitted bytes
# that only `status` could have revealed.
new_sandbox j1
git_init "$ROOT"
publish "$ROOT"
printf 'work in progress\n' >> "$BUNDLE/scripts/check.py"
TREE="$(git -C "$ROOT" rev-parse 'HEAD^{tree}')"
rm -f "$ROOT/.git/objects/${TREE:0:2}/${TREE:2}"
git -C "$BUNDLE" ls-files --error-unmatch . >/dev/null 2>&1 ||
  fail "J1: precondition -- the bundle should still read as tracked"
git -C "$BUNDLE" status --porcelain --ignored -- . >/dev/null 2>&1 &&
  fail "J1: precondition -- status should fail on a missing HEAD tree"
[ -z "$(git -C "$BUNDLE" status --porcelain --ignored -- . 2>/dev/null)" ] ||
  fail "J1: precondition -- the failed status should print nothing, which is what makes it look clean"
git -C "$BUNDLE" merge-base --is-ancestor HEAD origin/main 2>/dev/null ||
  fail "J1: precondition -- HEAD should still prove published"
run_hook
[ "$(installs)" = 0 ] || fail "J1: a bundle whose state git could not report was installed"
err_has "could not report the state" || fail "J1: wrong refusal (err: $(cat "$SB/err"))"
[ ! -f "$(sidecar)" ] || fail "J1: refusal wrote the sidecar, making the miss permanent"
pass "J1: a status git could not answer is not an answer of clean"

# --- J2: an index entry marked assume-unchanged ---
# `status` answers from the index, and the index can be told to stop looking.
# `update-index --assume-unchanged` is the flag a developer sets on a file they
# are hand-editing locally, so this is an ordinary local tweak rather than an
# exotic attack, and the bundle's bytes on disk then differ from anything ever
# published while every git question above still answers "clean, published".
# `diff --quiet HEAD` does not close this: it honours the same bit.
new_sandbox j2
git_init "$ROOT"
publish "$ROOT"
git -C "$ROOT" update-index --assume-unchanged .gsd/capabilities/$CAP_ID/scripts/check.py
printf 'UNPUBLISHED\n' >> "$BUNDLE/scripts/check.py"
[ -z "$(git -C "$BUNDLE" status --porcelain --ignored -- . 2>/dev/null)" ] ||
  fail "J2: precondition -- status should report this edited bundle as clean"
git -C "$BUNDLE" diff --quiet HEAD -- . 2>/dev/null ||
  fail "J2: precondition -- diff HEAD should also miss it, so it cannot be the fix"
run_hook
[ "$(installs)" = 0 ] || fail "J2: an assume-unchanged bundle edit was installed"
err_has "will not report edits" || fail "J2: wrong refusal (err: $(cat "$SB/err"))"
[ ! -f "$(sidecar)" ] || fail "J2: refusal wrote the sidecar, making the miss permanent"
pass "J2: assume-unchanged entries refuse"

# --- J3: an index entry marked skip-worktree ---
# The same hole through the other bit, and not reachable by J2's test: with -v
# assume-unchanged lowercases the tag while skip-worktree keeps an upper-case
# S, so a check written for lower-case letters alone passes this case.
new_sandbox j3
git_init "$ROOT"
publish "$ROOT"
git -C "$ROOT" update-index --skip-worktree .gsd/capabilities/$CAP_ID/scripts/check.py
printf 'UNPUBLISHED\n' >> "$BUNDLE/scripts/check.py"
[ -z "$(git -C "$BUNDLE" status --porcelain --ignored -- . 2>/dev/null)" ] ||
  fail "J3: precondition -- status should report this edited bundle as clean"
[ "$(git -C "$BUNDLE" ls-files -v -- . | cut -c1 | sort -u | tr -d '\n')" = "HS" ] ||
  fail "J3: precondition -- skip-worktree should tag S, not a lower-case letter"
run_hook
[ "$(installs)" = 0 ] || fail "J3: a skip-worktree bundle edit was installed"
err_has "will not report edits" || fail "J3: wrong refusal (err: $(cat "$SB/err"))"
pass "J3: skip-worktree entries refuse"

# --- J4: status configured not to mention untracked or ignored files ---
# Third way to make `status` answer "clean" about bytes that are there.
# `status.showUntrackedFiles=no` is a speed setting on large repositories, and
# it suppresses the --ignored output too -- which is the whole mechanism case E
# depends on. The command line has to override the config rather than trust it.
new_sandbox j4
git_init "$ROOT"
publish "$ROOT"
printf 'UNPUBLISHED\n' > "$BUNDLE/scripts/extra.py"
git -C "$ROOT" config status.showUntrackedFiles no
[ -z "$(git -C "$BUNDLE" status --porcelain --ignored -- . 2>/dev/null)" ] ||
  fail "J4: precondition -- the configured status should report this bundle clean"
run_hook
[ "$(installs)" = 0 ] || fail "J4: an untracked file hidden by status config was installed"
err_has "uncommitted or ignored" || fail "J4: wrong refusal (err: $(cat "$SB/err"))"
pass "J4: status configured to hide untracked bytes does not hide them from the guard"

# --- J5: part of the bundle cannot be read at all ---
# Nothing above can see this: an unreadable directory holds no tracked entry, so
# `ls-files` has nothing to say about it, and `status` -- even with
# --untracked-files=all -- exits 0 and prints nothing about a directory it could
# not open. Only `find` knows, by failing. Unread bytes are not published bytes,
# and the hash computed from the truncated listing would have been written to
# the sidecar as if it described the whole bundle.
new_sandbox j5
mkdir -p "$BUNDLE/private"
printf 'UNPUBLISHED\n' > "$BUNDLE/private/secret"
chmod 000 "$BUNDLE/private"
[ -z "$(git -C "$BUNDLE" status --porcelain --ignored --untracked-files=all -- . 2>/dev/null)" ] ||
  fail "J5: precondition -- git should have nothing to say about this bundle"
run_hook
chmod 755 "$BUNDLE/private"
[ "$(installs)" = 0 ] || fail "J5: a bundle that could not be read in full was installed"
err_has "could not be read in full" || fail "J5: wrong refusal (err: $(cat "$SB/err"))"
[ ! -f "$(sidecar)" ] || fail "J5: refusal wrote a sidecar holding a truncated bundle's hash"
grep -q "Permission denied" "$SB/err" &&
  fail "J5: find's own error reached the user's stderr instead of a refusal"
pass "J5: a bundle that cannot be read in full refuses"

# --- I1: unchanged bundle takes the fast path on the next session ---
new_sandbox i1
run_hook
run_hook
[ "$(installs)" = 1 ] || fail "I1: unchanged bundle reinstalled ($(installs) installs in 2 runs)"
pass "I1: unchanged bundle takes the hash fast path"

# --- I2: a second plugin root serving the same id reinstalls ---
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

# --- D0: every refusal the hook can emit is documented, and nothing else is ---
# The refusal list went stale three times in one session: the hook grew from
# five refusals to eight while README and CHANGELOG were being written against
# it, and one doc commit shipped "seven" against a hook emitting eight. Each
# drift was caught only because a human re-measured. Assert the set equality
# instead, so adding a refusal without documenting it fails here.
#
# Compared on the message PREFIX, up to "; refusing to install it at global
# scope" -- that tail is identical across all eight and the docs deliberately
# omit it. $CAP_ID is substituted because the docs name the capability.
REPO_ROOT_D0="$(cd "$(dirname "$0")/.." && pwd)"
doc_parity="$(python3 - "$REPO_ROOT_D0" <<'PYEOF'
import re, sys, pathlib
root = pathlib.Path(sys.argv[1])
hook = (root / "hooks" / "capability-auto-install.sh").read_text()
readme = (root / "README.md").read_text()
changelog = (root / "CHANGELOG.md").read_text()
emitted = [m for m in re.findall(r'echo "capability-auto-install: ([^"]+)" >&2', hook)
           if "refusing to install" in m]
def key(m):
    body = m.split("; refusing to install")[0]
    body = body.replace("$CAP_ID", "sota-numerics").replace("${CAP_ID}", "sota-numerics")
    return re.sub(r"\s*\$\{?\w+\}?\s*\)?$", "", body).strip()
missing = [key(m) for m in emitted if key(m) not in readme or key(m) not in changelog]
print(len(emitted), len(missing), "|".join(missing))
PYEOF
)"
set -- $doc_parity
D0_TOTAL="$1"; D0_MISSING="$2"
[ "$D0_TOTAL" -ge 8 ] || fail "D0: found only $D0_TOTAL refusals in the hook; the extractor regex has drifted"
[ "$D0_MISSING" -eq 0 ] || fail "D0: $D0_MISSING refusal(s) undocumented in README.md or CHANGELOG.md: ${doc_parity#* * }"
pass "D0: all $D0_TOTAL refusals documented verbatim in README.md and CHANGELOG.md"

# --- I0: no case above touched the developer's real global GSD state ---
[ "$(real_gsd_state)" = "$REAL_GSD_BEFORE" ] ||
  fail "I0: suite changed the real $REAL_GSD -- HOME/GSD_HOME redirect leaked"
pass "I0: real GSD_HOME untouched by the suite"

[ "$FAILURES" -eq 0 ] || { echo "$FAILURES FAILED"; exit 1; }
echo "ALL PASS"
exit 0
