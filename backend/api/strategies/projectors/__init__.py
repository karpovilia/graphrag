"""Projector strategies — post-clusterer stage that derives intra-layer
co-occurrence edges from cross-layer evidence.

Import side-effects: each module registers itself via the
`projectors.register(...)` decorator. Listing all projectors as a
sub-package keeps that decorator graph in one place.
"""

from . import intra_layer_backbone  # noqa: F401 — side-effect: register
