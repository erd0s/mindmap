#!/bin/sh
set -eu

repository=${MINDMAP_REPOSITORY:-erd0s/mindmap}
install_dir=${MINDMAP_INSTALL_DIR:-"$HOME/.local/bin"}
base_url=${MINDMAP_RELEASE_URL:-"https://github.com/$repository/releases/latest/download"}

fail() {
  printf 'mindmap installer: %s\n' "$1" >&2
  exit 1
}

command -v curl >/dev/null 2>&1 || fail "curl is required"
command -v sha256sum >/dev/null 2>&1 || command -v shasum >/dev/null 2>&1 || fail "sha256sum or shasum is required"

case $(uname -s) in
  Darwin) target_os=darwin ;;
  Linux) target_os=linux ;;
  *) fail "unsupported operating system; use a release asset directly" ;;
esac

case $(uname -m) in
  x86_64|amd64) target_arch=amd64 ;;
  arm64|aarch64) target_arch=arm64 ;;
  armv7l) target_arch=armv7 ;;
  i386|i686) target_arch=386 ;;
  *) fail "unsupported architecture: $(uname -m)" ;;
esac

asset="mindmap_${target_os}_${target_arch}"
temporary_dir=$(mktemp -d 2>/dev/null || mktemp -d -t mindmap)
trap 'rm -rf "$temporary_dir"' EXIT HUP INT TERM

curl -fL --retry 3 --proto '=https' --tlsv1.2 "$base_url/$asset" -o "$temporary_dir/$asset"
curl -fL --retry 3 --proto '=https' --tlsv1.2 "$base_url/checksums.txt" -o "$temporary_dir/checksums.txt"

expected=$(awk -v name="$asset" '$2 == name { print $1 }' "$temporary_dir/checksums.txt")
[ -n "$expected" ] || fail "release checksum for $asset was not found"
if command -v sha256sum >/dev/null 2>&1; then
  actual=$(sha256sum "$temporary_dir/$asset" | awk '{print $1}')
else
  actual=$(shasum -a 256 "$temporary_dir/$asset" | awk '{print $1}')
fi
[ "$actual" = "$expected" ] || fail "checksum verification failed"

mkdir -p "$install_dir"
chmod 0755 "$temporary_dir/$asset"
mv "$temporary_dir/$asset" "$install_dir/mindmap"
printf 'Installed mindmap to %s/mindmap\n' "$install_dir"

case ":$PATH:" in
  *":$install_dir:"*) ;;
  *) printf 'Add %s to PATH, then open a new shell.\n' "$install_dir" ;;
esac

if [ "${MINDMAP_SKIP_SETUP:-0}" != "1" ]; then
  "$install_dir/mindmap" setup --all || printf '%s\n' 'No agent integration was changed. Run mindmap setup --all after installing Codex or Claude.'
fi
