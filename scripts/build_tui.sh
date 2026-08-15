#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
version=${VERSION:-$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$repo_root/pyproject.toml")}
output_dir=${TUI_OUTPUT_DIR:-"$repo_root/dist/tui"}

supported_targets=(
  darwin/amd64
  darwin/arm64
  freebsd/amd64
  freebsd/arm64
  linux/386
  linux/amd64
  linux/arm
  linux/arm64
  linux/loong64
  linux/ppc64le
  linux/riscv64
  linux/s390x
  openbsd/amd64
  openbsd/arm64
  windows/386
  windows/amd64
  windows/arm64
)

targets=("${supported_targets[@]}")
if (($# > 0)); then
  targets=("$@")
fi

is_supported() {
  local requested=$1
  local supported
  for supported in "${supported_targets[@]}"; do
    if [[ "$requested" == "$supported" ]]; then
      return 0
    fi
  done
  return 1
}

mkdir -p "$output_dir"
for target in "${targets[@]}"; do
  if ! is_supported "$target"; then
    echo "Unsupported TUI target: $target" >&2
    echo "Supported targets: ${supported_targets[*]}" >&2
    exit 2
  fi
  target_os=${target%/*}
  target_arch=${target#*/}
  artifact_arch=$target_arch
  suffix=""
  build_env=("CGO_ENABLED=0" "GOOS=$target_os" "GOARCH=$target_arch")
  if [[ "$target" == "linux/arm" ]]; then
    build_env+=("GOARM=7")
    artifact_arch=armv7
  fi
  if [[ "$target_os" == "windows" ]]; then
    suffix=".exe"
  fi
  output="$output_dir/mindmap_${target_os}_${artifact_arch}${suffix}"
  echo "Building $target -> $output"
  (
    cd "$repo_root"
    env "${build_env[@]}" go build -trimpath \
      -ldflags "-s -w -X main.version=$version" \
      -o "$output" ./cmd/mindmap
  )
done
