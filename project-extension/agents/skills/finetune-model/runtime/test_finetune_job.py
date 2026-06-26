"""Real-path tests for skills/finetune-model/runtime/finetune_job.py.

These do NOT mock the builder. They build a script + argv and then feed
that argv through submit.py's LIVE ``parse_args`` to prove the payload is
accepted by the same parser the real ``/api/jobs/submit`` path uses. No
``submit()`` call, no network, no GPU.

The adversarial-injection suite is the crux: it feeds shell-metacharacter
payloads as user-controlled refs and proves the generated pod script
neutralizes every one of them (quoted as inert data, never executable
tokens). PR #62 was REJECTED for re-interpolating raw refs in the trainer
command; these tests assert against the *trainer command path*, not just
the shell assignments, so the same bug cannot recur silently.
"""
from __future__ import annotations

import importlib.util
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Absolute path to bash so the adversarial behavioral test can run it even
# while passing an emptied PATH *into* the script's own environment.
_BASH = shutil.which("bash") or "/bin/bash"

# This file lives at <root>/skills/finetune-model/runtime/test_finetune_job.py,
# so the worktree root is three parents up. Put it (and the runtime dir) on
# sys.path so both the sibling builder module and submit.py import cleanly
# regardless of cwd.
_HERE = Path(__file__).resolve()
_RUNTIME_DIR = _HERE.parent
_ROOT = _RUNTIME_DIR.parent.parent.parent
for _p in (str(_ROOT), str(_RUNTIME_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import finetune_job as fj  # noqa: E402


def _load_submit():
    """Import the live submit.py module by absolute path.

    Tries the package path first; falls back to importlib on the absolute
    file path so the live-parser assertion never gets skipped.
    """
    try:
        from skills.experiment.runtime import submit  # type: ignore

        return submit
    except Exception:
        submit_path = _ROOT / "skills" / "experiment" / "runtime" / "submit.py"
        spec = importlib.util.spec_from_file_location("_live_submit", submit_path)
        assert spec and spec.loader, f"cannot load submit.py at {submit_path}"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def _lora_request() -> fj.FinetuneRequest:
    return fj.FinetuneRequest(
        base_model_ref="registry/llama-3-1b",
        registry_dataset_id="ds-track2-abc123",
        method="lora",  # lower-case on purpose: normalization must fix it
        model_param_b=1.0,
    )


def _sft_request() -> fj.FinetuneRequest:
    return fj.FinetuneRequest(
        base_model_ref="registry/qwen-2-1_5b",
        registry_dataset_id="ds-track2-sft999",
        method="SFT",
        model_param_b=1.5,
        gpu_type="A40_48GB",
    )


def test_method_normalized_to_canonical_spelling():
    assert _lora_request().method == "LoRA"
    assert _sft_request().method == "SFT"
    assert fj.FinetuneRequest("m", "d", "Sft").method == "SFT"


def test_training_script_embeds_contract_tokens():
    for req in (_lora_request(), _sft_request()):
        script = fj.build_training_script(req)
        assert req.registry_dataset_id in script
        assert req.base_model_ref in script
        assert 'FINETUNE_PROGRESS {"step":' in script
        assert "/workspace/results/fine-tuned-model/" in script
        assert "/workspace/results/fine-tuned-model.tar.gz" in script
        assert "JOB_DONE" in script
        # JOB_DONE must come after the archive is written.
        assert script.index("fine-tuned-model.tar.gz") < script.rindex("JOB_DONE")


def test_trainer_command_references_quoted_shell_vars_not_raw_refs():
    """The trainer command must use the quoted shell variables, never raw
    refs interpolated into the command (the exact PR #62 defect)."""
    for req in (_lora_request(), _sft_request()):
        cmd = fj._trainer_invocation(req)
        assert '--base-model "$BASE_MODEL_REF"' in cmd
        assert '--dataset-id "$REGISTRY_DATASET_ID"' in cmd
        # The raw ref values must NOT appear anywhere in the trainer command.
        assert req.base_model_ref not in cmd
        assert req.registry_dataset_id not in cmd


def test_lora_and_sft_produce_different_trainer_invocations():
    lora_script = fj.build_training_script(_lora_request())
    sft_script = fj.build_training_script(_sft_request())
    assert "--method lora" in lora_script
    assert "--method sft" in sft_script
    assert "--method lora" not in sft_script
    assert "--method sft" not in lora_script


def test_argv_is_accepted_by_live_submit_parser(tmp_path):
    submit = _load_submit()
    req = _lora_request()

    script_path = tmp_path / "finetune-track2.sh"
    script_path.write_text(fj.build_training_script(req), encoding="utf-8")
    term_sheet_path = tmp_path / "approved-term-sheet.json"
    term_sheet_path.write_text("{}", encoding="utf-8")

    argv = fj.build_submit_argv(
        req,
        str(script_path),
        str(term_sheet_path),
        region="us-east",
        tier="on-demand",
        run_name="Quickstart fine-tune: llama-3-1b",
    )

    # The LIVE parser must accept the argv unmodified.
    ns = submit.parse_args(argv)
    assert ns.origin_skill == "finetune-model"
    assert ns.gpu_type in fj.ALLOWED_GPU_TYPES
    assert ns.gpu_count == req.gpu_count
    assert 1 <= ns.timeout <= 86400
    assert ns.script_file == str(script_path)
    assert ns.term_sheet_json == str(term_sheet_path)
    assert ns.monitoring_profile_id == "experiment.ml_baseline.v1"
    assert ns.region == "us-east"
    assert ns.tier == "on-demand"


def test_sft_argv_also_accepted_by_live_parser(tmp_path):
    submit = _load_submit()
    req = _sft_request()
    script_path = tmp_path / "finetune-track2.sh"
    script_path.write_text(fj.build_training_script(req), encoding="utf-8")
    term_sheet_path = tmp_path / "ts.json"
    term_sheet_path.write_text("{}", encoding="utf-8")
    argv = fj.build_submit_argv(req, str(script_path), str(term_sheet_path))
    ns = submit.parse_args(argv)
    assert ns.origin_skill == "finetune-model"
    assert ns.gpu_type == "A40_48GB"


@pytest.mark.parametrize(
    "req, expect_field",
    [
        (fj.FinetuneRequest("m", "d", "dpo"), "method"),
        (fj.FinetuneRequest("", "d", "LoRA"), "base_model_ref"),
        (fj.FinetuneRequest("m", "", "LoRA"), "registry_dataset_id"),
        (
            fj.FinetuneRequest("m", "d", "LoRA", private_data_ref="tenant://x"),
            "private_data_ref",
        ),
        (fj.FinetuneRequest("m", "d", "LoRA", model_param_b=13.0), "model_param_b"),
        (fj.FinetuneRequest("m", "d", "LoRA", gpu_type="T4"), "gpu_type"),
        (fj.FinetuneRequest("m", "d", "LoRA", gpu_count=0), "gpu_count"),
        (fj.FinetuneRequest("m", "d", "LoRA", timeout=999999), "timeout"),
    ],
)
def test_validate_rejects_with_correct_field(req, expect_field):
    with pytest.raises(fj.FinetuneValidationError) as exc:
        fj.validate(req)
    assert exc.value.field == expect_field


def test_private_data_ref_message_names_1298():
    req = fj.FinetuneRequest("m", "d", "LoRA", private_data_ref="tenant://x")
    with pytest.raises(fj.FinetuneValidationError) as exc:
        fj.validate(req)
    assert exc.value.field == "private_data_ref"
    assert "#1298" in exc.value.reason


def test_model_param_b_none_is_allowed_at_builder():
    # None -> server-side preflight handles it; builder must not refuse.
    req = fj.FinetuneRequest("m", "d", "LoRA", model_param_b=None)
    fj.validate(req)  # no raise


def test_build_submit_argv_refuses_invalid_request(tmp_path):
    bad = fj.FinetuneRequest("m", "d", "LoRA", model_param_b=13.0)
    sp = tmp_path / "s.sh"
    sp.write_text("x", encoding="utf-8")
    ts = tmp_path / "t.json"
    ts.write_text("{}", encoding="utf-8")
    with pytest.raises(fj.FinetuneValidationError) as exc:
        fj.build_submit_argv(bad, str(sp), str(ts))
    assert exc.value.field == "model_param_b"


def test_build_training_script_refuses_invalid_request():
    bad = fj.FinetuneRequest("", "d", "LoRA")
    with pytest.raises(fj.FinetuneValidationError):
        fj.build_training_script(bad)


# --------------------------------------------------------------------------
# Adversarial shell-injection suite — the crux of the #62 re-land.
# --------------------------------------------------------------------------

# Payloads that break out of double quotes or execute via command
# substitution if the ref is interpolated raw into the trainer command.
_INJECTION_PAYLOADS = [
    "$(touch /tmp/pwned)",
    "`id`",
    "a; curl evil",
    'a" ; rm -rf / ; "',
    'registry/model"; echo pwned #',
    "ds-123`rm -rf /`",
    "a\nrm -rf /",
    "$IFS$9cat${IFS}/etc/passwd",
    'x"$(echo hacked)"',
]


@pytest.mark.parametrize("payload", _INJECTION_PAYLOADS)
def test_injection_payload_is_neutralized_in_generated_script(payload):
    """Feed a malicious ref; prove the generated script quotes it as inert
    data and never as an executable token.

    The crux assertion: the only occurrence of the payload in the script is
    inside the ``shlex.quote``-d shell assignment (data), and the trainer
    command line references the shell VARIABLE, so the metacharacters can
    never be evaluated.
    """
    # Use the payload as both refs (model is < 7B by param hint).
    req = fj.FinetuneRequest(
        base_model_ref=payload,
        registry_dataset_id=payload,
        method="lora",
        model_param_b=1.0,
    )
    script = fj.build_training_script(req)

    # 1. The payload appears ONLY as quoted data in the two assignments.
    quoted = shlex.quote(payload)
    assert f"BASE_MODEL_REF={quoted}" in script
    assert f"REGISTRY_DATASET_ID={quoted}" in script

    # 2. The trainer command references the shell variables, NOT the raw ref.
    assert '--base-model "$BASE_MODEL_REF"' in script
    assert '--dataset-id "$REGISTRY_DATASET_ID"' in script

    # 3. Every raw occurrence of the payload in the script must be the
    #    quoted-assignment form — never a bare/unquoted token. We strip the
    #    two known-safe quoted assignments and assert no raw payload remains.
    stripped = script.replace(f"BASE_MODEL_REF={quoted}", "")
    stripped = stripped.replace(f"REGISTRY_DATASET_ID={quoted}", "")
    assert payload not in stripped, (
        f"payload leaked as a non-quoted token: {payload!r}"
    )


@pytest.mark.parametrize("payload", _INJECTION_PAYLOADS)
def test_injection_payload_is_inert_when_shell_parses_script(payload):
    """Prove it for real: have ``bash -n`` parse the generated script (the
    trainer/pip/tar lines stubbed so nothing actually runs) and confirm the
    payload survives as a single literal data word, with no command
    substitution or extra word-splitting escaping the quotes.

    This is a behavioral check, not just a string check: we replace the
    real side-effecting lines with an ``echo`` of the variable and run the
    script in a sandboxed PATH where the trainer/pip/tar binaries do not
    exist, so the ONLY thing that can run is the quoting itself.
    """
    req = fj.FinetuneRequest(
        base_model_ref=payload,
        registry_dataset_id="ds-track2-abc123",
        method="lora",
        model_param_b=1.0,
    )
    script = fj.build_training_script(req)

    # bash -n: parse-only. If the quoting were broken, an unbalanced quote
    # from a payload like 'a" ; rm -rf / ; "' would make this a syntax error.
    syntax = subprocess.run(
        [_BASH, "-n", "/dev/stdin"],
        input=script,
        text=True,
        capture_output=True,
    )
    assert syntax.returncode == 0, (
        f"generated script failed bash -n (broken quoting) for {payload!r}: "
        f"{syntax.stderr}"
    )

    # Now actually evaluate the script's variable-assignment block + an echo,
    # in a shell with an empty PATH so command substitution like $(touch ...)
    # cannot find any binary, and assert the variable expands to the payload
    # VERBATIM (i.e. it was treated as data, not code). We take everything in
    # the generated script up to the first real command (``mkdir``) — that is
    # exactly the BASE_MODEL_REF / REGISTRY_DATASET_ID / METHOD / *_DIR block,
    # and it may legitimately span a newline inside a quoted payload, which a
    # line-based regex would mis-split.
    head, sep, _ = script.partition("\nmkdir ")
    assert sep, "expected a mkdir command after the assignment block"
    probe = head + '\nprintf %s "$BASE_MODEL_REF"\n'
    result = subprocess.run(
        [_BASH, "-c", probe],
        text=True,
        capture_output=True,
        env={"PATH": "", "IFS": ""},
    )
    assert result.returncode == 0, result.stderr
    # The expanded value must equal the payload exactly: no command ran, no
    # metacharacter was interpreted. (IFS is empty so $IFS-based payloads
    # expand to empty for that token but still must not execute anything.)
    assert result.stdout == payload, (
        f"payload was altered/executed instead of treated as data: "
        f"got {result.stdout!r}, want {payload!r}"
    )
    # No injected side effect: /tmp/pwned must not exist.
    assert not Path("/tmp/pwned").exists(), "injection payload executed touch"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
