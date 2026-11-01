#!/bin/sh
set -eu
script_dir=${0%/*}
if [ "$script_dir" = "$0" ]; then script_dir=.; fi
script_dir=$(CDPATH='' cd "$script_dir" && pwd)
exec "${MINDMAP_PYTHON:-python3}" "$script_dir/mindmap.py" "$@"
