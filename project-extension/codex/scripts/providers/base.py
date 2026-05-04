"""providers/base.py — the Protocol every GPU provider adapter implements.

rockie is an autonomous-run harness: the agent provisions GPUs without a
human in the loop. Budget enforcement only works if every provider the
agent can spend on reports its costs through one uniform shape. This file
defines that shape.

Design rules every concrete adapter must follow:

  * **Pure API.** An adapter takes params and returns dataclasses; it does
    NOT write SQL, does NOT touch budget_usage, does NOT sys.exit. The
    harness layer (scripts/gpu.py, eventually) owns state and budget. This
    is what lets the router compose multiple providers cleanly and lets
    tests inject fakes.
  * **Honest flags.** supports_bid_auction / supports_pause_preserve /
    preemption_signal drive routing decisions and on-demand gating. Lying
    about them turns the router into a bug factory.
  * **billing_url.** Surfaced by `gpu.py dashboard` and `gpu.py cost` so
    humans can verify the harness's accounting against the provider's own
    UI in one click. Required.
  * **Raise from the hierarchy below.** The router catches AuthError /
    OutOfStock / BidRejected / NoCapacity to decide whether to hop, retry,
    or abort. Anything else escapes as a real error.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable


# ─── Exceptions ─────────────────────────────────────────────────────────────


class ProviderError(Exception):
    """Base for all provider-adapter errors."""


class AuthError(ProviderError):
    """Key missing/invalid, or billing not set up.

    Terminal for THIS provider (router skips it for the rest of the call)
    but the router continues to other providers — different env vars may
    still be valid.
    """


class OutOfStock(ProviderError):
    """Provider returned zero capacity for the requested gpu_type/count.

    Structural: nothing the caller can do except hop. Router moves on.
    """


class BidRejected(ProviderError):
    """Bid below the provider's current floor, or no spot tier available.

    Transient — caller could retry with a higher bid, but per the harness
    convention we hop providers instead of bumping bids (bumping doesn't
    meaningfully reduce preemption risk on blind-auction schedulers).
    """


class NoCapacity(ProviderError):
    """Transient capacity error (offer disappeared mid-create, cloud 409).

    Router may retry once on the same provider, then hops.
    """


# ─── Dataclasses ────────────────────────────────────────────────────────────
# Uniform shapes the router and dashboard read. Providers translate their
# native JSON into these; nothing downstream sees provider-specific keys.


@dataclass(frozen=True)
class GpuType:
    """A GPU type a provider offers.

    `id` is the provider's native identifier (e.g. "NVIDIA H100 80GB HBM3"
    on RunPod, "H100_SXM" on Vast, "H100_80GB" on Prime). Pass it back
    verbatim to price() / create_spot() — providers parse their own.
    """

    name: str
    id: str
    memory_gb: int | None = None


@dataclass(frozen=True)
class Price:
    """Snapshot price for a gpu_type at a point in time.

    Either tier may be None: Prime returns min_bid=None when no spot
    row exists for the requested type. On-demand-only providers (if
    any are added later) would set min_bid==on_demand.

    `gpu_type_id` carries whatever the provider's create_spot() needs to
    re-fetch — may be the raw gpu_type, an opaque offer_id (Vast), or a
    cloudId (Prime). Treat as opaque downstream.
    """

    min_bid: float | None
    on_demand: float | None
    stock: int
    gpu_type_id: str
    region: str | None = None


@dataclass
class SpotSpec:
    """Create-pod request passed to Provider.create_spot().

    `extras` carries provider-specific knobs that don't generalize across
    the fleet — e.g. RunPod's `secure` (SECURE-cloud filter) and
    `min_vcpu`/`min_ram`, Vast's `reliability_min`, TensorDock's
    `bid_per_vm`. Each adapter documents the keys it reads from extras.
    Keeps the shared shape clean while letting power users hit
    provider-specific levers without a Protocol bump.
    """

    gpu_type: str
    gpu_count: int = 1
    volume_gb: int = 40
    disk_gb: int = 40
    bid: float | None = None  # None → adapter uses provider's current min
    image: str = ""  # provider-default if empty
    name: str = "rockie-spot"
    ssh_key_id: str | None = None  # required by Prime; some others optional
    region: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class Pod:
    """A provisioned pod.

    `id` is unique within a provider, NOT globally — always pair with
    `provider` when persisting. `metadata` is provider-specific extras
    (e.g. Vast stashes machine_id and geolocation there).
    """

    id: str
    provider: str
    status: str = "CREATED"
    # Status vocab (uniform across providers):
    #   CREATED | RUNNING | STOPPED | EXITED | TERMINATED | PREEMPTED | GONE
    ssh_endpoint: str | None = None
    gpu_type: str | None = None
    gpu_count: int = 1
    bid_per_gpu: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PodStatus:
    """Lightweight polling result from poll_once().

    Used by the autopilot's preemption-detection loop. `preempted=True`
    triggers a preemption_events row write and (for spot tiers) a router
    hop on the next create.
    """

    pod_id: str
    status: str
    preempted: bool = False
    reason: str | None = None


@dataclass
class Spend:
    """Normalized live-spend snapshot. The harness SUMs these across every
    configured provider for the dashboard and the budget reconcile.

    compute_per_hr — sum of $/hr for all RUNNING pods on this provider.
    storage_per_hr — sum of idle-volume rates (paying-but-not-running).
    cumulative_usd — best-effort total spent on this provider since first
                     pod was provisioned. Read from gpu_pods.accrued_dollars
                     filtered to provider, not from a provider-side
                     billing API (most don't expose it cleanly).
    """

    provider: str
    compute_per_hr: float
    storage_per_hr: float
    cumulative_usd: float
    running_pods: int
    idle_volume_gb: int = 0


# ─── Protocol ───────────────────────────────────────────────────────────────


@runtime_checkable
class Provider(Protocol):
    """Contract every adapter implements. See module docstring for design rules."""

    name: str  # short slug: "runpod", "vast", "prime", ...
    supports_bid_auction: bool  # True if a spot/bid tier exists
    supports_pause_preserve: bool  # True if stop() preserves volume on this provider
    preemption_signal: Literal["none", "warning-secs", "hard-kill"]
    billing_url: str  # human-visible billing page; surfaced in dashboard

    def auth(self) -> None: ...
    def list_gpus(self, grep: str | None = None) -> list[GpuType]: ...
    def price(self, gpu_type: str, n: int = 1) -> Price: ...
    def create_spot(self, spec: SpotSpec, *, yes: bool) -> Pod | None: ...
    def list_pods(self) -> list[Pod]: ...
    def get_pod(self, pod_id: str) -> Pod: ...
    def stop(self, pod_id: str, *, yes: bool) -> None: ...
    def terminate(self, pod_id: str, *, yes: bool) -> None: ...
    def resume(self, pod_id: str, *, yes: bool, bid: float | None = None) -> Pod: ...
    def poll_once(self, pod_id: str) -> PodStatus: ...
    def current_spend(self) -> Spend: ...
