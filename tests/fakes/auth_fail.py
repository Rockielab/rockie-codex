"""Always raises AuthError — exercises router resilience to misconfigured providers."""
from providers.base import (  # noqa
    AuthError, GpuType, Pod, PodStatus, Price, Spend, SpotSpec,
)


class FakeAuthFailProvider:
    name = "fake-auth"
    supports_bid_auction = True
    supports_pause_preserve = True
    preemption_signal = "hard-kill"
    billing_url = "https://example.invalid/auth"

    def auth(self): raise AuthError("fake-auth: invalid key")
    def list_gpus(self, grep=None): raise AuthError("fake-auth")
    def price(self, gpu_type, n=1): raise AuthError("fake-auth")
    def create_spot(self, spec, *, yes): raise AuthError("fake-auth")
    def list_pods(self): raise AuthError("fake-auth")
    def get_pod(self, pod_id): raise AuthError("fake-auth")
    def stop(self, pod_id, *, yes): pass
    def terminate(self, pod_id, *, yes): pass
    def resume(self, pod_id, *, yes, bid=None): raise AuthError("fake-auth")
    def poll_once(self, pod_id): raise AuthError("fake-auth")
    def current_spend(self): raise AuthError("fake-auth")
