#!/bin/sh
set -eu

if [ "$(uname -s)" != "Darwin" ]; then
  printf '%s\n' 'build_macos_app.sh must run on macOS.' >&2
  exit 2
fi

repo_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
version=${VERSION:-$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$repo_root/pyproject.toml")}
output_dir=${MINDMAP_MACOS_OUTPUT_DIR:-"$repo_root/dist/macos"}
app="$output_dir/Mindmap.app"
binary_dir="$app/Contents/MacOS"
resource_dir="$app/Contents/Resources"
iconset="$output_dir/Mindmap.iconset"

mkdir -p "$binary_dir" "$resource_dir"
cp "$repo_root/desktop/Info.plist" "$app/Contents/Info.plist"
cp "$repo_root/LICENSE" "$resource_dir/LICENSE.txt"
cp "$repo_root/THIRD_PARTY_NOTICES.txt" "$resource_dir/THIRD_PARTY_NOTICES.txt"
plutil -replace CFBundleShortVersionString -string "$version" "$app/Contents/Info.plist"
plutil -replace CFBundleVersion -string "$version" "$app/Contents/Info.plist"

rm -rf "$iconset"
(cd "$repo_root" && go run ./scripts/generate_icon.go "$iconset")
iconutil -c icns "$iconset" -o "$resource_dir/Mindmap.icns"
rm -rf "$iconset"

(cd "$repo_root/desktop/frontend" && npm ci && npm run build)
for arch in amd64 arm64; do
  clang_arch=$arch
  if [ "$arch" = "amd64" ]; then
    clang_arch=x86_64
  fi
  (cd "$repo_root/desktop" && \
    CGO_ENABLED=1 GOOS=darwin GOARCH="$arch" MACOSX_DEPLOYMENT_TARGET=12.0 \
    CGO_CFLAGS="-arch $clang_arch" CGO_LDFLAGS="-arch $clang_arch" \
    go build -tags production -trimpath \
      -ldflags "-s -w -X main.version=$version" -o "$output_dir/Mindmap-$arch" .)
done
lipo -create "$output_dir/Mindmap-amd64" "$output_dir/Mindmap-arm64" -output "$binary_dir/Mindmap"
lipo -verify_arch x86_64 arm64 "$binary_dir/Mindmap"
rm "$output_dir/Mindmap-amd64" "$output_dir/Mindmap-arm64"
chmod 0755 "$binary_dir/Mindmap"
printf 'Built %s\n' "$app"
