#!/usr/bin/env python3
"""finetune-model skill — deploy the trained artifact through the inference loader.

When a Track 2 fine-tune GPU job reaches ``DONE`` with the trained-weights
artifact present, this helper deploys the fine-tuned model through the
*existing* platform-context inference-loader path and emits an
endpoint + token + curl payoff into the lab surface.

It composes existing platform APIs only — no training, no GPU, no spend in
this module. It orchestrates HTTP calls:

1. ``GET /api/jobs/{job_id}/artifacts`` — find ``results/fine-tuned-model.tar.gz``.
2. ``POST /api/inference/loads`` — hand off the artifact via the
   ``rockie-job-artifact://`` scheme url (never a signed HTTPS url).
3. ``GET /api/inference/loads/{id}/endpoint/wait`` — wait for endpoint readiness.
4. ``POST /api/notes/{note_id}/dashboard/append`` — emit the deploy payoff.

The **no-spend boundary**: if the trained artifact is absent, this helper
RAISES :class:`DeployError` and never calls the loader. A 402 from the loader
is surfaced verbatim — the platform owns spend.

Reads ``ROCKIELAB_API_URL``, ``ROCKIELAB_TENANT_ID``, and
``ROCKIELAB_TENANT_TOKEN`` from env, mirroring
``skills/experiment/runtime/submit.py``. Auth headers (``X-Tenant-Token`` +
``X-Tenant-Id``) are required on every control-plane call;
``ROCKIELAB_TENANT_ID`` is never used as the token.

CLI::

    deploy.py --job-id job_abc [--note-id note_xyz] [--model llama-3-8b] \\
              [--api-url ...] [--tenant-id ...]

Exit codes: 0 success; 5 no trained artifact (no spend); 6 loader/402 error;
7 endpoint not ready.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

TRAINED_ARTIFACT_PATH = "results/fine-tuned-model.tar.gz"
ROCKIE_RUNTIME_USER_AGENT = "rockie-runtime/1.0 (+https://api.rockielab.com)"
INFERENCE_MODEL_NAME = "fine-tuned-model"
WITHHELD_TOKEN_PLACEHOLDER = "$ROCKIE_INFERENCE_BEARER_TOKEN"

EXIT_NO_ARTIFACT = 5
EXIT_LOADER_ERROR = 6
EXIT_ENDPOINT_NOT_READY = 7


class DeployError(Exception):
    """Raised when deployment cannot proceed or the platform rejects it.

    ``exit_code`` lets the CLI map the failure class to a distinct process
    exit code without re-parsing the message.
    """

    def __init__(self, message: str, *, exit_code: int = EXIT_LOADER_ERROR) -> None:
        super().__init__(message)
        self.exit_code = exit_code


# --------------------------------------------------------------------------- #
# env + auth helpers (mirrors submit.py)
# --------------------------------------------------------------------------- #
def _api_url(override: Optional[str] = None) -> str:
    raw = (override or os.environ.get("ROCKIELAB_API_URL", "")).rstrip("/")
    if not raw:
        raise DeployError("ROCKIELAB_API_URL is not set in the environment.")
    return raw


def _tenant_token() -> str:
    raw = os.environ.get("ROCKIELAB_TENANT_TOKEN", "")
    if not raw:
        raise DeployError("ROCKIELAB_TENANT_TOKEN is not set in the environment.")
    return raw


def _tenant_id(override: Optional[str] = None) -> str:
    raw = override or os.environ.get("ROCKIELAB_TENANT_ID", "")
    if not raw:
        raise DeployError(
            "ROCKIELAB_TENANT_ID is not set in the environment. "
            "Set it explicitly; tenant tokens are not tenant identity."
        )
    return raw


def _headers(tenant_id: Optional[str] = None) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": ROCKIE_RUNTIME_USER_AGENT,
        "X-Tenant-Token": _tenant_token(),
        "X-Tenant-Id": _tenant_id(tenant_id),
    }


# --------------------------------------------------------------------------- #
# the single low-level HTTP seam — tests patch this one function
# --------------------------------------------------------------------------- #
def _http(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    body: Optional[bytes] = None,
) -> tuple[int, bytes]:
    """Perform one HTTP request. Returns ``(status_code, body_bytes)``.

    Never raises on a network/HTTP error: a non-2xx HTTPError yields its
    ``(code, body)`` so callers can surface platform responses (e.g. 402)
    verbatim, and a transport failure yields ``(0, <json error body>)``.
    """
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read()
        except Exception as read_error:  # pragma: no cover - defensive
            return exc.code, _error_body(f"http_error_read_failed: {read_error}")
    except urllib.error.URLError as exc:
        return 0, _error_body(f"network_error: {exc.reason}")
    except Exception as exc:  # pragma: no cover - defensive
        return 0, _error_body(f"transport_error: {exc}")


def _error_body(error: str) -> bytes:
    return json.dumps({"error": error}).encode("utf-8")


def _decode_json(body: bytes) -> Any:
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return body.decode("utf-8", errors="replace")


def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


# --------------------------------------------------------------------------- #
# step 1 + 2: artifacts
# --------------------------------------------------------------------------- #
def list_artifacts(
    job_id: str,
    *,
    api_url: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> list[dict]:
    """GET /api/jobs/{job_id}/artifacts → list of artifact dicts."""
    api = _api_url(api_url)
    code, body = _http(
        "GET",
        f"{api}/api/jobs/{_quote(job_id)}/artifacts",
        headers=_headers(tenant_id),
    )
    parsed = _decode_json(body)
    # code == 0 is a transport/network failure from the _http seam, not an
    # empty artifact list — surface it clearly instead of masquerading as
    # "no artifact" (which would print a misleading no-spend message).
    if code == 0 or code >= 400:
        raise DeployError(
            f"GET /jobs/{job_id}/artifacts failed ({code}): {parsed!r}",
            exit_code=EXIT_LOADER_ERROR,
        )
    if isinstance(parsed, list):
        return parsed
    return []


def find_trained_artifact(artifacts: list[dict]) -> Optional[dict]:
    """Return the entry whose path is the canonical trained-model archive."""
    for entry in artifacts or []:
        if isinstance(entry, dict) and entry.get("path") == TRAINED_ARTIFACT_PATH:
            return entry
    return None


def _is_usable_artifact(entry: Optional[dict]) -> bool:
    """A trained artifact must be present AND non-empty to be deployable.

    ``size_bytes`` is optional in the artifact list; when absent we treat it as
    usable (presence is the strongest signal we have), but an explicit ``0``
    means the archive never finished writing — refuse it before any spend.
    """
    if entry is None:
        return False
    size = entry.get("size_bytes")
    return size is None or size > 0


# --------------------------------------------------------------------------- #
# step 3: loader load
# --------------------------------------------------------------------------- #
def _load_request_body(artifact_url: str, model: Optional[str], job_id: str) -> bytes:
    run_name = f"Quickstart fine-tune deploy: {model or job_id}"
    payload = {
        "url": artifact_url,
        "compute_target": "rockie_gpu",
        "keep_running": True,
        "dashboard": {
            "origin_skill": "finetune-model",
            "run_name": run_name,
            "monitoring_profile_id": "inference.batch_baseline.v1",
        },
    }
    return json.dumps(payload).encode("utf-8")


def _create_load(
    artifact_url: str,
    *,
    model: Optional[str],
    job_id: str,
    api: str,
    tenant_id: Optional[str],
) -> str:
    code, body = _http(
        "POST",
        f"{api}/api/inference/loads",
        headers=_headers(tenant_id),
        body=_load_request_body(artifact_url, model, job_id),
    )
    parsed = _decode_json(body)
    # code == 0 (transport failure) is NOT success — fail closed rather than
    # fall through to a confusing "missing load id" message.
    if code == 0 or code >= 400:
        raise DeployError(
            f"POST /api/inference/loads failed ({code}): {parsed!r}",
            exit_code=EXIT_LOADER_ERROR,
        )
    load_id = parsed.get("id") if isinstance(parsed, dict) else None
    if not load_id:
        raise DeployError(
            f"loader response missing load id: {parsed!r}",
            exit_code=EXIT_LOADER_ERROR,
        )
    return load_id


# --------------------------------------------------------------------------- #
# step 4: wait for endpoint
# --------------------------------------------------------------------------- #
def _wait_endpoint(
    load_id: str,
    *,
    api: str,
    tenant_id: Optional[str],
    timeout_seconds: int,
    poll_interval_seconds: int,
) -> dict:
    query = urllib.parse.urlencode(
        {
            "timeout_seconds": timeout_seconds,
            "poll_interval_seconds": poll_interval_seconds,
        }
    )
    code, body = _http(
        "GET",
        f"{api}/api/inference/loads/{_quote(load_id)}/endpoint/wait?{query}",
        headers=_headers(tenant_id),
    )
    parsed = _decode_json(body)
    if code == 0 or code >= 400 or not isinstance(parsed, dict):
        raise DeployError(
            f"endpoint/wait failed ({code}): {parsed!r}",
            exit_code=EXIT_ENDPOINT_NOT_READY,
        )
    return parsed


def _require_ready_endpoint(wait_result: dict) -> dict:
    endpoint = wait_result.get("endpoint")
    if wait_result.get("endpoint_ready") and isinstance(endpoint, dict):
        return endpoint
    raise DeployError(
        "inference endpoint not ready "
        f"(state={wait_result.get('state')!r}, "
        f"timed_out={wait_result.get('timed_out')!r}, "
        f"error_code={wait_result.get('error_code')!r}).",
        exit_code=EXIT_ENDPOINT_NOT_READY,
    )


# --------------------------------------------------------------------------- #
# payoff: endpoint + token + curl
# --------------------------------------------------------------------------- #
def _build_curl(endpoint_url: str, bearer: Optional[str], token_visible: bool) -> str:
    auth = (
        f"Authorization: Bearer {bearer}"
        if bearer and token_visible
        else f"Authorization: Bearer {WITHHELD_TOKEN_PLACEHOLDER}"
    )
    note = (
        ""
        if bearer and token_visible
        else (
            "\n# Bearer token is withheld/rotated by the platform; the lab "
            "runtime supplies $ROCKIE_INFERENCE_BEARER_TOKEN."
        )
    )
    request_body = json.dumps(
        {
            "model": INFERENCE_MODEL_NAME,
            "messages": [{"role": "user", "content": "hello"}],
        }
    )
    return (
        f"curl \"{endpoint_url}\" \\\n"
        f"  -H \"{auth}\" \\\n"
        f"  -H \"Content-Type: application/json\" \\\n"
        f"  -d '{request_body}'" + note
    )


def _build_payoff(job_id: str, load_id: str, artifact_url: str, endpoint: dict) -> dict:
    endpoint_url = endpoint.get("url")
    bearer = endpoint.get("bearer_key") or None
    # A token is "visible" only when the platform both flags it visible AND
    # actually returns a key. This collapses the confused state where the
    # platform sends bearer_key_visible=true with bearer_key=null — we never
    # echo a null token as if it were usable, and never invent one.
    token_visible = bool(endpoint.get("bearer_key_visible", bearer is not None)) and (
        bearer is not None
    )
    return {
        "job_id": job_id,
        "load_id": load_id,
        "artifact_url": artifact_url,
        "endpoint_url": endpoint_url,
        "bearer_token": bearer if token_visible else None,
        "bearer_token_visible": token_visible,
        "curl": _build_curl(endpoint_url, bearer, token_visible),
    }


# --------------------------------------------------------------------------- #
# happy path
# --------------------------------------------------------------------------- #
def deploy_finetuned_model(
    job_id: str,
    *,
    model: Optional[str] = None,
    api_url: Optional[str] = None,
    tenant_id: Optional[str] = None,
    timeout_seconds: int = 120,
    poll_interval_seconds: int = 5,
) -> dict:
    """Deploy the trained artifact for ``job_id`` through the inference loader.

    Fails closed with no spend if the trained artifact is absent.
    """
    artifacts = list_artifacts(job_id, api_url=api_url, tenant_id=tenant_id)
    if not _is_usable_artifact(find_trained_artifact(artifacts)):
        raise DeployError(
            f"no usable fine-tuned artifact ({TRAINED_ARTIFACT_PATH}) for job "
            f"{job_id}; refusing to deploy — no spend.",
            exit_code=EXIT_NO_ARTIFACT,
        )

    api = _api_url(api_url)
    artifact_url = f"rockie-job-artifact://{job_id}/{TRAINED_ARTIFACT_PATH}"
    load_id = _create_load(
        artifact_url, model=model, job_id=job_id, api=api, tenant_id=tenant_id
    )
    wait_result = _wait_endpoint(
        load_id,
        api=api,
        tenant_id=tenant_id,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    endpoint = _require_ready_endpoint(wait_result)
    return _build_payoff(job_id, load_id, artifact_url, endpoint)


# --------------------------------------------------------------------------- #
# lab-surface emit
# --------------------------------------------------------------------------- #
def _dashboard_writer(job_id: str) -> dict[str, str]:
    return {"job_backend": "gpu_job", "job_id": job_id}


def emit_deploy_note(
    note_id: str,
    *,
    job_id: str,
    deploy_result: dict,
    api_url: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> Optional[dict]:
    """POST the deploy payoff to the lab surface as an ``artifact`` event.

    Network/HTTP failures never raise — they return ``None`` so a failed note
    never breaks deploy reporting (mirrors submit.append_dashboard).
    """
    if not note_id:
        return None
    try:
        api = _api_url(api_url)
        payload = {
            "writer": _dashboard_writer(job_id),
            "status_patch": {},
            "metrics": [],
            "events": [
                {
                    "kind": "artifact",
                    "summary": "Fine-tuned model deployed — endpoint live, see curl",
                    "state": "available",
                    "payload": deploy_result,
                }
            ],
            "verdicts": [],
        }
        code, body = _http(
            "POST",
            f"{api}/api/notes/{_quote(note_id)}/dashboard/append",
            headers=_headers(tenant_id),
            body=json.dumps(payload).encode("utf-8"),
        )
        if code == 0 or code >= 400:
            _warn(f"dashboard append failed ({code}): {_decode_json(body)!r}")
            return None
        return _decode_json(body)
    except Exception as exc:
        _warn(f"dashboard append error: {exc}")
        return None


def _warn(message: str) -> None:
    print(f"deploy.py: warning: {message}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="deploy.py",
        description="Deploy a fine-tuned model artifact through the inference loader.",
    )
    p.add_argument("--job-id", required=True, help="The DONE fine-tune job id.")
    p.add_argument("--note-id", default=None, help="Dashboard note id from submit.")
    p.add_argument("--model", default=None, help="Model slug for the run name.")
    p.add_argument("--api-url", default=None, help="Override ROCKIELAB_API_URL.")
    p.add_argument("--tenant-id", default=None, help="Override ROCKIELAB_TENANT_ID.")
    p.add_argument(
        "--timeout-seconds", type=int, default=120,
        help="Endpoint readiness wait budget.",
    )
    return p.parse_args(argv)


def _print_payoff(result: dict) -> None:
    visible = result.get("bearer_token_visible")
    token_line = (
        f"  bearer token : {result.get('bearer_token')}"
        if result.get("bearer_token") and visible
        else "  bearer token : (withheld/rotated by platform — use "
        f"{WITHHELD_TOKEN_PLACEHOLDER})"
    )
    print(
        "Fine-tuned model deployed.\n"
        f"  job id       : {result.get('job_id')}\n"
        f"  load id      : {result.get('load_id')}\n"
        f"  artifact     : {result.get('artifact_url')}\n"
        f"  endpoint url : {result.get('endpoint_url')}\n"
        f"{token_line}\n\n"
        f"{result.get('curl')}",
        file=sys.stdout,
        flush=True,
    )


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    try:
        result = deploy_finetuned_model(
            args.job_id,
            model=args.model,
            api_url=args.api_url,
            tenant_id=args.tenant_id,
            timeout_seconds=args.timeout_seconds,
        )
    except DeployError as exc:
        print(f"deploy.py: error: {exc}", file=sys.stderr, flush=True)
        return exc.exit_code
    if args.note_id:
        emit_deploy_note(
            args.note_id,
            job_id=args.job_id,
            deploy_result=result,
            api_url=args.api_url,
            tenant_id=args.tenant_id,
        )
    _print_payoff(result)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
