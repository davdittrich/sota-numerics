#!/usr/bin/env bash
# Stdlib-only coverage for hooks/capability-auto-install.sh.
#
# The hook enforces one invariant: `capability install --scope global` publishes
# to every project on the machine, so it may only install bytes it can still see
# in the bundle's own upstream -- concretely, in the last upstream tip this
# checkout fetched, which is as far as a hook that must not touch the network
# can see (case K1). This file enumerates the decision the hook makes, as a
# partition rather than a sample.
#
# The rows below, in the order the hook evaluates them, are exhaustive over the
# hook's OWN control flow and nothing more. They branch on
# `git ls-files --error-unmatch`, whose three exit codes are exhaustive by
# construction -- 0, 1, and everything else -- and each of those three is then
# split on conditions that are complementary, so every execution of the hook
# lands in exactly one row. That claim is provable by reading the script, and it
# is the only exhaustiveness claim this file makes.
#
# It is NOT a claim that row 4 catches every way the bundle can hold unpublished
# bytes. Row 4 asks git a question, and what git answers is configurable; the
# four settings that redirect it are named on the hook's `status` invocation and
# pinned in the rows below.
#
# One known way remains, and it is recorded rather than claimed away: a
# `.gitattributes` clean filter maps edited worktree bytes onto the committed
# blob, so `status` is honestly clean about the index while the directory copy
# carries the edit. No `status` option reaches that; a byte comparison against
# the published tree would. The filter driver lives in local config, which no
# clone carries, so unlike J7 it cannot follow the bundle to a consumer.
# Tracked as gsd-beads-5yy. The honest predicate for row 4 is therefore "git,
# asked without inheriting the repository's configuration, reports the worktree
# clean" -- not "the bundle's bytes are the published bytes", which is stronger
# than what this hook measures.
#
#   1. git binary unusable                    -> refuse   (cases H1, H2)
#
#   ls-files 0 -- a repository tracks the bundle:
#   2. index told not to check some entries   -> refuse   (cases J2, J3)
#   3. `status` could not answer at all       -> refuse   (case J1)
#   4. uncommitted or ignored bytes           -> refuse   (cases B, E, J4, J6,
#                                                          J7, J8)
#   5. clean, no origin/HEAD or origin/main   -> refuse   (cases C2, F2)
#   6. clean, HEAD not an ancestor of it      -> refuse   (case C)
#   7. clean, HEAD an ancestor of that ref    -> install  (cases D, A2, K1)
#
#   ls-files 1 -- a repository answered and does not track the bundle:
#   8. it has nothing to say about the bytes  -> install  (case F)
#
#   ls-files 128 -- git did not answer, which is not the same as "no":
#   9. no repository on disk                  -> install  (cases A, A3)
#  10. a repository git will not open         -> refuse   (cases H3, H5)
#  11. a repository whose index it cannot read-> refuse   (case H4)
#
# Rows 2 to 7 are complementary because they qualify `status`'s answer before
# reading it: first whether the index has been told to hide entries from it,
# then whether it exited non-zero, then whether it printed anything, then the
# only remaining state. That ordering is why the settings in J4, J6, J7 and J8
# all land in row 4 rather than in rows of their own: none of them changes which
# branch runs, only what `status` reports inside it, so each is a case that must
# make row 4 fire rather than a twelfth row. Rows 10 and 11 are separate because
# they need different evidence: in row 11 git has already opened the repository, so
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
# plugin root overwrote it (I1, I3), or the drift is a symlink rather than a
# file (I4).
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

# I0 runs from the EXIT trap rather than from the foot of this file. It is the
# assertion that the suite did not overwrite the developer's real global mirror
# -- the incident the hook under test exists to prevent -- and an assertion that
# only runs when everything above it succeeded is not a containment check. Any
# exit reaches it: an early precondition, a `set -u` abort on an unbound
# variable (which is exactly how a missing python3 used to skip it), or an
# `exit` some future case adds mid-file. It also decides the suite's status, so
# a leak is red even if every case passed.
SANDBOX_ROOT="$(mktemp -d)"
check_containment() {
  if [ "$(real_gsd_state)" = "$REAL_GSD_BEFORE" ]; then
    pass "I0: real GSD_HOME untouched by the suite"
    exit "$1"
  fi
  echo "FAIL: I0: suite changed the real $REAL_GSD -- HOME/GSD_HOME redirect leaked"
  exit 1
}
trap '_rc=$?; rm -rf "$SANDBOX_ROOT" 2>/dev/null; check_containment "$_rc"' EXIT

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
  mkdir -p "$BUNDLE/scripts" "$SB/home" "$SB/bin" "$ROOT/hooks"
  # A plugin root ships hooks/gsd-tools.sh next to the hook, and the hook
  # sources it for the gsd_tools resolver. A sandbox root without it is a shape
  # that cannot occur in an installed plugin, so every root gets it; case L2
  # removes it on purpose to pin what happens when it is missing.
  cp "$REPO_ROOT/hooks/gsd-tools.sh" "$ROOT/hooks/gsd-tools.sh"
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
  # advice.addEmbeddedRepo off: J6/J7 add a gitlink on purpose, and the hint git
  # prints for it is nine lines of CI noise about a case under test.
  if [ $# -eq 0 ]; then git -c advice.addEmbeddedRepo=false -C "$_dir" add -A
  else git -C "$_dir" add -- "$@"; fi
  git "${GIT_ID[@]}" -C "$_dir" commit -qm "initial"
}

# vendor_submodule -- put a gitlink inside the bundle, plus a .gitmodules entry
# naming it. Written by hand rather than by `git submodule add`, which needs
# protocol.file.allow for a file:// source; the gitlink and the .gitmodules
# section are all `status` consults to decide whether a submodule.<name>.ignore
# setting applies, so the hand-built shape is the shape under test. Call before
# git_init. $1 is extra .gitmodules body, so a caller can commit `ignore = all`.
vendor_submodule() {
  mkdir -p "$BUNDLE/vendor"
  printf 'v1\n' > "$BUNDLE/vendor/lib.py"
  git -C "$BUNDLE/vendor" init -q
  git -C "$BUNDLE/vendor" add -A
  git "${GIT_ID[@]}" -C "$BUNDLE/vendor" commit -qm "vendor"
  SUBMODULE_NAME=".gsd/capabilities/$CAP_ID/vendor"
  {
    printf '[submodule "%s"]\n\tpath = %s\n\turl = ./vendor\n' "$SUBMODULE_NAME" "$SUBMODULE_NAME"
    [ $# -gt 0 ] && printf '\t%s\n' "$1"
  } > "$ROOT/.gitmodules"
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
err_has "no origin/HEAD or origin/main" &&
  fail "F: gated the capability on an unrelated repository's publication state"
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

# --- J6: a submodule inside the bundle, told to report itself clean ---
# `status` walks into a submodule and reports its worktree as dirty, unless it
# has been told not to. `submodule.<name>.ignore=all` -- and `diff.ignoreSubmodules`,
# which reaches `status` through the same option -- silences that, and the
# gitlink then keeps an H tag in `ls-files -v`, so neither J2/J3's index check
# nor J4's --untracked-files=all sees it. The submodule's worktree is inside the
# bundle directory, so `capability install`'s directory copy carries whatever it
# holds. Only naming --ignore-submodules on the command line, for the same
# reason --untracked-files is named there, reaches it.
new_sandbox j6
vendor_submodule
git_init "$ROOT"
publish "$ROOT"
printf 'UNPUBLISHED\n' > "$BUNDLE/vendor/lib.py"
git -C "$ROOT" config "submodule.$SUBMODULE_NAME.ignore" all
[ "$(git -C "$ROOT" ls-files -s -- "$SUBMODULE_NAME" | cut -c1-6)" = "160000" ] ||
  fail "J6: precondition -- the bundle should hold a gitlink, not a directory of files"
[ -z "$(git -C "$BUNDLE" status --porcelain --ignored --untracked-files=all -- . 2>/dev/null)" ] ||
  fail "J6: precondition -- the configured status should report this bundle clean"
[ "$(git -C "$BUNDLE" ls-files -v -- . | cut -c1 | sort -u | tr -d '\n')" = "H" ] ||
  fail "J6: precondition -- the index check should see nothing to complain about"
run_hook
[ "$(installs)" = 0 ] || fail "J6: a submodule told to hide its dirt was installed"
err_has "uncommitted or ignored" || fail "J6: wrong refusal (err: $(cat "$SB/err"))"
[ ! -f "$(sidecar)" ] || fail "J6: refusal wrote the sidecar, making the miss permanent"
pass "J6: a submodule configured to report itself clean does not hide from the guard"

# --- J7: the same setting, committed in .gitmodules, so it follows a clone ---
# J6 is a local `.git/config` edit and stops at the developer's machine. `ignore`
# is equally valid in `.gitmodules`, which is a tracked file: a repository can
# ship it, and every consumer clone -- the marketplace shape of case A2 -- then
# reads it. That is what makes this a defect in the guard rather than a
# development-worktree curiosity, and it is why the case is pinned separately.
new_sandbox j7
vendor_submodule "ignore = all"
git_init "$ROOT"
publish "$ROOT"
printf 'UNPUBLISHED\n' > "$BUNDLE/vendor/lib.py"
[ -n "$(git -C "$ROOT" ls-files -- .gitmodules)" ] ||
  fail "J7: precondition -- .gitmodules must be tracked, or this is just J6 again"
[ -z "$(git -C "$BUNDLE" status --porcelain --ignored --untracked-files=all -- . 2>/dev/null)" ] ||
  fail "J7: precondition -- the shipped setting should report this bundle clean"
run_hook
[ "$(installs)" = 0 ] || fail "J7: a submodule hidden by committed .gitmodules was installed"
err_has "uncommitted or ignored" || fail "J7: wrong refusal (err: $(cat "$SB/err"))"
pass "J7: a submodule hidden by a committed .gitmodules does not hide from the guard"

# --- J8: status delegated to a file-system monitor that under-reports ---
# The last of the four ways config redirects `status` away from the worktree.
# `core.fsmonitor` names a command git trusts for which paths changed; a
# command that answers "none" makes `status` skip the files it would otherwise
# stat, and an edited tracked file reports clean with an H tag and no ignore
# setting anywhere. Overriding it on the command line costs one token and is
# the same move as --untracked-files and --ignore-submodules.
new_sandbox j8
git_init "$ROOT"
publish "$ROOT"
cat > "$SB/bin/fsmonitor-stub" <<'FSM'
#!/usr/bin/env bash
printf 'token'
FSM
chmod +x "$SB/bin/fsmonitor-stub"
git -C "$ROOT" config core.fsmonitor "$SB/bin/fsmonitor-stub"
git -C "$BUNDLE" status --porcelain -- . >/dev/null 2>&1   # prime the index extension
printf 'UNPUBLISHED\n' >> "$BUNDLE/scripts/check.py"
[ -z "$(git -C "$BUNDLE" status --porcelain --ignored --untracked-files=all --ignore-submodules=none -- . 2>/dev/null)" ] ||
  fail "J8: precondition -- the monitored status should report this edited bundle clean"
[ "$(git -C "$BUNDLE" ls-files -v -- . | cut -c1 | sort -u | tr -d '\n')" = "H" ] ||
  fail "J8: precondition -- no index bit is set, so J2/J3's check cannot catch this"
run_hook
[ "$(installs)" = 0 ] || fail "J8: an edit hidden by core.fsmonitor was installed"
err_has "uncommitted or ignored" || fail "J8: wrong refusal (err: $(cat "$SB/err"))"
[ ! -f "$(sidecar)" ] || fail "J8: refusal wrote the sidecar, making the miss permanent"
pass "J8: a file-system monitor that under-reports does not hide edits from the guard"

# --- I1: unchanged bundle takes the fast path on the next session ---
new_sandbox i1
run_hook
run_hook
[ "$(installs)" = 1 ] || fail "I1: unchanged bundle reinstalled ($(installs) installs in 2 runs)"
pass "I1: unchanged bundle takes the hash fast path"

# --- I3: two plugin roots serving one id reinstall, relative root and all ---
# One capability id owns one global mirror and therefore one sidecar. The two
# roots hold byte-identical bundles, so only the absolute paths in the hash stop
# root B from taking a fast path over a mirror that still holds root A's bytes.
# Run with a relative CLAUDE_PLUGIN_ROOT, which the host may supply and the
# protocol nowhere forbids: `cd "." && pwd` resolves it to the same absolute
# root the direct case would start from, so this covers that case as well and
# additionally fails if the absolutisation is ever dropped.
new_sandbox i3
ROOT_B="$SB/root-b"
mkdir -p "$(dirname "$ROOT_B")"
cp -r "$ROOT" "$ROOT_B"
run_hook "$ROOT" .
run_hook "$ROOT_B" .
run_hook "$ROOT" .
[ "$(installs)" = 3 ] ||
  fail "I3: a relative CLAUDE_PLUGIN_ROOT made the hash root-independent ($(installs) installs in 3 runs)"
pass "I3: two plugin roots for one id reinstall, relative root included"

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

# --- L1: the gsd_tools resolver exists once in this repo ---
# It used to exist twice: hooks/gsd-tools.sh, which this repo ships and
# hooks/session-start.sh sources, and a byte-identical inline copy in the hook.
# The copy's comment justified itself with a fact about a different repository.
# Two copies of a resolver is two things to change when the resolution order
# changes, and the release's own bar -- each meaning in exactly one place --
# rules it out. Asserted on the marker rather than on the whole body, so
# re-inlining a *modified* copy fails here too.
L1_DUPES="$(grep -l '_GSD_TOOLS_ARGS_SET' "$REPO_ROOT"/hooks/*.sh | grep -v '/gsd-tools\.sh$')"
[ -z "$L1_DUPES" ] ||
  fail "L1: the gsd_tools resolver is duplicated outside hooks/gsd-tools.sh: $(echo $L1_DUPES)"
pass "L1: the gsd_tools resolver is defined only in hooks/gsd-tools.sh"

# --- L2: a plugin root missing hooks/gsd-tools.sh fails closed and retries ---
# The cost of sourcing instead of inlining, pinned so it stays a decision. Both
# files ship from the same directory of the same repo, so a root missing one is
# a broken install rather than a supported configuration -- but it must say so
# and leave no sidecar, not install silently or write a hash that suppresses the
# next attempt. `gsd-tools` is on PATH here, so the install would otherwise
# succeed: this measures the dependency, not the absence of a binary.
new_sandbox l2
rm -f "$ROOT/hooks/gsd-tools.sh"
[ -x "$SB/bin/gsd-tools" ] || fail "L2: precondition -- the PATH stub should still be there"
run_hook
[ "$(installs)" = 0 ] || fail "L2: installed without the resolver it sources"
err_has "gsd-tools not found" || fail "L2: wrong message (err: $(cat "$SB/err"))"
[ ! -f "$(sidecar)" ] || fail "L2: wrote the sidecar, so the next session would not retry"
pass "L2: a plugin root missing hooks/gsd-tools.sh says so and leaves no sidecar"

# --- D0: the refusals the hook emits and the refusals README documents are
#         the same set ---
# The refusal list went stale three times in one session: the hook grew from
# five refusals to eight while README and CHANGELOG were being written against
# it, and one doc commit shipped "seven" against a hook emitting eight. Two of
# the three copies are now gone -- CHANGELOG points at README's table, and
# neither document states a count any more -- so what is left to check is one
# pair, by equality in both directions.
#
# Equality both ways, not a subset: a subset check sees neither a refusal added
# to the hook and to README while some third statement goes stale, nor a
# reworded refusal that leaves its superseded text behind in the table.
#
# What this does NOT check: that README's remedies are correct, that its prose
# grouping matches the table's order, or anything about CHANGELOG. It compares
# two sets of strings.
#
# Compared on the message BODY: the "capability-auto-install: " prefix and the
# "; refusing to install it at global scope" tail are identical across all of
# them and README deliberately omits both. $CAP_ID and $PUBLISHED are
# substituted with what README writes in their place, so the comparison is
# string equality rather than a substring search that a partial rewrite passes.
REPO_ROOT_D0="$(cd "$(dirname "$0")/.." && pwd)"
d0_report="$(python3 - "$REPO_ROOT_D0" "$CAP_ID" <<'PYEOF'
import re, sys, pathlib

root, cap = pathlib.Path(sys.argv[1]), sys.argv[2]
hook = (root / "hooks" / "capability-auto-install.sh").read_text()
readme = (root / "README.md").read_text()
TAIL = "; refusing to install it at global scope"
problems = []

def body(msg):
    msg = msg.split(TAIL)[0]
    msg = re.sub(r"\$\{?CAP_ID\}?", cap, msg)
    msg = re.sub(r"\$\{?PUBLISHED\}?", "<ref>", msg)
    return msg.removeprefix("capability-auto-install: ").strip()

emitted = [body(m) for m in re.findall(r'echo "(capability-auto-install: [^"]+)" >&2', hook)
           if TAIL in m]

# README: the rows of the table whose header names the refusals. Anchoring on
# the header rather than on "any table row holding a code span" keeps this from
# silently matching some other table if this one is moved or renamed -- it
# fails loudly instead, which is the correct answer for a parity gate.
readme_rows = []
lines = readme.splitlines()
for i, line in enumerate(lines):
    if line.startswith("| It refuses when |"):
        for row in lines[i + 2:]:
            if not row.startswith("|"):
                break
            readme_rows.append(row)
        break
else:
    problems.append("README.md has no table headed '| It refuses when |'")
readme_msgs = []
for row in readme_rows:
    cells = row.split("|")
    span = re.findall(r"`([^`]+)`", cells[2] if len(cells) > 2 else "")
    if span:
        readme_msgs.append(body(span[0]))

n = len(emitted)
if n == 0:
    problems.append("no refusals found in the hook; the extractor regex has drifted")
for dup in {m for m in readme_msgs if readme_msgs.count(m) > 1}:
    problems.append(f"README.md lists this refusal more than once: {dup!r}")
for m in sorted(set(emitted) - set(readme_msgs)):
    problems.append(f"README.md does not document the refusal {m!r}")
for m in sorted(set(readme_msgs) - set(emitted)):
    problems.append(f"README.md documents {m!r}, which the hook no longer emits")

for p in problems:
    print("D0-PROBLEM:", p)
print("D0-TOTAL:", n)
PYEOF
)"
# read, not `set --`: an empty $d0_report (no python3 on PATH, or a python that
# died) leaves `set --` with no positional parameters, and reading $1 under
# `set -u` then aborts the whole suite -- silently skipping the containment
# assertion, which is the one thing here that must never be skipped. `read`
# leaves D0_TOTAL empty instead, which the check below reports as a failure.
D0_TOTAL=""
D0_PROBLEMS=0
read -r _ D0_TOTAL <<<"$(printf '%s\n' "$d0_report" | grep '^D0-TOTAL:')"
while IFS= read -r _problem; do
  [ -n "$_problem" ] || continue
  fail "D0: ${_problem#D0-PROBLEM: }"
  D0_PROBLEMS=$((D0_PROBLEMS + 1))
done <<<"$(printf '%s\n' "$d0_report" | grep '^D0-PROBLEM:')"
if [ -z "$D0_TOTAL" ]; then
  fail "D0: the doc-parity check produced no result; is python3 on PATH?"
elif [ "$D0_TOTAL" -eq 0 ]; then
  fail "D0: no refusals found in the hook"
elif [ "$D0_PROBLEMS" -eq 0 ]; then
  pass "D0: the hook's $D0_TOTAL refusals and README's table of them are the same set"
fi

[ "$FAILURES" -eq 0 ] || { echo "$FAILURES FAILED"; exit 1; }
echo "ALL PASS"
exit 0
