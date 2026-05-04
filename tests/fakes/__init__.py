"""tests/fakes/ — mock Provider implementations for router smoke tests.

Each module defines a class ending in `Provider` that gpu.py's
`--providers tests.fakes.<name>` discovery picks up. Fakes have hardcoded
responses so the router's hop / cooldown / auth-error logic can be
exercised without hitting any live API.
"""
