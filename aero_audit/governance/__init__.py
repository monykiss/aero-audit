"""Holistic governance layer: a bird's-eye view of air and space navigation compliance, risk,
study and governing, built on the same evidence the audits already produce.

Four pillars over every domain:
- **Compliance**: a standards library and a controls library with typed evidence (rules, tests,
  artefacts, commands, workflows), so every control claim points at something checkable.
- **Risk**: one register across domains; air risks keep their evidence-adjusted likelihoods,
  space and UAS risks carry residuals from control status until their detectors exist.
- **Study**: a registry of reproducible analyses with provenance, some runnable today.
- **Governance**: policies, owners, cadences, and a posture roll-up with an index that moves
  only when controls, evidence, or risks move.

Modules: ``domains``, ``standards``, ``controls``, ``register``, ``studies``, ``posture``.
"""

from .controls import CONTROLS, POLICIES, Control, Policy, coverage, implementation_index
from .domains import DOMAINS, Domain
from .posture import posture
from .posture import render_markdown as render_posture
from .register import SPACE_RISKS, unified_register
from .standards import STANDARDS, Standard
from .studies import STUDIES, Study, run_study

__all__ = [
    "CONTROLS", "DOMAINS", "POLICIES", "SPACE_RISKS", "STANDARDS", "STUDIES", "Control", "Domain", "Policy", "Standard",
    "Study", "coverage", "implementation_index", "posture", "render_posture", "run_study", "unified_register",
]
