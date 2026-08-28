"""
Structured metadata for context passing.
==========================================

The exam-tested failure mode: a coordinator hands a synthesis agent plain
strings ("solar capacity grew 12% in 2024") instead of objects carrying
*where* that claim came from. The synthesis agent then has no attribution
information to cite, no matter how its own prompt is worded -- the fix is
always upstream, in what the coordinator passes it, not in the synthesis
agent's instructions.

Every subagent in this exercise returns Finding objects, never bare text,
so content and source metadata travel together through every hop.
"""

from dataclasses import dataclass, asdict
from typing import Literal, Optional


@dataclass
class Finding:
    # The factual claim itself, in the researcher's own words.
    claim: str

    # Full URL of the web source. Empty string if the finding came from a local document.
    source_url: str

    # Title of the web page, or the filename/title of the document analysed.
    document_name: str

    # Page number within document_name. None for web sources, which have no pages.
    page_number: Optional[int]

    # How confident the subagent is that the claim is accurate and correctly attributed.
    confidence: Literal["high", "medium", "low"]

    # Which subagent produced this finding -- lets downstream agents trace provenance.
    retrieved_by: Literal["web-search-agent", "document-analysis-agent"]

    def to_dict(self) -> dict:
        return asdict(self)

    def is_attributed(self) -> bool:
        return bool(self.source_url) or bool(self.document_name)
