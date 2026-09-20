# Changelog

All notable changes appear here. Mindmap follows semantic versioning while the public interfaces settle before 1.0.

## 0.3.2 — 2026-09-20

- Bound automatic prompt, session-start and Stop context while retaining the
  complete graph. Add paged retrieval of concepts, branches and notices, with
  revisions and continuation cursors that detect concurrent changes.
- Prepare immutable checkpoint requests, distinguish deliberate corrections
  from conflicting repeats, and refresh genuine retry coverage without
  duplicating map mutations. Preserve optimistic revisions, deletion protection
  and the single Stop recovery pass.
- Derive validation guidance from the enforced limits and keep essential
  checkpoint instructions at the start of automatic context.
- Preserve explicitly unchanged branches, reuse existing concepts for completed
  work, and avoid turning unrelated one-off answers into durable map entries.
- Qualify real-tool Stop recovery on both hosts and add regression coverage for
  bounded context, retrieval, correction/retry races and semantic edit scope.

- Replace an installed local Mindmap marketplace with the requested public
  source before upgrading Codex or Claude Code, preserving Claude plugin data.
- Leave nonpersistent Codex sessions (`codex exec --ephemeral`) unattached
  beneath an active project and honour a `MINDMAP_TRACKING=off|on` launcher
  override, so automated utility runs no longer produce unresolvable
  checkpoints or receive injected context.
- Warn when a planned concept's open or settled child was recorded after the
  parent's last revision, and tell the agent to move started planned work and
  finished handoffs or prerequisites in the same checkpoint while keeping
  broader outcomes open.
- Add the planned-parent transition and handoff completion semantic fixtures,
  and accept Claude Code's list-shaped `--output-format json` result in the
  semantic evaluation harness.

## 0.3.1 — 2026-09-02

- Invalidate premature checkpoints when later observed tool activity makes them stale, including fast post-checkpoint work.
- Recover unresolved prior output on the next prompt when an unattended checkpoint attempt fails.
- Remove the fixed 24-concept lifetime ceiling while retaining semantic limits on branch shape, depth, and individual updates.
- Add diagnostics and clearer recording guidance for stale resumes, contradictory frontiers, causal-parent independence, and safe non-interactive checkpoint transport.
- Make a forced Claude Code integration refresh reinstall same-version plugin contents while preserving plugin data.
- Add repeatable cross-host reliability evaluations, cold-read tooling, release criteria, and product screenshots.

## 0.3.0 — 2026-08-15

- Replace the browser hub with a live, multi-window Wails desktop viewer for macOS.
- Rename the terminal executable to `mindmap` and make the viewer its default command.
- Add project, snapshot, setup, doctor, configuration, desktop-open, and deletion commands.
- Add confirmed recursive branch deletion to the desktop and terminal interfaces.
- Add terminal capability detection, ASCII fallback, `NO_COLOR` support, and a complete shortcut overlay.
- Add checksum-verifying shell and PowerShell installers.
- Add signed and notarized macOS release automation and cross-platform terminal artifacts.
- Publish under the MIT License and replace private deployment documentation.

The live SQLite database remains machine-local. Windows and Linux desktop packages, Windows agent hooks, and cross-machine synchronization are deferred.
