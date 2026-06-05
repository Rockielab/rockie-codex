#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" != "--execute" ]]; then
  echo "DRY-RUN: review inputs/warpx.inputs.stub on an authorized HPC host."
  echo "Pass --execute only after loading WarpX in that environment."
  exit 0
fi
if [[ "${ROCKIE_COMPUTE_AUTHORIZED:-}" != "1" ]]; then
  echo "Refusing to execute WarpX without ROCKIE_COMPUTE_AUTHORIZED=1." >&2
  exit 2
fi
if [[ "${ROCKIE_COMPUTE_RUNTIME:-}" != "hpc" && "${ROCKIE_COMPUTE_RUNTIME:-}" != "tenant" && "${ROCKIE_COMPUTE_RUNTIME:-}" != "rockie" ]]; then
  echo "Refusing to execute WarpX outside approved compute runtime." >&2
  exit 2
fi

command -v warpx >/dev/null 2>&1 || {
  echo "WarpX executable not found in PATH; load the authorized module/container first." >&2
  exit 2
}

warpx inputs/warpx.inputs.stub
