#!/usr/bin/env python3
"""finetune-model — Track 2 GPU job payload builder.

Pure, stdlib-only. NO network, NO subprocess, NO torch/training imports.
This module builds and validates the *payload* for a Track 2 fine-tune
job: it produces the on-pod bash training script and the argv that the
caller hands to ``skills/experiment/runtime/submit.py``. It never calls
``submit()`` and never touches a GPU.

The validation here mirrors the v1 policy documented in ``SKILL.md`` so a
known-bad request is refused *before* any term sheet is approved or any
spend happens. The GPU-type allow-set is the same tuple ``submit.py``'s
argparse enforces (source of truth: ``skills/experiment/runtime/submit.py``
``parse_args`` ``--gpu-type`` ``choices``); we re-state it here so the
builder fails fast with a clear field-scoped error instead of an argparse
``SystemExit`` deep inside submit.

Shell-injection safety (the reason PR #62 was rejected, re-landed here):
EVERY user-controlled ref that reaches the generated pod script is either
(a) emitted once as a ``shlex.quote()``-d shell assignment and thereafter
referenced ONLY through the quoted shell variable (``"$BASE_MODEL_REF"``,
``"$REGISTRY_DATASET_ID"``), or (b) constrained to a strict safe charset
before it is interpolated as a bare shell token (``method`` -> one of two
hardcoded canonical spellings). There is no path by which a raw ``req.*``
value is interpolated into a shell command. See ``_trainer_invocation``.

See issue #1418 (Track 2 fine-tune pipeline) and #1298 (per-tenant data
API, which v1 deliberately does not depend on).
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Optional

# Mirror of submit.py parse_args --gpu-type choices. Source of truth is
# skills/experiment/runtime/submit.py; kept in sync intentionally so an
# invalid gpu_type is refused here with a field-scoped error rather than
# an opaque argparse SystemExit at submit time.
ALLOWED_GPU_TYPES = ("A40_48GB", "A100_80GB", "H100_SXM", "H200", "B200")

# v1 base-model size ceiling (billions of params). SKILL.md: "<7B".
MAX_MODEL_PARAM_B = 7.0

# argparse --timeout accepts any int; submit() enforces >= 1 and the docs
# cap it at 86400 (24h). We refuse out-of-range here.
MIN_TIMEOUT_SECONDS = 1
MAX_TIMEOUT_SECONDS = 86400

# Canonical method spellings keyed by their normalized (lowercased) form.
# These two strings are the ONLY values that ever reach the generated
# shell as the ``METHOD`` token / the trainer ``--method`` flag, so they
# are a closed, injection-proof set by construction. The trainer flag and
# pip extra are simply ``method.lower()`` of these — equally safe because
# ``validate()`` guarantees ``method`` is one of them before any script.
_METHOD_CANONICAL = {"lora": "LoRA", "sft": "SFT"}

ORIGIN_SKILL = "finetune-model"
DEFAULT_GPU_TYPE = "A100_80GB"
DEFAULT_GPU_COUNT = 1
DEFAULT_TIMEOUT = 14400
DEFAULT_MONITORING_PROFILE_ID = "experiment.ml_baseline.v1"

PRIVATE_DATA_REF_REFUSAL = (
    "private_data_ref is not supported in v1; the per-tenant data API "
    "from issue #1298 must expose a validated training handle first"
)


class FinetuneValidationError(ValueError):
    """Raised when a FinetuneRequest violates the v1 fine-tune policy.

    Carries the offending ``field`` and a human ``reason`` so the caller
    can surface exactly which input to fix before any GPU spend.
    """

    def __init__(self, field: str, reason: str) -> None:
        self.field = field
        self.reason = reason
        super().__init__(f"{field}: {reason}")


@dataclass
class FinetuneRequest:
    """A validated-shape Track 2 fine-tune request.

    ``method`` is normalized to its canonical spelling ("LoRA"/"SFT") at
    construction; ``validate()`` enforces the rest of the v1 policy.
    """

    base_model_ref: str
    registry_dataset_id: str
    method: str
    private_data_ref: Optional[str] = None
    model_param_b: Optional[float] = None
    gpu_type: str = DEFAULT_GPU_TYPE
    gpu_count: int = DEFAULT_GPU_COUNT
    timeout: int = DEFAULT_TIMEOUT

    def __post_init__(self) -> None:
        self.method = _normalize_method(self.method)


def _normalize_method(method: object) -> str:
    """Lowercase-normalize a method to its canonical spelling.

    Unknown methods are returned title-stripped so ``validate`` can report
    the original-ish value; the membership check there is the real gate.
    """
    if not isinstance(method, str):
        return ""
    return _METHOD_CANONICAL.get(method.strip().lower(), method.strip())


def _require_nonempty(value: object, field: str, reason: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise FinetuneValidationError(field, reason)


def _validate_method(req: "FinetuneRequest") -> None:
    if req.method not in ("LoRA", "SFT"):
        raise FinetuneValidationError(
            "method",
            f"method must be one of LoRA or SFT (got {req.method!r})",
        )


def _validate_private_data_ref(req: "FinetuneRequest") -> None:
    if req.private_data_ref not in (None, ""):
        raise FinetuneValidationError("private_data_ref", PRIVATE_DATA_REF_REFUSAL)


def _validate_model_size(req: "FinetuneRequest") -> None:
    if req.model_param_b is not None and req.model_param_b > MAX_MODEL_PARAM_B:
        raise FinetuneValidationError(
            "model_param_b",
            f"v1 supports <{MAX_MODEL_PARAM_B:g}B base models; "
            f"{req.model_param_b:g}B is too large",
        )


def _validate_compute(req: "FinetuneRequest") -> None:
    if req.gpu_type not in ALLOWED_GPU_TYPES:
        raise FinetuneValidationError(
            "gpu_type",
            f"gpu_type must be one of {', '.join(ALLOWED_GPU_TYPES)}",
        )
    if not isinstance(req.gpu_count, int) or req.gpu_count < 1:
        raise FinetuneValidationError("gpu_count", "gpu_count must be an int >= 1")
    if (
        not isinstance(req.timeout, int)
        or req.timeout < MIN_TIMEOUT_SECONDS
        or req.timeout > MAX_TIMEOUT_SECONDS
    ):
        raise FinetuneValidationError(
            "timeout",
            f"timeout must be an int in {MIN_TIMEOUT_SECONDS}..{MAX_TIMEOUT_SECONDS}",
        )


def validate(req: "FinetuneRequest") -> None:
    """Raise FinetuneValidationError on any v1 policy violation.

    Each check lives in its own helper to keep cognitive complexity low.
    After this returns, ``req.method`` is guaranteed to be one of the two
    canonical spellings, which is what makes the trainer ``--method`` flag
    injection-proof.
    """
    _require_nonempty(
        req.base_model_ref, "base_model_ref", "base model ref is required"
    )
    _require_nonempty(
        req.registry_dataset_id,
        "registry_dataset_id",
        "registry dataset id is required",
    )
    _validate_method(req)
    _validate_private_data_ref(req)
    _validate_model_size(req)
    _validate_compute(req)


def _trainer_invocation(req: "FinetuneRequest") -> str:
    """Method-specific trainer command line run on the pod.

    INJECTION SAFETY: user-controlled refs are referenced ONLY through the
    already-``shlex.quote()``-d shell variables ``"$BASE_MODEL_REF"`` and
    ``"$REGISTRY_DATASET_ID"`` defined by :func:`build_training_script`.
    No raw ``req.base_model_ref`` / ``req.registry_dataset_id`` value is
    ever interpolated into this command. ``req.method`` is the only Python
    value interpolated, and it is a closed set ("LoRA"/"SFT" ->
    "lora"/"sft") enforced by :func:`validate`, so it cannot carry shell
    metacharacters. This is the fix for the PR #62 blocking review.
    """
    method_flag = req.method.lower()  # closed {LoRA,SFT} set -> {lora,sft}
    extra = "--lora-r 16 --lora-alpha 32 " if req.method == "LoRA" else ""
    return (
        f"python -m rockie_finetune.train --method {method_flag} "
        f"{extra}"
        '--base-model "$BASE_MODEL_REF" '
        '--dataset-id "$REGISTRY_DATASET_ID" '
        '--output-dir "$OUTPUT_DIR"'
    )


def build_training_script(req: "FinetuneRequest") -> str:
    """Return the bash body for ``finetune-track2.sh`` (runs on the pod).

    Validates first, so a bad request never yields a script. Every
    user-controlled ref is emitted exactly once as a ``shlex.quote()``-d
    shell assignment; the trainer command references those quoted shell
    variables, never the raw Python values. The script writes outputs
    under ``/workspace/results/fine-tuned-model/``, archives to
    ``.../fine-tuned-model.tar.gz``, emits ``FINETUNE_PROGRESS`` JSON
    lines, and prints ``JOB_DONE`` only after the archive is written.
    """
    validate(req)
    # METHOD is a closed canonical set ("LoRA"/"SFT"); the pip extra is
    # its lowercase. Neither can carry metacharacters.
    pip_extra = req.method.lower()
    return f"""#!/usr/bin/env bash
# finetune-track2.sh — generated by skills/finetune-model/runtime/finetune_job.py
# Runs ON THE ROCKIE JOB POD. Training libs are installed here, never locally.
set -euo pipefail

# User-controlled refs are quoted ONCE here and referenced only via these
# shell variables below — never re-interpolated as raw values (PR #62 fix).
BASE_MODEL_REF={shlex.quote(req.base_model_ref)}
REGISTRY_DATASET_ID={shlex.quote(req.registry_dataset_id)}
METHOD="{req.method}"
# Trained outputs are saved under /workspace/results/fine-tuned-model/
OUTPUT_DIR="/workspace/results/fine-tuned-model/"
ARCHIVE_PATH="/workspace/results/fine-tuned-model.tar.gz"

mkdir -p "$OUTPUT_DIR"

# Training libraries are installed on the pod only. Never on the orchestrator.
pip install --quiet "rockie-finetune[{pip_extra}]"

# Trainer emits progress lines of the exact form:
#   FINETUNE_PROGRESS {{"step":N,"loss":X}}
# which submit.py tails into training.step / training.loss dashboard metrics.
{_trainer_invocation(req)}

# Archive the trained artifact, then (and only then) signal completion.
tar -czf "$ARCHIVE_PATH" -C "$OUTPUT_DIR" .
test -f "$ARCHIVE_PATH"

echo "JOB_DONE"
"""


def build_submit_argv(
    req: "FinetuneRequest",
    script_path: str,
    term_sheet_path: str,
    *,
    region: Optional[str] = None,
    tier: Optional[str] = None,
    monitoring_profile_id: str = DEFAULT_MONITORING_PROFILE_ID,
    run_name: Optional[str] = None,
) -> list[str]:
    """Return the argv list for submit.py (NOT executed).

    Calls ``validate(req)`` first, so no argv is ever produced for an
    invalid request. The returned list is what a caller would pass to
    ``submit.parse_args`` / the ``submit.py`` CLI; this module never runs
    it.
    """
    validate(req)
    argv = [
        "--gpu-type",
        req.gpu_type,
        "--gpu-count",
        str(req.gpu_count),
        "--script-file",
        script_path,
        "--timeout",
        str(req.timeout),
        "--term-sheet-json",
        term_sheet_path,
        "--origin-skill",
        ORIGIN_SKILL,
        "--monitoring-profile-id",
        monitoring_profile_id,
    ]
    if region:
        argv += ["--region", region]
    if tier:
        argv += ["--tier", tier]
    if run_name:
        argv += ["--run-name", run_name]
    return argv
