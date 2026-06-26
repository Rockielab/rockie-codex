#!/usr/bin/env python3
"""publish_gate.py -- the agent-builder PUBLISH GATE (slice B1).

Generalizes diligence-deck/critic_loop.py from "harden one deck" to "decide
whether a BUILT AGENT is fit to ship". The proven loop engine is IMPORTED, not
re-implemented (DRY -- single source of truth for the 2-consecutive-clean gate,
counter-reset-on-fail, MAX_ROUNDS cap, CRITICAL-blocks-PASS, and the subagent /
single-process modes). This file adds only the PUBLISH semantics on top:

  DOUBLE-LAYERED ADVERSARY
  ------------------------
  * quality sublayer (ALWAYS runs): does the agent achieve its declared goal?
    Are its tools/prompts/policies sound? Is its reasoning trace defensible?
    Prompt: prompts/quality-critic.md.
  * ai-detection sublayer (OPT-IN): only runs when the declarer cares that the
    output reads as human-authored. SKIPPED when output is understood to be
    AI-generated. Prompt: prompts/ai-detection-critic.md.

  Each round runs every ENABLED sublayer as a fresh, no-memory critic. The round
  PASSES iff every enabled sublayer returns zero CRITICALs. The pass-twice gate,
  the reset-on-any-fail, and the cap are inherited verbatim from the canonical
  engine -- a round that fails ANY sublayer fails the round and resets the
  consecutive-pass counter to zero.

  PUBLISH CONTRACT
  ----------------
  IF the agent has not passed the gauntlet TWICE with zero CRITICALs, the gate
  REFUSES to mark it publishable. The verdict is emitted as JSON:
    {publishable, converged, rounds, consecutive_clean, sublayers_run, reason}

Live critics are injected as callables or an explicit CLI command transport. The
gate still stays transport-agnostic, so the core logic remains provable with
mocked verdicts and fails closed when live critic output is missing or malformed.

    publish_gate.py --selftest                     # deterministic loop-logic proof
    publish_gate.py --agent <repo> --live-command <cmd> --out verdict.json
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any, Callable, Optional
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

# DRY: import the proven loop engine from the sibling diligence-deck skill rather
# than copy it. The skills live side-by-side under skills/; resolve that path
# relative to THIS file (no hardcoded absolute paths).
_HERE = os.path.dirname(os.path.abspath(__file__))
_DD_SCRIPTS = os.path.normpath(
    os.path.join(_HERE, "..", "..", "diligence-deck", "scripts")
)
if _DD_SCRIPTS not in sys.path:
    sys.path.insert(0, _DD_SCRIPTS)

try:
    from critic_loop import (  # noqa: E402  (path-dependent import, intentional)
        run_critic_loop,
        validate_verdict,
        make_subagent_critic,
        make_single_process_critic,
        CRITICAL,
        MAX_ROUNDS,
        REQUIRED_CONSECUTIVE_PASSES,
    )
except ImportError as e:  # pragma: no cover - surfaced loudly, never silent
    sys.stderr.write(
        "publish_gate: could not import the canonical critic_loop engine from "
        f"{_DD_SCRIPTS!r}.\nThe agent-builder publish gate REUSES diligence-deck's "
        "engine (DRY); ensure the diligence-deck skill is present alongside "
        f"agent-builder.\nunderlying error: {e}\n"
    )
    raise

# The two adversary sublayers. quality is always on; ai_detection is opt-in.
QUALITY = "quality"
AI_DETECTION = "ai_detection"
_SUBLAYERS = {QUALITY, AI_DETECTION}
_PROMPT_FILES = {
    QUALITY: "quality-critic.md",
    AI_DETECTION: "ai-detection-critic.md",
}


class LiveCriticError(RuntimeError):
    """A live critic could not produce a strict valid verdict."""


class CandidateBindingError(ValueError):
    """The reviewed candidate cannot be bound to the platform candidate."""


class GateNotPublishableError(RuntimeError):
    """The live gauntlet did not produce an attachable publishable verdict."""


class AgentApiError(RuntimeError):
    """The platform agent API refused or failed a request."""

    def __init__(self, status: int, body: Any, url: str) -> None:
        super().__init__(f"agent API request failed with HTTP {status}: {url}")
        self.status = status
        self.body = body
        self.url = url


@dataclass(frozen=True)
class HttpJsonResponse:
    status: int
    body: Any
    url: str


# --------------------------------------------------------------------------- #
# Live critic adapters and strict verdict parsing
# --------------------------------------------------------------------------- #

def _prompt_path(sublayer: str) -> str:
    if sublayer not in _PROMPT_FILES:
        raise ValueError(f"unknown sublayer {sublayer!r}")
    return os.path.normpath(
        os.path.join(_HERE, "..", "prompts", _PROMPT_FILES[sublayer])
    )


def load_sublayer_prompt(sublayer: str) -> str:
    """Load the checked-in prompt for a live publish-gate sublayer."""
    with open(_prompt_path(sublayer), "r", encoding="utf-8") as f:
        return f.read()


def parse_strict_json_verdict(output: Any) -> dict:
    """Parse a live critic response as exactly one JSON object verdict.

    The live adapter intentionally accepts text/bytes, not an already-decoded
    dict, so a caller cannot bypass the strict "JSON only, nothing else" rule.
    """
    if isinstance(output, bytes):
        output = output.decode("utf-8")
    if not isinstance(output, str):
        raise LiveCriticError(
            f"live critic output must be JSON text, got {type(output).__name__}"
        )
    text = output.strip()
    if not text:
        raise LiveCriticError("live critic output was empty")

    decoder = json.JSONDecoder()
    try:
        parsed, idx = decoder.raw_decode(text)
    except json.JSONDecodeError as e:
        raise LiveCriticError(f"live critic output was not valid JSON: {e}") from e
    if text[idx:].strip():
        raise LiveCriticError("live critic output had non-JSON trailing text")
    if not isinstance(parsed, dict):
        raise LiveCriticError(
            f"live critic verdict must be a JSON object, got {type(parsed).__name__}"
        )
    if not isinstance(parsed.get("pass"), bool):
        raise LiveCriticError("live critic verdict.pass must be a boolean")
    try:
        cleaned = validate_verdict(parsed)
    except Exception as e:
        raise LiveCriticError(f"live critic verdict failed schema validation: {e}") from e
    if parsed["pass"] is not cleaned["pass"]:
        raise LiveCriticError(
            "live critic verdict.pass disagrees with derived CRITICAL count"
        )
    return cleaned


def _fail_closed_verdict(sublayer: str, reason: str, detail: str) -> dict:
    where = f"{sublayer} live critic"
    return {
        "pass": False,
        "violations": [
            {
                "check": "live_critic_failure",
                "severity": CRITICAL,
                "where": where,
                "fix": f"Refuse publish until {reason}: {detail}",
            }
        ],
    }


def make_command_transport(command: str) -> Callable[..., str]:
    """Return a transport that invokes an explicit local critic command.

    The command receives JSON on stdin with prompt/input metadata and must write
    the critic's strict JSON verdict to stdout. This is opt-in wiring for local
    orchestration; when no transport is supplied, the live path fails closed.
    """
    argv = shlex.split(command)
    if not argv:
        raise ValueError("live critic command must not be empty")

    def _transport(*, prompt: str, input_text: str,
                   sublayer: str, round_index: int) -> str:
        payload = json.dumps(
            {
                "prompt": prompt,
                "input_text": input_text,
                "sublayer": sublayer,
                "round": round_index,
            },
            sort_keys=True,
        )
        proc = subprocess.run(
            argv,
            input=payload,
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.strip() or f"exit {proc.returncode}"
            raise LiveCriticError(stderr)
        return proc.stdout

    return _transport


def make_live_sublayer_critic(
    sublayer: str,
    *,
    transport: Optional[Callable[..., Any]],
    review: dict,
    prompt_text: Optional[str] = None,
) -> Callable[[dict, int], dict]:
    """Build a fresh live critic callable for one publish-gate sublayer.

    `transport` is injected by the runtime/orchestrator and is called once per
    sublayer round. It receives the prompt and this round's allowed input only.
    Missing transport, transport exceptions, malformed JSON, and invalid verdict
    schema all become a CRITICAL failure verdict, never a clean round.
    """
    if sublayer not in _SUBLAYERS:
        raise ValueError(f"unknown sublayer {sublayer!r}")
    prompt = prompt_text if prompt_text is not None else load_sublayer_prompt(sublayer)

    def _input_text() -> str:
        if sublayer == AI_DETECTION:
            text = review.get("output_text")
            if text is None or str(text) == "":
                raise LiveCriticError("ai-detection enabled without output_text")
            return str(text)
        quality_input = review.get("quality_input")
        if quality_input is None:
            raise LiveCriticError("quality critic missing materialized review input")
        return str(quality_input)

    def _critic(context: dict, rnd: int) -> dict:
        try:
            if transport is None:
                raise LiveCriticError("live critic transport is not configured")
            output = transport(
                prompt=prompt,
                input_text=_input_text(),
                sublayer=sublayer,
                round_index=rnd,
            )
            return parse_strict_json_verdict(output)
        except Exception as e:
            return _fail_closed_verdict(sublayer, "live critic failed closed", str(e))

    return _critic


# --------------------------------------------------------------------------- #
# Platform candidate materialization, binding, and verdict mapping
# --------------------------------------------------------------------------- #

def _canonical_json(value: Any, *, pretty: bool = False) -> str:
    kwargs = {
        "sort_keys": True,
        "default": str,
    }
    if pretty:
        kwargs["indent"] = 2
    else:
        kwargs["separators"] = (",", ":")
    return json.dumps(value, **kwargs)


def canonical_json_sha256(value: Any) -> str:
    """Stable SHA-256 over canonical JSON, matching platform-context."""
    blob = _canonical_json(value, pretty=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def canonical_candidate_fingerprint(candidate: dict) -> str:
    return canonical_json_sha256(candidate)


def _pick(mapping: dict, *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _pick_field(*sources: tuple[dict, str]) -> Any:
    for mapping, key in sources:
        if isinstance(mapping, dict) and key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _candidate_config(candidate: dict) -> dict:
    cfg = candidate.get("config")
    return dict(cfg) if isinstance(cfg, dict) else {}


def _stringify_review_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return _canonical_json(value, pretty=True)


def materialize_candidate_for_review(
    agent_record: dict,
    candidate: dict,
    candidate_fingerprint: str,
    *,
    output_text: Optional[str] = None,
    sample_run_evidence: Any = None,
) -> dict:
    """Bind a platform candidate to the full artifact reviewed by live critics.

    The binding verifies the backend candidate fingerprint first, then builds a
    stable review artifact from the current agent record plus the
    AgentEditResponse.candidate payload. The quality critic receives the
    materialized artifact; the ai-detection critic receives only output_text.
    """
    if not isinstance(agent_record, dict):
        raise CandidateBindingError("agent_record must be an object")
    if not isinstance(candidate, dict):
        raise CandidateBindingError("candidate must be an object")
    if not candidate_fingerprint:
        raise CandidateBindingError("candidate_fingerprint is required")

    computed = canonical_candidate_fingerprint(candidate)
    if computed != candidate_fingerprint:
        raise CandidateBindingError(
            "candidate_fingerprint mismatch: "
            f"computed {computed}, platform returned {candidate_fingerprint}"
        )

    cfg = _candidate_config(candidate)
    declared_goal = _pick_field(
        (cfg, "declared_goal"),
        (cfg, "goal"),
        (candidate, "declared_goal"),
        (candidate, "goal"),
        (agent_record, "goal"),
        (agent_record, "declared_goal"),
        (agent_record, "name"),
    )
    if declared_goal is None:
        declared_goal = ""
    candidate_output = (
        output_text
        if output_text is not None
        else _pick_field(
            (candidate, "output_text"),
            (candidate, "output"),
            (cfg, "output_text"),
            (cfg, "output"),
        )
    )
    sample = (
        sample_run_evidence
        if sample_run_evidence is not None
        else _pick_field(
            (candidate, "sample_run_evidence"),
            (candidate, "sample_run"),
            (cfg, "sample_run_evidence"),
            (cfg, "sample_run"),
        )
    )

    review_artifact = {
        "declared_goal": declared_goal,
        "config": {
            "agent_config": _pick(agent_record, "config_json", "config") or {},
            "candidate_config": cfg,
            "model": candidate.get("model", agent_record.get("model")),
            "runtime": candidate.get("runtime", agent_record.get("runtime")),
            "tools": candidate.get("tools", agent_record.get("tools") or []),
            "prompts": candidate.get("prompts", agent_record.get("prompts") or []),
            "adversarial": agent_record.get("adversarial") or {},
        },
        "manifest": _pick_field(
            (candidate, "manifest"),
            (cfg, "manifest"),
            (agent_record, "manifest"),
        ) or {},
        "skills": _pick_field(
            (candidate, "skills"),
            (cfg, "skills"),
            (agent_record, "skills"),
        ) or {},
        "hooks": _pick_field(
            (candidate, "hooks"),
            (cfg, "hooks"),
            (agent_record, "hooks"),
        ) or {},
        "policies": candidate.get("policies", agent_record.get("policies") or []),
        "tests": _pick_field(
            (candidate, "tests"),
            (cfg, "tests"),
            (agent_record, "tests"),
        ) or {},
        "sample_run_evidence": sample if sample is not None else {},
    }
    quality_input = _canonical_json(review_artifact, pretty=True)
    review_hash = canonical_json_sha256(review_artifact)

    return {
        "binding_verified": True,
        "candidate": candidate,
        "candidate_payload_hash": computed,
        "candidate_fingerprint": candidate_fingerprint,
        "review_artifact": review_artifact,
        "review_artifact_hash": review_hash,
        "quality_input": quality_input,
        "output_text": _stringify_review_text(candidate_output),
    }


def materialize_agent_repo_for_review(
    agent_path: str,
    *,
    output_text: Optional[str] = None,
) -> dict:
    """Materialize a local agent repo for live CLI review without platform bind."""
    root = Path(agent_path)
    if not root.exists():
        raise FileNotFoundError(agent_path)
    wanted = [
        "CLAUDE.md",
        "agent.config.json",
        "manifest.json",
        ".mcp.json",
    ]
    collected: dict[str, Any] = {"files": {}}
    for rel in wanted:
        p = root / rel
        if p.exists() and p.is_file():
            collected["files"][rel] = p.read_text(encoding="utf-8")
    for dirname in (".claude/skills", ".claude/hooks", "policies", "tests"):
        base = root / dirname
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file():
                rel = p.relative_to(root).as_posix()
                collected["files"][rel] = p.read_text(encoding="utf-8")

    quality_input = _canonical_json(collected, pretty=True)
    return {
        "binding_verified": False,
        "review_artifact": collected,
        "review_artifact_hash": canonical_json_sha256(collected),
        "quality_input": quality_input,
        "output_text": output_text or "",
    }


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_verified_binding(binding: dict) -> str:
    if not isinstance(binding, dict) or binding.get("binding_verified") is not True:
        raise CandidateBindingError(
            "backend verdict mapping requires a verified candidate binding"
        )
    fp = binding.get("candidate_fingerprint")
    if not isinstance(fp, str) or not fp:
        raise CandidateBindingError("verified binding missing candidate_fingerprint")
    return fp


def map_publish_verdict_to_gauntlet_verdict(
    publish_verdict: dict,
    binding: dict,
    *,
    produced_at: Optional[Any] = None,
    notes: Optional[str] = None,
) -> dict:
    """Map the internal publish gate verdict to platform GauntletVerdict."""
    fingerprint = _require_verified_binding(binding)
    clean_rounds = int(publish_verdict.get("consecutive_clean") or 0)
    publishable = (
        bool(publish_verdict.get("publishable"))
        and clean_rounds >= REQUIRED_CONSECUTIVE_PASSES
    )
    rounds = publish_verdict.get("round_log") or []
    if not isinstance(rounds, list):
        raise ValueError("publish_verdict.round_log must be a per-round list")

    if produced_at is None:
        produced = _iso_utc_now()
    elif isinstance(produced_at, datetime):
        dt = produced_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        produced = dt.astimezone(timezone.utc).isoformat()
    else:
        produced = str(produced_at)

    body = {
        "publishable": publishable,
        "clean_rounds": clean_rounds,
        "produced_at": produced,
        "candidate_fingerprint": fingerprint,
        "rounds": rounds,
    }
    attached_notes = notes if notes is not None else publish_verdict.get("reason")
    if attached_notes:
        body["notes"] = str(attached_notes)
    return body


# --------------------------------------------------------------------------- #
# Opt-in platform API client and propose/edit/attach flow
# --------------------------------------------------------------------------- #

def _normalize_api_url(api_url: Optional[str] = None) -> str:
    base = api_url or os.environ.get("ROCKIELAB_API_URL")
    if not base:
        raise ValueError("ROCKIELAB_API_URL or api_url is required")
    return base.rstrip("/")


def _header_has(headers: dict[str, str], needle: str) -> bool:
    return any(k.lower() == needle.lower() for k in headers)


def _header_value(headers: dict[str, str], needle: str) -> Optional[str]:
    for key, value in headers.items():
        if key.lower() == needle.lower():
            return value
    return None


def _cookie_has(cookie_header: str, cookie_name: str) -> bool:
    return any(
        part.strip().startswith(f"{cookie_name}=")
        for part in cookie_header.split(";")
    )


class AgentApiClient:
    """Small opt-in client for the session-authenticated /api/agents routes."""

    def __init__(
        self,
        *,
        api_url: Optional[str] = None,
        auth_headers: Optional[dict[str, str]] = None,
        auth_cookie: Optional[str] = None,
        request_json: Optional[
            Callable[[str, str, dict[str, str], Any], Any]
        ] = None,
    ) -> None:
        self.api_url = _normalize_api_url(api_url)
        self.auth_headers = dict(auth_headers or {})
        if _header_has(self.auth_headers, "X-Tenant-Token"):
            raise ValueError(
                "agent edit routes require session auth, not X-Tenant-Token"
            )
        if _header_has(self.auth_headers, "Authorization"):
            raise ValueError(
                "agent edit routes require rockielab_session Cookie, not Authorization"
            )
        if auth_cookie:
            self.auth_headers["Cookie"] = auth_cookie
        cookie = _header_value(self.auth_headers, "Cookie")
        if not cookie or not _cookie_has(cookie, "rockielab_session"):
            raise ValueError(
                "agent edit routes require caller-provided rockielab_session Cookie"
            )
        self._request_json = request_json

    def _url(self, path: str) -> str:
        return self.api_url + path

    def _request(self, method: str, path: str, body: Any) -> Any:
        url = self._url(path)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            **self.auth_headers,
        }
        if self._request_json is not None:
            resp = self._request_json(method, url, headers, body)
            if isinstance(resp, HttpJsonResponse):
                status, data = resp.status, resp.body
            elif isinstance(resp, tuple) and len(resp) == 2:
                status, data = resp
            else:
                raise TypeError("request_json must return HttpJsonResponse or (status, body)")
        else:
            data_bytes = json.dumps(body).encode("utf-8")
            req = urlrequest.Request(
                url,
                data=data_bytes,
                headers=headers,
                method=method,
            )
            try:
                with urlrequest.urlopen(req) as r:  # nosec: explicit user URL
                    status = int(r.status)
                    raw = r.read().decode("utf-8")
            except urlerror.HTTPError as e:
                status = int(e.code)
                raw = e.read().decode("utf-8")
            data = json.loads(raw) if raw else None

        if status < 200 or status >= 300:
            raise AgentApiError(status, data, url)
        return data

    def propose_edit(self, agent_id: str, patch: dict) -> dict:
        path_id = urlparse.quote(str(agent_id), safe="")
        return self._request("POST", f"/api/agents/{path_id}/edits", patch)

    def attach_gauntlet_verdict(
        self,
        agent_id: str,
        edit_id: str,
        verdict_body: dict,
    ) -> dict:
        path_agent = urlparse.quote(str(agent_id), safe="")
        path_edit = urlparse.quote(str(edit_id), safe="")
        return self._request(
            "POST",
            f"/api/agents/{path_agent}/edits/{path_edit}/gauntlet",
            verdict_body,
        )


def propose_edit_run_gauntlet_and_attach(
    *,
    api_client: AgentApiClient,
    agent_id: str,
    edit_patch: dict,
    agent_record: dict,
    critic_transport: Callable[..., Any],
    ai_detection: bool = False,
    output_text: Optional[str] = None,
    quality_prompt_text: Optional[str] = None,
    ai_detection_prompt_text: Optional[str] = None,
    mode: str = "single",
    max_rounds: int = MAX_ROUNDS,
    required_consecutive: int = REQUIRED_CONSECUTIVE_PASSES,
    verbose: bool = True,
) -> dict:
    """Propose a platform edit, review that exact candidate, then attach.

    This function refuses before attach if the platform candidate fingerprint
    does not match the returned candidate payload or if the live gate does not
    converge to an attachable publishable verdict.
    """
    edit_response = api_client.propose_edit(agent_id, edit_patch)
    edit_id = edit_response.get("edit_id")
    candidate = edit_response.get("candidate")
    candidate_fingerprint = edit_response.get("candidate_fingerprint")
    if not edit_id:
        raise CandidateBindingError("AgentEditResponse missing edit_id")
    effective_required = max(required_consecutive, REQUIRED_CONSECUTIVE_PASSES)
    binding = materialize_candidate_for_review(
        agent_record,
        candidate,
        candidate_fingerprint,
        output_text=output_text,
    )

    quality = make_live_sublayer_critic(
        QUALITY,
        transport=critic_transport,
        review=binding,
        prompt_text=quality_prompt_text,
    )
    ai = None
    if ai_detection:
        ai = make_live_sublayer_critic(
            AI_DETECTION,
            transport=critic_transport,
            review=binding,
            prompt_text=ai_detection_prompt_text,
        )

    publish_verdict = run_publish_gate(
        binding["review_artifact_hash"],
        quality,
        ai_detection_critic=ai,
        mode=mode,
        max_rounds=max_rounds,
        required_consecutive=effective_required,
        verbose=verbose,
    )
    body = map_publish_verdict_to_gauntlet_verdict(publish_verdict, binding)
    if body["publishable"] is not True or body["clean_rounds"] < effective_required:
        raise GateNotPublishableError(
            "live gauntlet did not produce a publishable verdict; not attaching"
        )

    attached = api_client.attach_gauntlet_verdict(agent_id, edit_id, body)
    return {
        "edit": edit_response,
        "binding": binding,
        "publish_verdict": publish_verdict,
        "gauntlet_body": body,
        "attached": attached,
    }


# --------------------------------------------------------------------------- #
# Sublayer composition: turn N enabled sublayer critics into ONE round critic
# --------------------------------------------------------------------------- #

def compose_round_critic(sublayer_critics: dict):
    """Return a single Critic that, per round, runs every enabled sublayer and
    MERGES their violations. A round passes iff EVERY sublayer is CRITICAL-clean.

    `sublayer_critics`: {name -> critic_callable(context, round) -> raw verdict}.
    Each sublayer's verdict is validated/re-derived by the canonical engine's
    validate_verdict; we then tag each violation with its sublayer and merge.
    The merged verdict's `pass` is re-derived from the union of CRITICALs by the
    engine, so a CRITICAL in ANY sublayer fails the round.
    """
    if not sublayer_critics:
        raise ValueError("at least the quality sublayer must be enabled")

    round_violation_log = {}

    def _critic(context: dict, rnd: int) -> dict:
        merged = []
        for name, sub in sublayer_critics.items():
            try:
                v = validate_verdict(sub(context, rnd))
            except Exception as e:
                v = validate_verdict(
                    _fail_closed_verdict(name, "sublayer raised", str(e))
                )
            for viol in v["violations"]:
                merged.append(dict(viol, sublayer=name))
        round_violation_log[rnd] = list(merged)
        # Return a raw verdict; the engine re-derives pass from CRITICAL count.
        return {"violations": merged}

    _critic.round_violation_log = round_violation_log
    return _critic


# --------------------------------------------------------------------------- #
# The publish gate
# --------------------------------------------------------------------------- #

def run_publish_gate(
    agent_path: str,
    quality_critic,
    *,
    ai_detection_critic=None,
    mode: str = "single",
    max_rounds: int = MAX_ROUNDS,
    required_consecutive: int = REQUIRED_CONSECUTIVE_PASSES,
    verbose: bool = True,
) -> dict:
    """Drive the double-layered gauntlet over a built agent and return a verdict.

    quality_critic is REQUIRED (always-on sublayer). ai_detection_critic is
    optional (opt-in sublayer). Both are Critic callables of (context, round) ->
    raw verdict dict; the round critic composes them. The 2-pass gate / reset /
    cap come from the imported run_critic_loop.
    """
    sublayers = {QUALITY: quality_critic}
    if ai_detection_critic is not None:
        sublayers[AI_DETECTION] = ai_detection_critic
    round_critic = compose_round_critic(sublayers)

    result = run_critic_loop(
        draft_path=agent_path,
        critic=round_critic,
        mode=mode,
        max_rounds=max_rounds,
        required_consecutive=required_consecutive,
        verbose=verbose,
    )

    consecutive_clean = (
        result.rounds[-1].consecutive_passes_after if result.rounds else 0
    )
    round_violation_log = getattr(round_critic, "round_violation_log", {})
    verdict = {
        "publishable": bool(result.converged),  # ONLY publishable on convergence
        "converged": result.converged,
        "rounds": result.rounds_run,
        "consecutive_clean": consecutive_clean,
        "required_consecutive": required_consecutive,
        "sublayers_run": sorted(sublayers.keys()),
        "mode": result.mode,
        "isolation": "single-process" if mode == "single" else "subagent",
        "reason": result.reason,
        "round_log": [
            {
                "round": r.round,
                "passed": r.passed,
                "n_critical": r.n_critical,
                "consecutive_passes_after": r.consecutive_passes_after,
                "violations": round_violation_log.get(
                    r.round, r.verdict.get("violations", [])
                ),
            }
            for r in result.rounds
        ],
    }
    return verdict


# --------------------------------------------------------------------------- #
# Deterministic selftest (mocked sublayer verdicts -- proves the gate logic)
# --------------------------------------------------------------------------- #

def _clean():
    return {"pass": True, "violations": []}


def _crit(check="goal_achievement"):
    return {"pass": False, "violations": [
        {"check": check, "severity": "critical",
         "where": "agent goal", "fix": "make the agent actually achieve its goal"}]}


def _scripted(seq):
    return lambda ctx, rnd: seq[rnd - 1]


def _selftest() -> int:
    failures = []

    def chk(name, cond, detail=""):
        print(f"  [{'ok' if cond else 'FAIL'}] {name}"
              + (f" -- {detail}" if detail and not cond else ""))
        if not cond:
            failures.append(name)

    # (1) quality-only, pass/pass -> publishable, converged at round 2.
    print("\n(1) quality-only: PASS, PASS -> publishable at round 2")
    v = run_publish_gate("agent", _scripted([_clean(), _clean()]),
                         mode="single", verbose=False)
    chk("publishable", v["publishable"])
    chk("converged at round 2", v["rounds"] == 2, f"ran {v['rounds']}")
    chk("only quality sublayer ran", v["sublayers_run"] == [QUALITY])

    # (2) reset-on-fail: PASS, FAIL, PASS, PASS -> converges at round 4, not 3.
    print("\n(2) reset-on-fail: PASS, FAIL, PASS, PASS -> round 4")
    v = run_publish_gate("agent",
                         _scripted([_clean(), _crit(), _clean(), _clean()]),
                         mode="single", verbose=False)
    chk("publishable", v["publishable"])
    chk("converged at round 4 (counter reset by the fail)", v["rounds"] == 4,
        f"ran {v['rounds']}")

    # (3) a CRITICAL in the AI-DETECTION sublayer alone fails the round, even
    #     when quality is clean -- proves both sublayers gate the round.
    print("\n(3) ai-detection CRITICAL fails the round even when quality is clean")
    q = _scripted([_clean(), _clean(), _clean(), _clean()])
    # ai-detection: FAIL the first round, then clean -> converges at round 3.
    ai = _scripted([_crit("reads_ai_generated"), _clean(), _clean(), _clean()])
    v = run_publish_gate("agent", q, ai_detection_critic=ai,
                         mode="single", verbose=False)
    chk("both sublayers ran", v["sublayers_run"] == sorted([QUALITY, AI_DETECTION]))
    chk("round-1 failed (ai-detection CRITICAL) -> not converged at 2",
        v["round_log"][0]["passed"] is False)
    chk("converges at round 3", v["rounds"] == 3, f"ran {v['rounds']}")

    # (4) opt-in respected: ai-detection NOT run unless a critic is supplied.
    print("\n(4) ai-detection is OPT-IN -- skipped when no critic supplied")
    v = run_publish_gate("agent", _scripted([_clean(), _clean()]),
                         ai_detection_critic=None, mode="single", verbose=False)
    chk("ai_detection NOT in sublayers_run", AI_DETECTION not in v["sublayers_run"])

    # (5) refusal: never two-in-a-row within the cap -> NOT publishable, fails loud.
    print("\n(5) never converges -> REFUSES to publish, hits the cap")
    v = run_publish_gate("agent",
                         _scripted([_clean(), _crit()] * MAX_ROUNDS),
                         mode="single", verbose=False)
    chk("NOT publishable", not v["publishable"])
    chk("ran exactly MAX_ROUNDS", v["rounds"] == MAX_ROUNDS, f"ran {v['rounds']}")
    chk("reason names the cap", "MAX_ROUNDS" in v["reason"])

    # (6) a single PASS does NOT unlock publish.
    print("\n(6) one PASS does NOT unlock publish")
    v = run_publish_gate("agent", _scripted([_clean(), _crit(), _crit(),
                                             _crit(), _crit(), _crit()]),
                         mode="single", verbose=False)
    chk("one pass then fails -> NOT publishable", not v["publishable"])

    # (7) both execution modes drive identical gate logic.
    print("\n(7) subagent + single modes drive identical gate logic")
    va = run_publish_gate("agent", make_subagent_critic(lambda c, r: _clean()),
                          mode="subagent", verbose=False)
    vb = run_publish_gate("agent", make_single_process_critic(lambda c, r: _clean()),
                          mode="single", verbose=False)
    chk("subagent mode publishable in 2", va["publishable"] and va["rounds"] == 2)
    chk("single mode publishable in 2", vb["publishable"] and vb["rounds"] == 2)
    chk("single mode labels isolation single-process",
        vb["isolation"] == "single-process")

    print("\n" + ("ALL SELFTESTS PASSED" if not failures
                  else f"SELFTEST FAILURES: {failures}"))
    return 0 if not failures else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--selftest", action="store_true",
                   help="run the deterministic mocked-verdict gate-logic test")
    p.add_argument("--agent", help="path to a scaffolded agent repo to gate")
    p.add_argument("--ai-detection", action="store_true",
                   help="enable the opt-in AI-content-detection sublayer")
    p.add_argument("--live-command",
                   help=("explicit live critic command; receives prompt/input JSON "
                         "on stdin and must print strict verdict JSON"))
    p.add_argument("--output-text",
                   help="path to the output text judged by --ai-detection")
    p.add_argument("--mode", choices=("subagent", "single"), default="single")
    p.add_argument("--out", help="write the verdict JSON here (default: stdout)")
    args = p.parse_args(argv)

    if args.selftest:
        return _selftest()

    if not args.agent:
        p.print_help()
        return 0

    if not args.live_command:
        # Live-critic wiring must be explicit. Without a transport this CLI
        # cannot grade an agent; fail loudly rather than emit a fake verdict.
        sys.stderr.write(
            "publish_gate: live LLM sublayer critics are not configured.\n"
            "Pass --live-command to run a real critic transport, or drive\n"
            "run_publish_gate() from the builder orchestrator with injected\n"
            "fresh no-memory critics. The command must return strict JSON.\n"
            "Run `publish_gate.py --selftest` to prove the gate LOGIC.\n"
        )
        return 1

    try:
        output_text = None
        if args.output_text:
            with open(args.output_text, "r", encoding="utf-8") as f:
                output_text = f.read()
        review = materialize_agent_repo_for_review(args.agent, output_text=output_text)
        transport = make_command_transport(args.live_command)
        quality = make_live_sublayer_critic(QUALITY, transport=transport, review=review)
        ai = None
        if args.ai_detection:
            ai = make_live_sublayer_critic(
                AI_DETECTION,
                transport=transport,
                review=review,
            )
        verdict = run_publish_gate(
            args.agent,
            quality,
            ai_detection_critic=ai,
            mode=args.mode,
            verbose=True,
        )
        rendered = json.dumps(verdict, indent=2, sort_keys=True)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(rendered + "\n")
        else:
            print(rendered)
        return 0 if verdict.get("publishable") else 1
    except Exception as e:
        sys.stderr.write(f"publish_gate: live gate failed closed: {e}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
