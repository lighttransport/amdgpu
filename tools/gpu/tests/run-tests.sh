#!/bin/bash
# SPDX-License-Identifier: MIT
# Offline C/mock tests only; never install/load a driver or access a GPU.
set -euo pipefail
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)
for test in "$repo_root"/tools/gpu/tests/test-*.py; do
    echo "== ${test##*/} =="
    python3 "$test" "$repo_root"
done
