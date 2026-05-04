"""Always raises OutOfStock — exercises the router's hop logic."""
from providers.base import (  # noqa
    GpuType, OutOfStock, Pod, PodStatus, Price, Spend, SpotSpec,
)


class FakeOOSProvider:
    name = "fake-oos"
    supports_bid_auction = True
    supports_pause_preserve = True
    preemption_signal = "hard-kill"
    billing_url = "https://example.invalid/oos"

    def auth(self): pass
    def list_gpus(self, grep=None): return []
    def price(self, gpu_type, n=1): raise OutOfStock(f"fake-oos: no {gpu_type}")
    def create_spot(self, spec, *, yes): raise OutOfStock(f"fake-oos: {spec.gpu_type}")
    def list_pods(self): return []
    def get_pod(self, pod_id): raise OutOfStock(f"fake-oos: {pod_id}")
    def stop(self, pod_id, *, yes): pass
    def terminate(self, pod_id, *, yes): pass
    def resume(self, pod_id, *, yes, bid=None): return Pod(id=pod_id, provider=self.name)
    def poll_once(self, pod_id): return PodStatus(pod_id=pod_id, status="GONE")
    def current_spend(self):
        return Spend(provider=self.name, compute_per_hr=0.0, storage_per_hr=0.0,
                     cumulative_usd=0.0, running_pods=0, idle_volume_gb=0)
