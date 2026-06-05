from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


RUNTIME_DIR = Path(__file__).resolve().parent
LOCAL_PROFILE_DIR = RUNTIME_DIR / "monitoring-profiles"
PHYSICS_PROFILE_DIR = RUNTIME_DIR.parents[1] / "physics" / "runtime" / "monitoring-profiles"
FALLBACK_PROFILE_ID = "common.default.v1"

_SOFTWARE_TO_PROFILE = {
    "abinit": "physics.electronic_structure.v1",
    "bentoml": "inference.batch_baseline.v1",
    "cp2k": "physics.electronic_structure.v1",
    "gmx": "physics.molecular_dynamics.v1",
    "gromacs": "physics.molecular_dynamics.v1",
    "jax": "experiment.ml_baseline.v1",
    "lammps": "physics.molecular_dynamics.v1",
    "lmdeploy": "inference.batch_baseline.v1",
    "openmm": "physics.molecular_dynamics.v1",
    "pw.x": "physics.electronic_structure.v1",
    "pytorch": "experiment.ml_baseline.v1",
    "python-training": "experiment.ml_baseline.v1",
    "qe": "physics.electronic_structure.v1",
    "quantum-espresso": "physics.electronic_structure.v1",
    "sglang": "inference.batch_baseline.v1",
    "tei": "inference.batch_baseline.v1",
    "torchrun": "experiment.ml_baseline.v1",
    "triton": "inference.batch_baseline.v1",
    "vllm": "inference.batch_baseline.v1",
}


def infer_software(script: str, explicit_software: Optional[str]) -> Optional[str]:
    if explicit_software:
        return explicit_software

    lowered = script.lower()
    markers = (
        ("quantum-espresso", ("pw.x", "ph.x", "neb.x")),
        ("gromacs", ("gmx grompp", "gmx mdrun", "gmx ")),
        ("lammps", ("lmp ", "lmp_mpi", "lammps")),
        ("openmm", ("openmm",)),
        ("cp2k", ("cp2k",)),
        ("abinit", ("abinit",)),
        ("vllm", ("vllm",)),
        ("triton", ("tritonserver",)),
        ("tei", ("text-embeddings-inference", "tei")),
        ("bentoml", ("bentoml",)),
        ("sglang", ("sglang",)),
        ("lmdeploy", ("lmdeploy",)),
        ("torchrun", ("torchrun",)),
        ("pytorch", ("accelerate launch", "python train.py", "python3 train.py", "trainer.fit", "torch.nn")),
        ("jax", ("jax",)),
    )
    for software, tokens in markers:
        if any(token in lowered for token in tokens):
            return software
    return None


def default_profile_id(
    script: str,
    *,
    explicit_profile_id: Optional[str],
    software: Optional[str],
) -> str:
    if explicit_profile_id:
        return explicit_profile_id
    inferred_software = infer_software(script, software)
    if not inferred_software:
        return FALLBACK_PROFILE_ID
    return _SOFTWARE_TO_PROFILE.get(inferred_software, FALLBACK_PROFILE_ID)


def resolve_profile_snapshot(
    *,
    profile_id: Optional[str],
    run_name: str,
    origin_skill: str,
    software: Optional[str],
    script: str,
) -> tuple[str, dict[str, Any]]:
    resolved_software = infer_software(script, software)
    resolved_profile_id = default_profile_id(
        script,
        explicit_profile_id=profile_id,
        software=resolved_software,
    )
    requested_profile_id = profile_id or resolved_profile_id
    profile = _load_profile(resolved_profile_id)
    return resolved_profile_id, _build_snapshot(
        profile=profile,
        requested_profile_id=requested_profile_id,
        run_name=run_name,
        origin_skill=origin_skill,
        software=resolved_software,
        unprofiled=resolved_profile_id == FALLBACK_PROFILE_ID and profile_id is None,
    )


def _load_profile(profile_id: str) -> dict[str, Any]:
    for directory in (LOCAL_PROFILE_DIR, PHYSICS_PROFILE_DIR):
        for path in directory.glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("profile_id") == profile_id:
                return data
    raise ValueError(f"Unknown monitoring profile id: {profile_id}")


def _build_snapshot(
    *,
    profile: dict[str, Any],
    requested_profile_id: str,
    run_name: str,
    origin_skill: str,
    software: Optional[str],
    unprofiled: bool,
) -> dict[str, Any]:
    heartbeat = dict(profile.get("heartbeat") or {})
    stop_policy = dict(profile.get("stop_policy") or {})
    safe_to_auto_stop = bool(
        profile.get("safe_to_auto_stop", stop_policy.get("default_action") == "stop")
    )
    return {
        "profile_id": profile["profile_id"],
        "requested_profile_id": requested_profile_id,
        "run_name": run_name,
        "origin_skill": origin_skill,
        "software": software,
        "domain": profile.get("domain"),
        "family": profile.get("family"),
        "duration_class": profile.get("expected_duration_class"),
        "expected_duration_class": profile.get("expected_duration_class"),
        "heartbeat": heartbeat,
        "cadence_bounds": {
            "min_threshold_seconds": heartbeat.get("min_threshold_seconds"),
            "cadence_seconds": heartbeat.get("cadence_seconds"),
            "max_gap_seconds": heartbeat.get("max_gap_seconds"),
        },
        "metrics": list(profile.get("metrics") or []),
        "panels": list(profile.get("panels") or []),
        "red_flags": list(profile.get("red_flags") or []),
        "stop_policy": stop_policy,
        "safe_to_auto_stop": safe_to_auto_stop,
        "redaction": dict(profile.get("redaction") or {}),
        "unprofiled": unprofiled,
    }
