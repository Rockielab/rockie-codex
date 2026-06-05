#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" != "--execute" ]]; then
  echo "DRY-RUN: review inputs/athinput.stub on an authorized Athena++ host."
  echo "Pass --execute only after loading/building Athena++ in that environment."
  exit 0
fi
if [[ "${ROCKIE_COMPUTE_AUTHORIZED:-}" != "1" ]]; then
  echo "Refusing to execute Athena++ without ROCKIE_COMPUTE_AUTHORIZED=1." >&2
  exit 2
fi
if [[ "${ROCKIE_COMPUTE_RUNTIME:-}" != "hpc" && "${ROCKIE_COMPUTE_RUNTIME:-}" != "tenant" && "${ROCKIE_COMPUTE_RUNTIME:-}" != "rockie" ]]; then
  echo "Refusing to execute Athena++ outside approved compute runtime." >&2
  exit 2
fi

command -v athena >/dev/null 2>&1 || {
  echo "Athena++ executable 'athena' not found in PATH; load/build it first." >&2
  exit 2
}

athena -i inputs/athinput.stub
