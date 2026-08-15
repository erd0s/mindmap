#!/bin/sh
set -eu

if [ "$(uname -s)" != Darwin ]; then
  printf '%s\n' 'test_macos_app.sh must run on macOS.' >&2
  exit 2
fi

repo_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
version=$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$repo_root/pyproject.toml")
app="$repo_root/dist/macos/Mindmap.app"
binary="$app/Contents/MacOS/Mindmap"
plist="$app/Contents/Info.plist"

[ -n "$version" ] || { printf '%s\n' 'Could not read the package version.' >&2; exit 2; }
"$repo_root/scripts/build_macos_app.sh"

plutil -lint "$plist"
[ "$(plutil -extract CFBundleIdentifier raw -o - "$plist")" = io.github.erd0s.mindmap ]
[ "$(plutil -extract CFBundleShortVersionString raw -o - "$plist")" = "$version" ]
[ "$(plutil -extract CFBundleVersion raw -o - "$plist")" = "$version" ]
[ "$(plutil -extract LSMinimumSystemVersion raw -o - "$plist")" = 12.0 ]
lipo -verify_arch x86_64 arm64 "$binary"
[ "$("$binary" --version)" = "$version" ]
[ -s "$app/Contents/Resources/Mindmap.icns" ]
cmp "$repo_root/LICENSE" "$app/Contents/Resources/LICENSE.txt"
cmp "$repo_root/THIRD_PARTY_NOTICES.txt" "$app/Contents/Resources/THIRD_PARTY_NOTICES.txt"

printf 'Verified unsigned universal Mindmap %s at %s\n' "$version" "$app"
