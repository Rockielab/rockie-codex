"""On-demand-only provider — supports_bid_auction=False. Router should
include it only when --allow-on-demand is set."""
from providers.base import (  # noqa
    GpuType, Pod, PodStatus, Price, Spend, SpotSpec,
)


class FakeOnDemandProvider:
    name = "fake-ondemand"
    supports_bid_auction = False
    supports_pause_preserve = False
    preemption_signal = "none"
    billing_url = "https://example.invalid/ondemand"

    def auth(self): pass
    def list_gpus(self, grep=None):
        return [GpuType(name="FakeOnDemandH100", id="fake-od-h100", memory_gb=80)]
    def price(self, gpu_type, n=1):
        return Price(min_bid=5.0, on_demand=5.0, stock=10, gpu_type_id=gpu_type)
    def create_spot(self, spec, *, yes):
        if not yes:
            return None
        return Pod(
            id=f"fake-ondemand-pod-{spec.gpu_type}",
            provider=self.name,
            status="CREATED",
            gpu_type=spec.gpu_type,
            gpu_count=spec.gpu_count,
            bid_per_gpu=spec.bid or 5.0,
            ssh_endpoint="ssh root@10.0.0.2 -p 22",
        )
    def list_pods(self): return []
    def get_pod(self, pod_id):
        return Pod(id=pod_id, provider=self.name, status="RUNNING")
    def stop(self, pod_id, *, yes): pass
    def terminate(self, pod_id, *, yes): pass
    def resume(self, pod_id, *, yes, bid=None):
        return Pod(id=pod_id, provider=self.name, status="RUNNING")
    def poll_once(self, pod_id): return PodStatus(pod_id=pod_id, status="RUNNING")
    def current_spend(self):
        return Spend(provider=self.name, compute_per_hr=5.0, storage_per_hr=0.0,
                     cumulative_usd=0.0, running_pods=1, idle_volume_gb=0)
