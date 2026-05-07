"""NodeTool plugins.

Importing this package registers every tool below. Type-binding lives
in `descriptor.applies_to` (and on the class as `applies_to`); routes
filter the menu so PERSON-only tools aren't offered on COMMUNITY nodes.
"""

from .corpus_collocations import CorpusCollocations
from .show_evidence_chunks import ShowEvidenceChunks
from .show_neighbors import ShowNeighbors
from .summarize_subgraph import SummarizeSubgraph
from .wikidata_lookup import WikidataLookup

__all__ = [
    "CorpusCollocations",
    "ShowEvidenceChunks",
    "ShowNeighbors",
    "SummarizeSubgraph",
    "WikidataLookup",
]
