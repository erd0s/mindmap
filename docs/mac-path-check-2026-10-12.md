# macOS project path repair, 12 October 2026

A local run on the 0.3.2 repair branch (`faade9a`) failed Go activation and shared route-golden tests. macOS temporary paths can appear under both `/var/...` and `/private/var/...`. The Go implementation resolved symlinks for only one side of some home/project comparisons, causing an existing project inside the home to be rejected as outside it. Python already resolves both sides.

Canonicalize the project root before deriving its route and canonicalize the default home as well as the configured override. Existing containment and home-as-project rejection remain. A regression checks a symlinked home via both names and rejects a project symlink that escapes the home. Existing route golden cases and activation tests now pass on the MacBook. No database migration, plugin activation or live map rewrite is involved.

Two test assumptions were also corrected: the desktop-root test must expect the canonical filesystem path, and the Unicode graph-border test must select Unicode mode rather than inherit TERM=dumb. Other tests continue to cover ASCII/limited terminals. The remaining first-run interpreter failure came from Apple's `/usr/bin/python3` 3.9.6, below the documented Python 3.10 prerequisite. Validation used the already installed Homebrew Python 3.14.7 by prepending its directory only for the test command; no system setting was changed.

Validation:

- Before the fix: activation, configured-home routes and two shared Unicode route cases failed with home-containment errors. The complete original output is `mindmap-go.log` under the local overnight evidence directory.
- After the fix: `PATH=/opt/homebrew/bin:$PATH go test -race ./...` and `go vet ./...` passed.
- The unchanged Python suite passed all 155 tests; the unchanged frontend passed all 17 tests before this Go-only repair.

The patch was prepared from the preserved 0.3.2 repair branch, then rebased onto current main `eb16a43`. Those bases differ only in release/closeout documentation; the repaired implementation is the same. This is not a rollout. It does not resolve the broader resume-quality, four-host cutover, canary, production reconciliation or product-contract issues. The installed application/plugins and production maps were untouched. Local evidence is retained in the 12 October overnight work directory.
