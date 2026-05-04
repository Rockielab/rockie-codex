"""Successful spot provider — the router should land here when others fail."""
from providers.base import (  # noqa
    GpuType, Pod, PodStatus, Price, Spend, SpotSpec,
)


class FakeOKProvider:
    name = "fake-ok"
    supports_bid_auction = True
    supports_pause_preserve = True
    preemption_signal = "hard-kill"
    billing_url = "https://example.invalid/ok"

    def auth(self): pass
    def list_gpus(self, grep=None):
        return [GpuType(name="FakeH100", id="fake-h100", memory_gb=80)]
    def price(self, gpu_type, n=1):
        return Price(min_bid=1.0, on_demand=2.0, stock=5, gpu_type_id=gpu_type)
    def create_spot(self, spec, *, yes):
        if not yes:
            return None
        return Pod(
            id=f"fake-ok-pod-{spec.gpu_type}",
            provider=self.name,
            status="CREATED",
            gpu_type=spec.gpu_type,
            gpu_count=spec.gpu_count,
            bid_per_gpu=spec.bid or 1.0,
            ssh_endpoint="ssh root@10.0.0.1 -p 22",
        )
    def list_pods(self): return []
    def get_pod(self, pod_id):
        return Pod(id=pod_id, provider=self.name, status="RUNNING",
                   ssh_endpoint="ssh root@10.0.0.1 -p 22")
    def stop(self, pod_id, *, yes): pass
    def terminate(self, pod_id, *, yes): pass
    def resume(self, pod_id, *, yes, bid=None):
        return Pod(id=pod_id, provider=self.name, status="RUNNING")
    def poll_once(self, pod_id): return PodStatus(pod_id=pod_id, status="RUNNING")
    def current_spend(self):
        return Spend(provider=self.name, compute_per_hr=1.0, storage_per_hr=0.001,
                     cumulative_usd=2.5, running_pods=1, idle_volume_gb=0)
