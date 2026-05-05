"""Clusterer plugins.

Importing this package triggers registration of every clusterer below.
A clusterer takes entity-layer Nodes + their relations and produces
community-layer Nodes plus MEMBER_OF edges from entities to communities.
"""

from .bayan import BayanClusterer
from .leiden import LeidenClusterer

__all__ = ["BayanClusterer", "LeidenClusterer"]
