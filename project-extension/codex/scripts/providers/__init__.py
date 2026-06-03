"""providers/ — GPU adapter package.

See base.py for the Protocol every adapter implements. The router in
scripts/gpu.py iterates configured adapters, but ships with none in its
default rank — compute-supplier selection lives behind the deidentified
`rockie-gpu` broker (the single GPU surface; see the gpu-spend and
inference-engineer skills). No concrete adapter is bundled here; inject
one ad-hoc via `gpu.py --providers <dotted.module.path>` (the test fakes
under tests/fakes/ are the reference implementations).
"""
