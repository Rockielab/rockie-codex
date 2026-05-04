"""providers/runpod.py — RunPod adapter conforming to providers.base.Provider.

Pure API: every method takes typed input, returns dataclasses, and raises
from the providers.base exception hierarchy. State writes (gpu_pods,
budget_usage, .state stamps) live in the harness layer (scripts/runpod.py
today; scripts/gpu.py once commit 7 lifts the reconcile loop).

The asymmetry to remember:
  * create_spot(bid=None) means "use current minimumBidPrice for this gpu_type"
  * resume(bid=None) means "on-demand resume" (RunPod has two literal
    endpoints, podResume and podBidResume)
Each is documented on the method. Don't conflate them.

extras keys this adapter reads from SpotSpec.extras:
  * "secure" (bool, default False) — restrict to SECURE-cloud datacenters
  * "min_vcpu" (int, default 4)
  * "min_ram" (int, default 16)
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

API_URL = "https://api.runpod.io/graphql"


class RunPodProvider:
    name = "runpod"
    supports_bid_auction = True
    supports_pause_preserve = True
    preemption_signal = "hard-kill"
    billing_url = "https://www.runpod.io/console/user/billing"

    def __init__(self, api_key: str | None = None):
        key = (api_key if api_key is not None else os.environ.get("RUNPOD_API_KEY", "")).strip()
        if not key:
            raise AuthError("RUNPOD_API_KEY not set")
        self.api_key = key

    # ─── HTTP ──────────────────────────────────────────────────────────

    def _gql(self, query: str, *, timeout: int = 30) -> dict[str, Any]:
        url = f"{API_URL}?api_key={self.api_key}"
        payload = json.dumps({"query": query}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "content-type": "application/json",
                # RunPod sits behind Cloudflare; default urllib UA gets a
                # 1010 access-denied. Identifying like a real client gets
                # through. (Curl works because its default UA is allowed.)
                "user-agent": "rockie-runpod/0.2 (+https://github.com/saml212/rockie)",
                "accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            if e.code == 401:
                raise AuthError(f"HTTP 401: {detail}") from e
            raise ProviderError(f"HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise ProviderError(f"network: {e.reason}") from e

        if "errors" in body:
            msgs = "; ".join(e.get("message", "") for e in body["errors"])
            if "unauthor" in msgs.lower():
                raise AuthError(msgs)
            raise ProviderError(f"GraphQL: {msgs}")
        return body.get("data") or {}

    # ─── Provider interface ─────────────────────────────────────────────

    def auth(self) -> None:
        d = self._gql("query { myself { id email } }")
        me = d.get("myself") or {}
        if not me.get("id"):
            raise AuthError("empty myself response — key may be invalid")

    def list_gpus(self, grep: str | None = None) -> list[GpuType]:
        d = self._gql("query { gpuTypes { id displayName memoryInGb } }")
        rows = d.get("gpuTypes") or []
        if grep:
            q = grep.lower()
            rows = [
                r
                for r in rows
                if q in (r.get("displayName") or "").lower()
                or q in (r.get("id") or "").lower()
            ]
        return [
            GpuType(name=r.get("displayName") or r["id"], id=r["id"], memory_gb=r.get("memoryInGb"))
            for r in rows
        ]

    def price(self, gpu_type: str, n: int = 1) -> Price:
        q = f'''
            query {{
              gpuTypes(input: {{ id: "{gpu_type}" }}) {{
                id displayName memoryInGb
                lowestPrice(input: {{ gpuCount: {n} }}) {{
                  stockStatus minimumBidPrice uninterruptablePrice availableGpuCounts
                }}
              }}
            }}
        '''
        d = self._gql(q)
        types = d.get("gpuTypes") or []
        if not types:
            raise OutOfStock(f"no GPU type matching {gpu_type!r}")
        p = types[0].get("lowestPrice") or {}
        avail = p.get("availableGpuCounts") or []
        if not avail and not p.get("minimumBidPrice"):
            raise OutOfStock(f"{gpu_type}: stockStatus={p.get('stockStatus')!r}, no available counts")
        return Price(
            min_bid=float(p["minimumBidPrice"]) if p.get("minimumBidPrice") is not None else None,
            on_demand=float(p["uninterruptablePrice"]) if p.get("uninterruptablePrice") is not None else None,
            stock=len(avail),
            gpu_type_id=gpu_type,
        )

    def create_spot(self, spec: SpotSpec, *, yes: bool) -> Pod | None:
        bid = spec.bid
        if bid is None:
            pr = self.price(spec.gpu_type, spec.gpu_count)
            if pr.min_bid is None:
                raise BidRejected(f"no minimumBidPrice for {spec.gpu_type}")
            bid = pr.min_bid
        if not yes:
            return None  # dry-run

        secure = bool(spec.extras.get("secure", False))
        min_vcpu = int(spec.extras.get("min_vcpu", 4))
        min_ram = int(spec.extras.get("min_ram", 16))
        image = spec.image or "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04"

        env_pairs = ""
        if spec.env:
            env_json = ", ".join(
                f'{{ key: "{k}", value: "{v}" }}' for k, v in spec.env.items()
            )
            env_pairs = f", env: [{env_json}]"

        mut = f'''
            mutation {{
              podRentInterruptable(input: {{
                bidPerGpu: {bid}
                cloudType: {"SECURE" if secure else "ALL"}
                gpuCount: {spec.gpu_count}
                volumeInGb: {spec.volume_gb}
                containerDiskInGb: {spec.disk_gb}
                minVcpuCount: {min_vcpu}
                minMemoryInGb: {min_ram}
                gpuTypeId: "{spec.gpu_type}"
                name: "{spec.name}"
                imageName: "{image}"
                dockerArgs: ""
                ports: "22/tcp"
                volumeMountPath: "/workspace"
                {env_pairs}
              }}) {{
                id imageName machineId machine {{ podHostId }}
              }}
            }}
        '''
        d = self._gql(mut)
        pod = d.get("podRentInterruptable") or {}
        if not pod.get("id"):
            raise NoCapacity("podRentInterruptable returned empty id")
        return Pod(
            id=pod["id"],
            provider=self.name,
            status="CREATED",
            gpu_type=spec.gpu_type,
            gpu_count=spec.gpu_count,
            bid_per_gpu=bid,
        )

    def list_pods(self) -> list[Pod]:
        d = self._gql(
            """
            query { myself { pods {
              id name desiredStatus
              runtime { uptimeInSeconds ports { ip privatePort publicPort } }
            } } }
            """
        )
        rows = (d.get("myself") or {}).get("pods") or []
        return [self._row_to_pod(r) for r in rows]

    def get_pod(self, pod_id: str) -> Pod:
        d = self._gql(
            f'query {{ pod(input: {{podId: "{pod_id}"}}) {{ '
            "id name desiredStatus imageName "
            "runtime { uptimeInSeconds ports { ip privatePort publicPort } } } }"
        )
        p = d.get("pod")
        if not p:
            raise ProviderError(f"pod {pod_id} not found")
        return self._row_to_pod(p)

    def stop(self, pod_id: str, *, yes: bool) -> None:
        if not yes:
            return
        d = self._gql(f'mutation {{ podStop(input: {{podId: "{pod_id}"}}) {{ id desiredStatus }} }}')
        if not (d.get("podStop") or {}).get("id"):
            raise ProviderError(f"podStop failed for {pod_id}")

    def terminate(self, pod_id: str, *, yes: bool) -> None:
        if not yes:
            return
        # podTerminate returns null on success; errors raise via _gql
        self._gql(f'mutation {{ podTerminate(input: {{podId: "{pod_id}"}}) }}')

    def resume(self, pod_id: str, *, yes: bool, bid: float | None = None) -> Pod:
        """bid=None → on-demand resume (podResume); bid=N → spot (podBidResume).

        Asymmetric with create_spot intentionally: RunPod has two distinct
        endpoints and the choice is meaningful at resume time.
        """
        if not yes:
            return Pod(id=pod_id, provider=self.name, status="STOPPED")
        if bid is None:
            mut = (
                f'mutation {{ podResume(input: {{podId: "{pod_id}", '
                f"gpuCount: 1 }}) {{ id desiredStatus imageName }} }}"
            )
            field_name = "podResume"
        else:
            mut = (
                f'mutation {{ podBidResume(input: {{podId: "{pod_id}", '
                f"bidPerGpu: {bid}, gpuCount: 1 }}) "
                "{ id desiredStatus imageName } }"
            )
            field_name = "podBidResume"
        d = self._gql(mut)
        pod = d.get(field_name) or {}
        if not pod.get("id"):
            raise ProviderError(f"resume failed for {pod_id}")
        return Pod(
            id=pod["id"],
            provider=self.name,
            status=pod.get("desiredStatus") or "RUNNING",
        )

    def poll_once(self, pod_id: str) -> PodStatus:
        p = self.get_pod(pod_id)
        # The harness owns the "expected lifetime" comparison (it knows
        # when create() was called); we only report observable status.
        # An EXITED pod with no SSH port is preempted-or-failed; the
        # caller decides which based on its own timeline.
        preempted = p.status in ("EXITED", "TERMINATED") and p.ssh_endpoint is None
        return PodStatus(pod_id=pod_id, status=p.status, preempted=preempted)

    def current_spend(self) -> Spend:
        """Live snapshot. Does NOT include cumulative_usd — that's read
        from gpu_pods.accrued_dollars by the harness, which owns the SQL.
        """
        d = self.fetch_live_state()
        me = d.get("myself") or {}
        pods = me.get("pods") or []
        volumes = me.get("networkVolumes") or []

        compute_per_hr = 0.0
        idle_volume_gb = 0
        running = 0
        for p in pods:
            cph = float(p.get("costPerHr") or 0)
            gb = int(p.get("volumeInGb") or 0)
            if p.get("desiredStatus") == "RUNNING":
                compute_per_hr += cph
                running += 1
            else:
                idle_volume_gb += gb
        idle_volume_gb += sum(int(v.get("size") or 0) for v in volumes)

        # Public RunPod storage rate: ~$0.10/GB/month for container/network
        # storage. Not authoritative — billing page is the source of truth.
        storage_per_hr = idle_volume_gb * (0.10 / 30 / 24)

        return Spend(
            provider=self.name,
            compute_per_hr=compute_per_hr,
            storage_per_hr=storage_per_hr,
            cumulative_usd=0.0,  # filled in by harness from gpu_pods
            running_pods=running,
            idle_volume_gb=idle_volume_gb,
        )

    # ─── Helpers used by harness reconcile ──────────────────────────────

    def fetch_live_state(self) -> dict[str, Any]:
        """Raw {myself: {pods, networkVolumes}} for cross-referencing
        against gpu_pods rows during reconcile. Lets the harness do one
        round-trip per provider per reconcile pass.
        """
        return (
            self._gql(
                """
                query { myself {
                  networkVolumes { id name size dataCenterId }
                  pods { id name desiredStatus volumeInGb costPerHr
                         runtime { uptimeInSeconds } }
                } }
                """
            )
            or {}
        )

    # ─── Internal ───────────────────────────────────────────────────────

    def _row_to_pod(self, r: dict[str, Any]) -> Pod:
        rt = r.get("runtime") or {}
        ports = rt.get("ports") or []
        ssh = next((x for x in ports if x.get("privatePort") == 22), None)
        ssh_ep = (
            f'ssh root@{ssh["ip"]} -p {ssh["publicPort"]}'
            if ssh and ssh.get("ip") and ssh.get("publicPort")
            else None
        )
        return Pod(
            id=r["id"],
            provider=self.name,
            status=r.get("desiredStatus") or "?",
            ssh_endpoint=ssh_ep,
        )
