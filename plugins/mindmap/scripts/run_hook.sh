#!/bin/sh

# Agent desktop apps do not always inherit the shell that ran `mindmap setup`.
# Prefer the absolute interpreter saved by setup, then fall back to explicit and
# conventional locations. Every candidate must satisfy the package's Python
# 3.10 minimum before it can execute a bundled entrypoint.

script_dir=${0%/*}
if [ "$script_dir" = "$0" ]; then
  script_dir=.
fi
script_dir=$(CDPATH='' cd "$script_dir" && pwd) || exit 0
entrypoint="$script_dir/hook.py"
failure_status=0
failure_message='Mindmap hook warning: Python 3.10+ was not found. Run mindmap setup again or set MINDMAP_PYTHON to an absolute interpreter path in the agent environment.'
if [ "${0##*/}" = "mindmap" ]; then
  entrypoint="$script_dir/mindmap.py"
  failure_status=2
  failure_message='mindmap: Python 3.10+ was not found. Run mindmap setup again or set MINDMAP_PYTHON to an absolute interpreter path.'
fi

run_with_python() {
  candidate=$1
  shift
  [ -n "$candidate" ] || return 1
  case "$candidate" in
    */*) ;;
    *) candidate=$(command -v "$candidate" 2>/dev/null) || return 1 ;;
  esac
  [ -x "$candidate" ] || return 1
  "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' </dev/null >/dev/null 2>&1 || return 1
  exec "$candidate" "$entrypoint" "$@"
}

configured_python=
run_configured_python() {
  config_file=$1
  shift
  if [ -r "$config_file" ]; then
    IFS= read -r configured_python < "$config_file" || configured_python=
    if [ -n "$configured_python" ]; then
      run_with_python "$configured_python" "$@"
    fi
  fi
}

if [ -n "${MINDMAP_PYTHON:-}" ]; then
  run_with_python "$MINDMAP_PYTHON" "$@"
fi

if [ -n "${HOME:-}" ]; then
  run_configured_python "$HOME/Library/Application Support/mindmap/python-path" "$@"
  if [ -n "${XDG_CONFIG_HOME:-}" ]; then
    run_configured_python "$XDG_CONFIG_HOME/mindmap/python-path" "$@"
  fi
  run_configured_python "$HOME/.config/mindmap/python-path" "$@"
fi

run_with_python python3 "$@"

for candidate in \
  "${HOME:-}/.local/bin/python3" \
  "${HOME:-}/.pyenv/shims/python3" \
  "${HOME:-}/.asdf/shims/python3" \
  "${HOME:-}/.local/share/mise/shims/python3" \
  /opt/homebrew/bin/python3 \
  /usr/local/bin/python3 \
  /opt/local/bin/python3 \
  /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
  /home/linuxbrew/.linuxbrew/bin/python3 \
  /run/current-system/sw/bin/python3 \
  "${HOME:-}/.nix-profile/bin/python3" \
  /usr/bin/python3
do
  run_with_python "$candidate" "$@"
done

printf '%s\n' "$failure_message" >&2
exit "$failure_status"
