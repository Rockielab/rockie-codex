# Physics Software Landscape

Posture values follow `references/licensing.md`. Source links are primary
project or documentation pages where practical.

| Package | Families | Posture | Source |
|---|---|---|---|
| LAMMPS | molecular_dynamics, force_fields | open_source | https://docs.lammps.org/Intro_opensource.html |
| GROMACS | molecular_dynamics, force_fields | open_source | https://www.gromacs.org/ |
| OpenMM | molecular_dynamics | open_source | https://openmm.org/ |
| CP2K | molecular_dynamics, electronic_structure | open_source | https://www.cp2k.org/ |
| Quantum ESPRESSO | electronic_structure | open_source | https://www.quantum-espresso.org/Doc/user_guide/node6.html |
| GPAW | electronic_structure | open_source | https://wiki.fysik.dtu.dk/gpaw/ |
| Psi4 | electronic_structure | open_source | https://psicode.org/ |
| ABINIT | electronic_structure | open_source | https://www.abinit.org/ |
| PYTHIA | particle_transport_collision | open_source | https://pythia.org/ |
| MadGraph5_aMC@NLO | particle_transport_collision | open_source | https://launchpad.net/mg5amcnlo |
| Geant4 | particle_transport_collision, nuclear_radiation | open_source | https://www.geant4.org/download/license |
| ROOT | particle_transport_collision | open_source | https://root.cern/ |
| OpenFOAM | continuum_multiphysics | open_source | https://openfoam.org/licence/ |
| SU2 | continuum_multiphysics | open_source | https://su2code.github.io/ |
| MOOSE | continuum_multiphysics | open_source | https://mooseframework.inl.gov/ |
| CalculiX | continuum_multiphysics | open_source | http://www.calculix.de/ |
| WarpX | plasma_pic | open_source | https://warpx.readthedocs.io/ |
| Smilei | plasma_pic | open_source | https://smileipic.github.io/Smilei/ |
| PIConGPU | plasma_pic | open_source | https://picongpu.readthedocs.io/ |
| Gkeyll | plasma_pic | open_source | https://gkeyll.readthedocs.io/ |
| OpenMC | nuclear_radiation | open_source | https://docs.openmc.org/ |
| Athena++ | astro_cosmology | open_source | https://www.athena-astro.app/ |
| Enzo | astro_cosmology | open_source | https://enzo-project.org/ |
| FLASH | astro_cosmology | free_academic_or_noncommercial | https://flash.rochester.edu/site/ |
| GADGET-family workflows | astro_cosmology | unknown_needs_review | https://wwwmpa.mpa-garching.mpg.de/gadget/ |
| VASP | electronic_structure | commercial_or_proprietary | https://www.vasp.at/ |
| Gaussian | electronic_structure | commercial_or_proprietary | https://gaussian.com/ |
| ORCA | electronic_structure | free_academic_or_noncommercial | https://www.faccts.de/orca/ |
| COMSOL Multiphysics | continuum_multiphysics | commercial_or_proprietary | https://www.comsol.com/ |
| Ansys | continuum_multiphysics | commercial_or_proprietary | https://www.ansys.com/ |
| Amber | force_fields, molecular_dynamics | commercial_or_proprietary | https://ambermd.org/ |
| CHARMM | force_fields, molecular_dynamics | commercial_or_proprietary | https://www.charmm.org/ |
| MCNP | nuclear_radiation | restricted_export_or_controlled | https://mcnp.lanl.gov/ |

## Open-Source-First Defaults

- Atomistic classical dynamics: LAMMPS, GROMACS, or OpenMM.
- DFT/electronic structure: Quantum ESPRESSO, CP2K, GPAW, Psi4, or
  ABINIT depending on basis, pseudopotential, and property needs.
- Event/transport: PYTHIA or MadGraph for generator workflows, Geant4
  for detector/geometry transport, ROOT for analysis artifacts.
- Continuum: OpenFOAM for CFD, SU2 for aerodynamic optimization,
  MOOSE for coupled PDEs, CalculiX for structural FEA.
- Plasma/PIC: WarpX, Smilei, PIConGPU, or Gkeyll.
- Nuclear/radiation: OpenMC or Geant4 when data libraries and use case
  are authorized.
- Astro/cosmology: Athena++ for grid hydrodynamics/MHD, Enzo for
  cosmology workflows, GADGET-family only after license review.
