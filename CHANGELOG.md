# Changelog

All notable changes appear here. Mindmap follows semantic versioning while the public interfaces settle before 1.0.

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
