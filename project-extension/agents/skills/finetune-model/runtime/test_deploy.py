"""Tests for the finetune-model deploy helper.

stdlib + monkeypatch only. No network, no torch, no GPU. The single
``deploy._http`` seam is patched with a router keyed by URL so the same
fake covers jobs/artifacts, inference/loads, endpoint/wait, and
dashboard/append.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import deploy  # noqa: E402

API = "https://api.test.rockielab.com"
JOB_ID = "job_abc"
ARTIFACT_URL = f"rockie-job-artifact://{JOB_ID}/results/fine-tuned-model.tar.gz"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ROCKIELAB_API_URL", API)
    monkeypatch.setenv("ROCKIELAB_TENANT_ID", "t-test")
    monkeypatch.setenv("ROCKIELAB_TENANT_TOKEN", "secret-token")


def _json(obj):
    return json.dumps(obj).encode("utf-8")


class Recorder:
    """Captures every (method, url, headers, body) and routes by URL."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, method, url, *, headers, body=None):
        self.calls.append(
            {"method": method, "url": url, "headers": headers, "body": body}
        )
        # endpoint/wait URLs contain the /api/inference/loads prefix, so match
        # the more specific suffix routes first.
        order = ["/endpoint/wait", "/dashboard/append", "/artifacts"]
        order += [n for n in self.routes if n not in order]
        for needle in order:
            if needle in self.routes and needle in url:
                return self.routes[needle]
        raise AssertionError(f"unrouted url: {url}")

    def urls(self):
        return [c["url"] for c in self.calls]

    def body_for(self, needle):
        for c in self.calls:
            if needle in c["url"] and c["body"]:
                return json.loads(c["body"].decode("utf-8"))
        return None


def _install(monkeypatch, routes):
    rec = Recorder(routes)
    monkeypatch.setattr(deploy, "_http", rec)
    return rec


ARTIFACTS_OK = (
    200,
    _json(
        [
            {"path": "results/other.txt", "size_bytes": 10},
            {
                "path": "results/fine-tuned-model.tar.gz",
                "size_bytes": 123456,
                "signed_url": "https://signed.example/x?sig=abc",
            },
        ]
    ),
)
LOAD_OK = (200, _json({"id": "load_abc", "state": "loading"}))


def _endpoint_ready(bearer="bk-live-123", visible=True):
    return (
        200,
        _json(
            {
                "id": "load_abc",
                "state": "ready",
                "endpoint_ready": True,
                "wait_complete": True,
                "timed_out": False,
                "endpoint": {
                    "url": "https://ep.test/v1/chat/completions",
                    "hostname": "ep.test",
                    "bearer_key": bearer,
                    "bearer_key_visible": visible,
                },
            }
        ),
    )


# --------------------------------------------------------------------------- #
def test_happy_path(monkeypatch):
    rec = _install(
        monkeypatch,
        {
            "/artifacts": ARTIFACTS_OK,
            "/api/inference/loads": LOAD_OK,
            "/endpoint/wait": _endpoint_ready(),
        },
    )
    result = deploy.deploy_finetuned_model(JOB_ID, model="llama-3-8b")

    assert result["job_id"] == JOB_ID
    assert result["load_id"] == "load_abc"
    assert result["artifact_url"] == ARTIFACT_URL
    assert result["endpoint_url"] == "https://ep.test/v1/chat/completions"
    assert result["bearer_token"] == "bk-live-123"
    assert result["bearer_token_visible"] is True
    # curl carries the real bearer token.
    assert "Authorization: Bearer bk-live-123" in result["curl"]
    assert '"model":"fine-tuned-model"' in result["curl"].replace(" ", "")

    # the loads POST carried the artifact-scheme url (NOT the signed https one)
    load_body = rec.body_for("/api/inference/loads")
    assert load_body["url"] == ARTIFACT_URL
    assert load_body["url"].startswith("rockie-job-artifact://")
    assert load_body["keep_running"] is True
    assert load_body["dashboard"]["origin_skill"] == "finetune-model"


def test_token_withheld(monkeypatch):
    _install(
        monkeypatch,
        {
            "/artifacts": ARTIFACTS_OK,
            "/api/inference/loads": LOAD_OK,
            "/endpoint/wait": _endpoint_ready(bearer=None, visible=False),
        },
    )
    result = deploy.deploy_finetuned_model(JOB_ID)

    assert result["bearer_token"] is None
    assert result["bearer_token_visible"] is False
    assert "$ROCKIE_INFERENCE_BEARER_TOKEN" in result["curl"]
    # no invented token leaked into the curl
    assert "Bearer bk-" not in result["curl"]


def test_no_artifact_no_spend(monkeypatch):
    """The no-spend boundary: missing trained artifact → no loads call."""
    rec = _install(
        monkeypatch,
        {
            "/artifacts": (200, _json([{"path": "results/logs.txt", "size_bytes": 4}])),
        },
    )
    with pytest.raises(deploy.DeployError) as excinfo:
        deploy.deploy_finetuned_model(JOB_ID)

    assert excinfo.value.exit_code == deploy.EXIT_NO_ARTIFACT
    # The loader was NEVER called — no deploy, no spend.
    assert not any("/api/inference/loads" in u for u in rec.urls())


def test_zero_byte_artifact_no_spend(monkeypatch):
    """A present-but-empty trained archive must not trigger a paid deploy."""
    rec = _install(
        monkeypatch,
        {
            "/artifacts": (
                200,
                _json(
                    [{"path": "results/fine-tuned-model.tar.gz", "size_bytes": 0}]
                ),
            ),
        },
    )
    with pytest.raises(deploy.DeployError) as excinfo:
        deploy.deploy_finetuned_model(JOB_ID)

    assert excinfo.value.exit_code == deploy.EXIT_NO_ARTIFACT
    # 0-byte artifact never reaches the loader — no spend.
    assert not any("/api/inference/loads" in u for u in rec.urls())


def test_network_error_on_artifacts_not_masked_as_no_artifact(monkeypatch):
    """A transport failure (code 0) at artifacts must surface as a loader error,
    NOT be silently converted into a misleading "no artifact" message — and it
    must never reach the loader."""
    rec = _install(
        monkeypatch,
        {"/artifacts": (0, _json({"error": "network_error: connection refused"}))},
    )
    with pytest.raises(deploy.DeployError) as excinfo:
        deploy.deploy_finetuned_model(JOB_ID)

    assert excinfo.value.exit_code == deploy.EXIT_LOADER_ERROR
    assert "artifacts failed (0)" in str(excinfo.value)
    assert not any("/api/inference/loads" in u for u in rec.urls())


def test_confused_token_state_not_echoed(monkeypatch):
    """bearer_key=null with bearer_key_visible=true is a confused platform
    response — never echo a null token as usable, never invent one."""
    _install(
        monkeypatch,
        {
            "/artifacts": ARTIFACTS_OK,
            "/api/inference/loads": LOAD_OK,
            "/endpoint/wait": _endpoint_ready(bearer=None, visible=True),
        },
    )
    result = deploy.deploy_finetuned_model(JOB_ID)

    assert result["bearer_token"] is None
    assert result["bearer_token_visible"] is False
    assert "$ROCKIE_INFERENCE_BEARER_TOKEN" in result["curl"]
    assert "Bearer None" not in result["curl"]


def test_insufficient_credit_402(monkeypatch):
    rec = _install(
        monkeypatch,
        {
            "/artifacts": ARTIFACTS_OK,
            "/api/inference/loads": (
                402,
                _json({"error": {"code": "insufficient_balance", "needed_cents": 500}}),
            ),
        },
    )
    with pytest.raises(deploy.DeployError) as excinfo:
        deploy.deploy_finetuned_model(JOB_ID)

    assert excinfo.value.exit_code == deploy.EXIT_LOADER_ERROR
    assert "402" in str(excinfo.value)
    assert "insufficient_balance" in str(excinfo.value)
    # endpoint/wait must never be reached on a 402.
    assert not any("/endpoint/wait" in u for u in rec.urls())


def test_endpoint_not_ready(monkeypatch):
    _install(
        monkeypatch,
        {
            "/artifacts": ARTIFACTS_OK,
            "/api/inference/loads": LOAD_OK,
            "/endpoint/wait": (
                200,
                _json(
                    {
                        "id": "load_abc",
                        "state": "loading",
                        "endpoint_ready": False,
                        "wait_complete": False,
                        "timed_out": True,
                        "error_code": "timeout",
                        "endpoint": None,
                    }
                ),
            ),
        },
    )
    with pytest.raises(deploy.DeployError) as excinfo:
        deploy.deploy_finetuned_model(JOB_ID)

    assert excinfo.value.exit_code == deploy.EXIT_ENDPOINT_NOT_READY


def test_emit_deploy_note_swallows_500(monkeypatch):
    _install(
        monkeypatch,
        {"/dashboard/append": (500, _json({"error": "boom"}))},
    )
    result = {"job_id": JOB_ID, "load_id": "load_abc", "curl": "curl ..."}
    out = deploy.emit_deploy_note("note_1", job_id=JOB_ID, deploy_result=result)
    assert out is None  # failed note never raises, returns None


def test_emit_deploy_note_skips_empty_note(monkeypatch):
    rec = _install(monkeypatch, {})
    out = deploy.emit_deploy_note("", job_id=JOB_ID, deploy_result={})
    assert out is None
    assert rec.calls == []  # no HTTP when note_id is falsy


def test_emit_deploy_note_artifact_event(monkeypatch):
    rec = _install(monkeypatch, {"/dashboard/append": (200, _json({"ok": True}))})
    result = {"endpoint_url": "https://ep", "curl": "curl ..."}
    out = deploy.emit_deploy_note("note_1", job_id=JOB_ID, deploy_result=result)
    assert out == {"ok": True}
    body = rec.body_for("/dashboard/append")
    assert body["writer"] == {"job_backend": "gpu_job", "job_id": JOB_ID}
    assert body["events"][0]["kind"] == "artifact"
    assert body["events"][0]["payload"] == result


def test_auth_headers_on_every_call(monkeypatch):
    rec = _install(
        monkeypatch,
        {
            "/artifacts": ARTIFACTS_OK,
            "/api/inference/loads": LOAD_OK,
            "/endpoint/wait": _endpoint_ready(),
            "/dashboard/append": (200, _json({"ok": True})),
        },
    )
    result = deploy.deploy_finetuned_model(JOB_ID)
    deploy.emit_deploy_note("note_1", job_id=JOB_ID, deploy_result=result)

    assert rec.calls  # sanity
    for call in rec.calls:
        headers = call["headers"]
        assert headers["X-Tenant-Token"] == "secret-token"
        assert headers["X-Tenant-Id"] == "t-test"
        # never use tenant id as the token
        assert headers["X-Tenant-Token"] != headers["X-Tenant-Id"]


def test_find_trained_artifact():
    assert deploy.find_trained_artifact([]) is None
    assert deploy.find_trained_artifact([{"path": "x"}]) is None
    hit = {"path": "results/fine-tuned-model.tar.gz", "size_bytes": 1}
    assert deploy.find_trained_artifact([hit]) is hit
