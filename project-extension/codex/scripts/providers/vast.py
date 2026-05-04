"""providers/vast.py — Vast.ai adapter conforming to providers.base.Provider.

Pure API: no SQL, no budget writes; the harness (scripts/runpod.py today,
scripts/gpu.py once commit 7 lands) owns those.

Vast specifics worth knowing if you're reading this for the first time:

  * **No GPU-type catalog.** Unlike RunPod's gpuTypes endpoint, Vast doesn't
    expose a clean enumeration of GPU types. We synthesize GpuType objects
    by deduping `gpu_name` across the offer search results. `list_gpus()`
    reflects what's currently rentable, not a Platonic catalog.
  * **Offer-id is the live unit.** A `price()` snapshot returns the
    *current cheapest* min_bid; `create_spot()` re-searches at submit time
    and picks a fresh offer_id. Don't cache offer_ids — they disappear.
  * **`reliability >= 0.95` is mandatory.** Vast aggregates rentals from
    individual hosts of varying quality; without the filter you get
    preempted by host misbehavior, not by the market. This is the #1
    complaint in vast-python issues.
  * **`cancel_unavail: true` is mandatory.** Without it, a failed-to-start
    instance bills you "queued" hours until you manually destroy it.
  * **Paused != free.** When outbid, Vast pauses the instance (preserves
    disk) but you keep paying the storage rate (~$0.10/GB/month). The
    adapter exposes both `stop` (pause-preserve) and `terminate` (delete
    — final). The harness should prefer terminate when the user signals
    "done" rather than "pause."
  * **No new bid on resume.** Vast's PUT /instances/{id}/ with
    {"state":"running"} doesn't accept a fresh bid; it uses whatever the
    instance was created with. The Provider's `resume(bid=...)` arg is
    ignored on Vast, with a warning if set. (Asymmetric with RunPod where
    bid IS meaningful on resume.)

extras keys this adapter reads from SpotSpec.extras:
  * "reliability_min" (float, default 0.95) — host-quality floor
  * "verified_only" (bool, default True) — restrict to Vast-verified hosts
"""
from __future__ import annotations

import json
import os
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

BASE = "https://console.vast.ai/api/v0"

# ─── Vast error codes that map to our taxonomy ─────────────────────────────
# Vast returns 200 OK with {"success": false, "error": "<code>", "msg": ...}
# for many failure modes; the HTTP code alone doesn't distinguish them.
_AUTH_ERR_CODES = frozenset({"insufficient_credit", "billing_required"})
_NOCAPACITY_CODES = frozenset({"no_such_ask", "no_capacity", "machine_unavailable"})
_BID_CODES = frozenset({"bid_too_low", "bid_rejected"})


class VastProvider:
    name = "vast"
    supports_bid_auction = True
    supports_pause_preserve = True
    preemption_signal = "hard-kill"
    billing_url = "https://cloud.vast.ai/billing/"

    def __init__(self, api_key: str | None = None):
        key = (api_key if api_key is not None else os.environ.get("VAST_API_KEY", "")).strip()
        if not key:
            raise AuthError("VAST_API_KEY not set")
        self.api_key = key

    # ─── HTTP ──────────────────────────────────────────────────────────

    def _req(self, method: str, path: str, body: dict[str, Any] | None = None, *, timeout: int = 30) -> dict[str, Any]:
        url = f"{BASE}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "rockie-vast/0.1 (+https://github.com/saml212/rockie)",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                http_code = resp.status
        except urllib.error.HTTPError as e:
            # Vast often returns 4xx with the SAME success=false body shape
            # as 200-with-error. Parse + route through the same taxonomy
            # so the router can hop on no_such_ask, etc., instead of
            # treating them as opaque ProviderErrors.
            raw = e.read().decode("utf-8", "replace")
            self._raise_from_body(raw, http_code=e.code)
            # If raise_from_body didn't recognize the shape, raise generic.
            if e.code == 401:
                raise AuthError(f"HTTP 401: {raw[:400]}") from e
            raise ProviderError(f"HTTP {e.code}: {raw[:400]}") from e
        except urllib.error.URLError as e:
            raise ProviderError(f"network: {e.reason}") from e

        if not raw:
            return {}
        self._raise_from_body(raw, http_code=http_code)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProviderError(f"non-JSON response: {raw[:200]!r}") from e

    def _raise_from_body(self, raw: str, *, http_code: int) -> None:
        """If `raw` parses as a Vast error envelope ({"success": false, ...}),
        raise from our taxonomy. Otherwise return — caller continues normal
        processing. Centralized so HTTPError 4xx bodies and 200 bodies share
        the same mapping."""
        try:
            doc = json.loads(raw)
        except (ValueError, json.JSONDecodeError):
            return
        if not isinstance(doc, dict) or doc.get("success") is not False:
            return
        err = (doc.get("error") or "").strip()
        msg = doc.get("msg") or err or "vast: unknown error"
        if err in _AUTH_ERR_CODES:
            raise AuthError(f"{err}: {msg}")
        if err in _NOCAPACITY_CODES:
            raise NoCapacity(f"{err}: {msg}")
        if err in _BID_CODES:
            raise BidRejected(f"{err}: {msg}")
        raise ProviderError(f"vast: HTTP {http_code} {err or 'unknown'}: {msg}")

    # ─── Provider interface ─────────────────────────────────────────────

    def auth(self) -> None:
        d = self._req("GET", "/users/current/")
        if not d.get("id"):
            raise AuthError("/users/current/ returned no id")

    def list_gpus(self, grep: str | None = None) -> list[GpuType]:
        offers = self._search_offers({"limit": 500, "order": [["min_bid", "asc"]]})
        names: dict[str, dict[str, Any]] = {}
        for o in offers:
            n = o.get("gpu_name")
            if not n:
                continue
            if n not in names:
                names[n] = o
        out = []
        for name, sample in sorted(names.items()):
            mem_mb = sample.get("gpu_ram") or 0
            mem_gb = int(mem_mb // 1024) if mem_mb else None
            out.append(GpuType(name=name, id=name, memory_gb=mem_gb))
        if grep:
            q = grep.lower()
            out = [g for g in out if q in g.name.lower()]
        return out

    def price(self, gpu_type: str, n: int = 1) -> Price:
        offers = self._search_offers({
            "gpu_name": {"eq": gpu_type},
            "num_gpus": {"eq": n},
            "order": [["min_bid", "asc"]],
            "limit": 20,
        })
        if not offers:
            raise OutOfStock(f"no {gpu_type} ×{n} offers on vast")
        min_bid = min(float(o["min_bid"]) for o in offers if o.get("min_bid") is not None)
        on_demand = min(float(o["dph_total"]) for o in offers if o.get("dph_total") is not None)
        return Price(
            min_bid=min_bid,
            on_demand=on_demand,
            stock=len(offers),
            gpu_type_id=gpu_type,
        )

    def create_spot(self, spec: SpotSpec, *, yes: bool) -> Pod | None:
        # Re-search at submit time — offers disappear.
        offers = self._search_offers({
            "gpu_name": {"eq": spec.gpu_type},
            "num_gpus": {"eq": spec.gpu_count},
            "order": [["min_bid", "asc"]],
            "limit": 1,
        }, extras=spec.extras)
        if not offers:
            raise OutOfStock(f"no {spec.gpu_type} ×{spec.gpu_count} offers")
        offer = offers[0]
        offer_id = offer["id"]
        min_bid = float(offer.get("min_bid") or 0)

        bid = spec.bid if spec.bid is not None else min_bid
        if bid < min_bid:
            raise BidRejected(f"bid ${bid} below min ${min_bid} for offer {offer_id}")

        if not yes:
            return None

        body = {
            "image": spec.image or "pytorch/pytorch:2.4.0-cuda12.4-cudnn9-devel",
            "disk": spec.volume_gb,
            "runtype": "ssh",
            "price": bid,
            "target_state": "running",
            "label": spec.name,
            "cancel_unavail": True,  # mandatory — see module docstring
        }
        if spec.env:
            # Vast's `env` is a flag string, not a dict. Encoded as
            # "-e KEY=VAL -e KEY2=VAL2" per /asks/ docs.
            body["env"] = " ".join(f'-e {k}={v}' for k, v in spec.env.items())

        r = self._req("PUT", f"/asks/{offer_id}/", body)
        if not r.get("success"):
            # Defensive — _req normalizes most cases, but PUT /asks/ has been
            # known to return success=true with a non-numeric new_contract.
            raise NoCapacity(f"asks PUT failed: {r}")
        contract_id = r.get("new_contract")
        if not contract_id:
            raise NoCapacity(f"asks PUT returned no new_contract: {r}")
        return Pod(
            id=str(contract_id),
            provider=self.name,
            status="CREATED",
            gpu_type=spec.gpu_type,
            gpu_count=spec.gpu_count,
            bid_per_gpu=bid,
            metadata={"offer_id": offer_id, "machine_id": offer.get("machine_id")},
        )

    def list_pods(self) -> list[Pod]:
        d = self._req("GET", "/instances/")
        rows = d.get("instances") or []
        return [self._row_to_pod(r) for r in rows]

    def get_pod(self, pod_id: str) -> Pod:
        d = self._req("GET", f"/instances/{pod_id}/")
        # Vast wraps it as {"instances": {...}} for single-id GETs in the
        # current API — but historically also returns the bare object.
        # Normalize.
        inst = d.get("instances") if isinstance(d.get("instances"), dict) else d
        if not inst or not inst.get("id"):
            raise ProviderError(f"vast: instance {pod_id} not found")
        return self._row_to_pod(inst)

    def stop(self, pod_id: str, *, yes: bool) -> None:
        if not yes:
            return
        self._req("PUT", f"/instances/{pod_id}/", {"state": "stopped"})

    def terminate(self, pod_id: str, *, yes: bool) -> None:
        if not yes:
            return
        self._req("DELETE", f"/instances/{pod_id}/")

    def resume(self, pod_id: str, *, yes: bool, bid: float | None = None) -> Pod:
        if not yes:
            return Pod(id=pod_id, provider=self.name, status="STOPPED")
        if bid is not None:
            # Vast doesn't accept a new bid on resume; it uses whatever
            # the instance was created with. Document and ignore.
            import sys as _s
            print(
                f"[vast] resume(bid={bid}) ignored — Vast resumes at original bid",
                file=_s.stderr,
            )
        self._req("PUT", f"/instances/{pod_id}/", {"state": "running"})
        return self.get_pod(pod_id)

    def poll_once(self, pod_id: str) -> PodStatus:
        d = self._req("GET", f"/instances/{pod_id}/")
        inst = d.get("instances") if isinstance(d.get("instances"), dict) else d
        if not inst:
            return PodStatus(pod_id=pod_id, status="GONE", preempted=False)
        actual = (inst.get("actual_status") or "").lower()
        intended = (inst.get("intended_status") or "").lower()
        # Preemption signal: user wanted RUNNING but Vast paused/exited it.
        # See spec §A.7: this mismatch is the only signal Vast gives us
        # short of the disk-preserved bit.
        preempted = intended == "running" and actual in ("stopped", "exited")
        status = "RUNNING" if actual == "running" else (
            "EXITED" if actual == "exited" else
            "STOPPED" if actual == "stopped" else
            actual.upper() or "?"
        )
        return PodStatus(
            pod_id=pod_id,
            status=status,
            preempted=preempted,
            reason=f"actual={actual!r} intended={intended!r}" if preempted else None,
        )

    def current_spend(self) -> Spend:
        d = self._req("GET", "/instances/")
        rows = d.get("instances") or []
        compute_per_hr = 0.0
        storage_per_hr = 0.0
        running = 0
        idle_volume_gb = 0
        for r in rows:
            actual = (r.get("actual_status") or "").lower()
            disk_gb = int(r.get("disk_space") or 0)
            dph = float(r.get("dph_total") or 0)
            if actual == "running":
                compute_per_hr += dph
                running += 1
            else:
                idle_volume_gb += disk_gb
                # storage_total_cost is $/hr already on most rows
                storage_per_hr += float(r.get("storage_total_cost") or 0)
        return Spend(
            provider=self.name,
            compute_per_hr=compute_per_hr,
            storage_per_hr=storage_per_hr,
            cumulative_usd=0.0,  # filled by harness from gpu_pods.accrued_dollars
            running_pods=running,
            idle_volume_gb=idle_volume_gb,
        )

    # ─── Internal ───────────────────────────────────────────────────────

    def _search_offers(self, query: dict[str, Any], *, extras: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """POST /bundles/ with the search query, applying our defaults
        (rentable, verified, reliability >= 0.95). Caller's `query` is
        merged on top — caller can override any default by setting a key.
        """
        rel_min = 0.95
        verified_only = True
        if extras:
            rel_min = float(extras.get("reliability_min", rel_min))
            verified_only = bool(extras.get("verified_only", verified_only))

        body: dict[str, Any] = {
            "type": "bid",
            "rentable": {"eq": True},
            "reliability": {"gte": rel_min},
        }
        if verified_only:
            body["verified"] = {"eq": True}
        body.update(query)
        d = self._req("POST", "/bundles/", body)
        return d.get("offers") or []

    def _row_to_pod(self, r: dict[str, Any]) -> Pod:
        actual = (r.get("actual_status") or "").lower()
        intended = (r.get("intended_status") or "").lower()
        if actual == "running":
            status = "RUNNING"
        elif actual == "exited":
            status = "PREEMPTED" if intended == "running" else "EXITED"
        elif actual == "stopped":
            status = "PREEMPTED" if intended == "running" else "STOPPED"
        else:
            status = (actual or "?").upper()
        ssh_host = r.get("ssh_host") or r.get("public_ipaddr")
        ssh_port = r.get("ssh_port")
        ssh_ep = (
            f"ssh root@{ssh_host} -p {ssh_port}"
            if ssh_host and ssh_port
            else None
        )
        return Pod(
            id=str(r["id"]),
            provider=self.name,
            status=status,
            ssh_endpoint=ssh_ep,
            gpu_type=r.get("gpu_name"),
            gpu_count=int(r.get("num_gpus") or 1),
            metadata={
                "machine_id": r.get("machine_id"),
                "geolocation": r.get("geolocation"),
                "actual_status": actual,
                "intended_status": intended,
            },
        )
