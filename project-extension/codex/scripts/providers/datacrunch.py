"""providers/datacrunch.py — Verda Cloud (formerly DataCrunch) adapter.

Pure API: no SQL, no budget writes; the harness layer (scripts/gpu.py)
owns those.

Verda specifics worth knowing:

  * **OAuth2 client-credentials, not a static API key.** Set
    DATACRUNCH_CLIENT_ID + DATACRUNCH_CLIENT_SECRET; the adapter calls
    POST /v1/oauth2/token to mint a JWT bearer token, caches it, and
    refreshes when expired. This is different from every other provider
    we support (RunPod/Vast/Prime use static keys).
  * **Pre-registered SSH keys.** Upload your pubkey via the dashboard
    or POST /v1/ssh-keys, then set DATACRUNCH_SSH_KEY_ID to the UUID.
    Vast-style raw-pubkey-at-create is NOT supported.
  * **Spot via flag, not endpoint.** `is_spot: true` in the create body
    chooses spot tier. The cheapest spot price is on the InstanceType's
    `spot_price` field (string-typed; convert).
  * **Status `discontinued` = preempted (for spot).** Vast says
    "intended=running, actual=stopped"; Verda says "status=discontinued"
    on a spot instance whose host preempted. Detection is one-field-clean.
  * **`on_spot_discontinue` policy** controls volume fate after
    preemption: `keep_detached` / `move_to_trash` / `delete_permanently`.
    Adapter defaults to `keep_detached` so the user's data isn't lost
    on first preemption.
  * **10-minute billing increments.** Verda bills in 10-min chunks;
    short-lived test pods round up. The harness's reconcile uses elapsed
    seconds at price_per_hour rate, so the *budget* slightly under-counts
    by a few minutes on preempted-quickly pods. Negligible at H100 spot
    prices (~$0.005/min); not worth complicating the math.
  * **DataCrunch → Verda rebrand.** The legacy domain api.datacrunch.io
    still resolves to the same API; the canonical 2026 name is
    api.verda.com. Adapter pins to the canonical name.
  * **Lifecycle is one endpoint.** PUT /v1/instances with `{action, id}`
    handles start/stop/delete/discontinue/etc. There's no DELETE method
    on the instance path — it's PUT-with-action.

extras keys this adapter reads from SpotSpec.extras:
  * "location_code" (str, required if not set on SpotSpec.region) —
    Verda has multiple data centers (FIN-01, ICE-01, etc.). list_gpus()
    can be called to enumerate available locations.
  * "on_spot_discontinue" (str, default "keep_detached") — what happens
    to the OS volume on preemption.
  * "image" (str, default "ubuntu-22.04-cuda-12.4-docker") — Verda image
    enum, NOT a Docker tag.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from .base import (
    AuthError,
    BidRejected,
    GpuType,
    NoCapacity,
    OutOfStock,
    Pod,
    PodStatus,
    Price,
    ProviderError,
    Spend,
    SpotSpec,
)

BASE = "https://api.verda.com"

# Status enum from OpenAPI: GetInstanceResponsePublicApiDto.status
_STATUS_RUNNING = {"running"}
_STATUS_PROVISIONING = {"provisioning", "validating", "new", "ordered"}
_STATUS_STOPPED = {"offline"}
_STATUS_TERMINAL = {"deleting", "notfound", "error", "installation_failed"}
# "discontinued" is the spot-preemption state on Verda.
_STATUS_DISCONTINUED = {"discontinued"}
_STATUS_NO_CAPACITY = {"no_capacity"}


class DataCrunchProvider:
    name = "datacrunch"
    supports_bid_auction = True
    supports_pause_preserve = True  # via configure_spot / volume retention policy
    preemption_signal = "hard-kill"
    billing_url = "https://cloud.verda.com/billing"

    def __init__(self, client_id: str | None = None, client_secret: str | None = None):
        cid = (client_id if client_id is not None else os.environ.get("DATACRUNCH_CLIENT_ID", "")).strip()
        csec = (client_secret if client_secret is not None else os.environ.get("DATACRUNCH_CLIENT_SECRET", "")).strip()
        if not cid or not csec:
            raise AuthError("DATACRUNCH_CLIENT_ID + DATACRUNCH_CLIENT_SECRET must be set")
        self.client_id = cid
        self.client_secret = csec
        self._token: str | None = None
        self._token_exp: float = 0.0  # epoch seconds; refresh when within 60s

    # ─── Auth: OAuth2 client_credentials ───────────────────────────────

    def _ensure_token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        body = json.dumps(
            {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{BASE}/v1/oauth2/token",
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                doc = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code in (400, 401, 403):
                raise AuthError(f"oauth2/token HTTP {e.code}: {detail}") from e
            raise ProviderError(f"oauth2/token HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise ProviderError(f"network: {e.reason}") from e
        token = doc.get("access_token")
        if not token:
            raise AuthError(f"oauth2/token returned no access_token: {doc}")
        self._token = token
        # expires_in is seconds; default to 1h if missing
        self._token_exp = time.time() + int(doc.get("expires_in") or 3600)
        return token

    def _req(self, method: str, path: str, body: dict[str, Any] | None = None, *, timeout: int = 30) -> Any:
        token = self._ensure_token()
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            f"{BASE}{path}",
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "rockie-datacrunch/0.1 (+https://github.com/saml212/rockie)",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            if e.code == 401:
                # Token expired or revoked; force re-auth on next call.
                self._token = None
                raise AuthError(f"HTTP 401: {detail}") from e
            if e.code == 402:
                raise AuthError(f"HTTP 402 (insufficient credit): {detail}") from e
            if e.code == 404:
                raise ProviderError(f"HTTP 404: {detail}") from e
            if e.code in (409, 503):
                raise NoCapacity(f"HTTP {e.code}: {detail}") from e
            raise ProviderError(f"HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise ProviderError(f"network: {e.reason}") from e
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProviderError(f"non-JSON response: {raw[:200]!r}") from e

    # ─── Provider interface ─────────────────────────────────────────────

    def auth(self) -> None:
        # Token mint is the auth probe.
        self._ensure_token()
        # Then a cheap GET to verify the bearer is accepted.
        self._req("GET", "/v1/balance")

    def list_gpus(self, grep: str | None = None) -> list[GpuType]:
        types = self._req("GET", "/v1/instance-types") or []
        out: list[GpuType] = []
        seen: set[str] = set()
        for t in types:
            model = t.get("model") or ""  # e.g. "H100"
            name = t.get("name") or t.get("display_name") or model  # "H100 SXM5 80GB"
            if not name:
                continue
            if name in seen:
                continue
            seen.add(name)
            mem = t.get("gpu_memory") or {}
            mem_gb = mem.get("size_in_gigabytes") if isinstance(mem, dict) else None
            out.append(GpuType(name=name, id=t.get("instance_type") or model, memory_gb=mem_gb))
        if grep:
            q = grep.lower()
            out = [g for g in out if q in g.name.lower() or q in g.id.lower()]
        return out

    def price(self, gpu_type: str, n: int = 1) -> Price:
        """gpu_type may be either an `instance_type` string ("1H100.80S.22V")
        or a model name ("H100"). We match either."""
        types = self._req("GET", "/v1/instance-types") or []
        # Filter to matching types. Prefer exact instance_type match;
        # fall back to model match scaled by `n`.
        candidates = [
            t for t in types
            if t.get("instance_type") == gpu_type or t.get("model") == gpu_type
        ]
        if not candidates:
            raise OutOfStock(f"no Verda instance_type matching {gpu_type!r}")
        # When matching by model, prefer the one whose GPU count == n.
        # When exact instance_type, gpu_count is already encoded in the type id.
        scored = []
        for t in candidates:
            gpu_count = (t.get("gpu") or {}).get("number_of_gpus") if isinstance(t.get("gpu"), dict) else None
            score = 0 if gpu_count == n else abs((gpu_count or n) - n)
            scored.append((score, t))
        scored.sort(key=lambda x: x[0])
        best = scored[0][1]

        # Verda surfaces price_per_hour (on-demand) and spot_price (floor).
        # Strings in the API; cast to float.
        on_demand = float(best.get("price_per_hour") or 0) or None
        spot = best.get("spot_price")
        spot_f = float(spot) if spot not in (None, "") else None

        # Stock requires a separate availability call.
        avail = self._req("GET", f"/v1/instance-availability?is_spot=true") or []
        stock = sum(
            1 for loc in avail
            if best["instance_type"] in (loc.get("availabilities") or [])
        )

        return Price(
            min_bid=spot_f,
            on_demand=on_demand,
            stock=stock,
            gpu_type_id=best["instance_type"],
        )

    def create_spot(self, spec: SpotSpec, *, yes: bool) -> Pod | None:
        if spec.bid is not None:
            # Verda spot is fixed-floor pricing, not bid auction. The
            # `bid` arg is informational only here; we don't pass it.
            pass

        # Pick a location with stock. Caller can pin via extras["location_code"].
        location = spec.extras.get("location_code") or spec.region
        if not location:
            avail = self._req("GET", "/v1/instance-availability?is_spot=true") or []
            for loc in avail:
                if spec.gpu_type in (loc.get("availabilities") or []):
                    location = loc.get("location_code")
                    break
            if not location:
                raise OutOfStock(f"no Verda location has spot {spec.gpu_type}")

        ssh_key_id = spec.ssh_key_id or os.environ.get("DATACRUNCH_SSH_KEY_ID", "")
        if not ssh_key_id:
            raise AuthError("DATACRUNCH_SSH_KEY_ID required (UUID of pre-registered key)")

        if not yes:
            return None  # dry-run

        body: dict[str, Any] = {
            "instance_type": spec.gpu_type,
            "image": spec.image or "ubuntu-22.04-cuda-12.4-docker",
            "ssh_key_ids": [ssh_key_id],
            "hostname": spec.name,
            "description": f"rockie-managed: {spec.name}",
            "location_code": location,
            "is_spot": True,
            "os_volume": {
                "name": f"{spec.name}-os",
                "size": spec.volume_gb,
                "on_spot_discontinue": spec.extras.get("on_spot_discontinue", "keep_detached"),
            },
        }
        resp = self._req("POST", "/v1/instances", body)
        # Response is the instance id (string) per the public API.
        instance_id = resp if isinstance(resp, str) else (resp or {}).get("id")
        if not instance_id:
            raise NoCapacity(f"create returned no id: {resp}")
        return Pod(
            id=str(instance_id),
            provider=self.name,
            status="CREATED",
            gpu_type=spec.gpu_type,
            gpu_count=spec.gpu_count,
            bid_per_gpu=None,  # Verda spot is fixed-floor; capture price on get_pod
            metadata={"location": location},
        )

    def list_pods(self) -> list[Pod]:
        rows = self._req("GET", "/v1/instances") or []
        return [self._row_to_pod(r) for r in rows]

    def get_pod(self, pod_id: str) -> Pod:
        r = self._req("GET", f"/v1/instances/{pod_id}")
        if not r or not r.get("id"):
            raise ProviderError(f"verda: instance {pod_id} not found")
        return self._row_to_pod(r)

    def stop(self, pod_id: str, *, yes: bool) -> None:
        if not yes:
            return
        self._req("PUT", "/v1/instances", {"action": "shutdown", "id": pod_id})

    def terminate(self, pod_id: str, *, yes: bool) -> None:
        if not yes:
            return
        # Delete with empty volume_ids = "delete pod, keep volumes" per
        # Verda's PUT semantics. Pass `delete_permanently: true` only if
        # caller wants nuke. Default keeps volume so spot data isn't lost
        # on accidental terminate.
        self._req("PUT", "/v1/instances", {"action": "delete", "id": pod_id})

    def resume(self, pod_id: str, *, yes: bool, bid: float | None = None) -> Pod:
        if not yes:
            return Pod(id=pod_id, provider=self.name, status="STOPPED")
        if bid is not None:
            import sys as _s
            print(
                f"[datacrunch] resume(bid={bid}) ignored — Verda spot is fixed-floor",
                file=_s.stderr,
            )
        self._req("PUT", "/v1/instances", {"action": "start", "id": pod_id})
        return self.get_pod(pod_id)

    def poll_once(self, pod_id: str) -> PodStatus:
        try:
            p = self.get_pod(pod_id)
        except ProviderError:
            return PodStatus(pod_id=pod_id, status="GONE", preempted=False)
        # On Verda, status=='discontinued' on a spot pod = preemption.
        raw = (p.metadata.get("verda_status") or "").lower()
        preempted = raw in _STATUS_DISCONTINUED and bool(p.metadata.get("is_spot"))
        return PodStatus(
            pod_id=pod_id,
            status=p.status,
            preempted=preempted,
            reason=f"verda_status={raw!r}" if preempted else None,
        )

    def current_spend(self) -> Spend:
        rows = self._req("GET", "/v1/instances") or []
        compute = 0.0
        running = 0
        idle_volume_gb = 0  # Verda doesn't surface volume size on the list endpoint
        for r in rows:
            status = (r.get("status") or "").lower()
            price = float(r.get("price_per_hour") or 0)
            if status in _STATUS_RUNNING:
                compute += price
                running += 1
        return Spend(
            provider=self.name,
            compute_per_hr=compute,
            storage_per_hr=0.0,  # Verda bundles storage into instance price
            cumulative_usd=0.0,  # filled by harness from gpu_pods.accrued_dollars
            running_pods=running,
            idle_volume_gb=idle_volume_gb,
        )

    # ─── Internal ───────────────────────────────────────────────────────

    def _row_to_pod(self, r: dict[str, Any]) -> Pod:
        raw = (r.get("status") or "").lower()
        if raw in _STATUS_RUNNING:
            status = "RUNNING"
        elif raw in _STATUS_PROVISIONING:
            status = "CREATED"
        elif raw in _STATUS_DISCONTINUED:
            status = "PREEMPTED" if r.get("is_spot") else "STOPPED"
        elif raw in _STATUS_STOPPED:
            status = "STOPPED"
        elif raw in _STATUS_NO_CAPACITY:
            status = "EXITED"
        elif raw in _STATUS_TERMINAL:
            status = "TERMINATED" if raw in ("deleting", "notfound") else "EXITED"
        else:
            status = (raw or "?").upper()

        ip = r.get("ip")
        ssh_ep = f"ssh root@{ip} -p 22" if ip else None
        # Note: Verda's default SSH user is "root" on Ubuntu cloud images;
        # if the user customizes the image, this may need to change.

        return Pod(
            id=str(r["id"]),
            provider=self.name,
            status=status,
            ssh_endpoint=ssh_ep,
            gpu_type=r.get("instance_type"),
            gpu_count=int((r.get("gpu") or {}).get("number_of_gpus") or 1) if isinstance(r.get("gpu"), dict) else 1,
            metadata={
                "location": r.get("location"),
                "is_spot": bool(r.get("is_spot")),
                "verda_status": raw,
                "price_per_hour": r.get("price_per_hour"),
            },
        )
