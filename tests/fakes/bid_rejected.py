"""Always raises BidRejected — exercises router hop on bid failures."""
from providers.base import (  # noqa
    BidRejected, GpuType, Pod, PodStatus, Price, Spend, SpotSpec,
)


class FakeBidRejProvider:
    name = "fake-bidrej"
    supports_bid_auction = True
    supports_pause_preserve = True
    preemption_signal = "hard-kill"
    billing_url = "https://example.invalid/bidrej"

    def auth(self): pass
    def list_gpus(self, grep=None): return []
    def price(self, gpu_type, n=1):
        return Price(min_bid=999.0, on_demand=999.0, stock=1, gpu_type_id=gpu_type)
    def create_spot(self, spec, *, yes): raise BidRejected("fake-bidrej: bid too low")
    def list_pods(self): return []
    def get_pod(self, pod_id): raise BidRejected(f"fake-bidrej: {pod_id}")
    def stop(self, pod_id, *, yes): pass
    def terminate(self, pod_id, *, yes): pass
    def resume(self, pod_id, *, yes, bid=None): return Pod(id=pod_id, provider=self.name)
    def poll_once(self, pod_id): return PodStatus(pod_id=pod_id, status="GONE")
    def current_spend(self):
        return Spend(provider=self.name, compute_per_hr=0.0, storage_per_hr=0.0,
                     cumulative_usd=0.0, running_pods=0, idle_volume_gb=0)
