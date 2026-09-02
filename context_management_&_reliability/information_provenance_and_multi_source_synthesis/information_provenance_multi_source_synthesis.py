"""
Information Provenance & Multi-Source Synthesis
===================================================

Demonstrates the exam's attribution-preservation and conflict-handling
rules for multi-agent research pipelines, with real, deterministic code
(no LLM API call):

  1. STRUCTURED CLAIM-SOURCE MAPPINGS SURVIVING SYNTHESIS
     A naive synthesis step that just concatenates prose is shown to
     drop attribution ("Investment has grown significantly", no
     amounts/sources/dates). A synthesis step that explicitly carries
     structured mappings through preserves every claim's traceability.

  2. CONFLICT HANDLING -- ANNOTATE, DON'T RESOLVE
     Two credible sources reporting different numbers are annotated
     with both values and their attribution, rather than averaged or
     silently overwritten by picking "the more recent" one.

  3. TEMPORAL AWARENESS
     Different publication dates for different numbers are checked
     against each other to distinguish a genuine trend from a data
     contradiction.

  4. CONTENT-APPROPRIATE RENDERING
     A renderer picks table / prose / structured-list format based on
     content type, and forcing everything into one format is shown to
     be the documented anti-pattern.
"""

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Step 1: structured claim-source mappings vs naive synthesis
# ---------------------------------------------------------------------------

@dataclass
class ClaimSource:
    claim: str
    source_url: str
    document_name: str
    relevant_excerpt: str
    publication_date: str


RESEARCH_FINDINGS = [
    ClaimSource(
        claim="Global renewable energy investment grew 12% in 2023",
        source_url="https://iea.org/reports/2024-investment",
        document_name="IEA World Energy Investment 2024",
        relevant_excerpt="...investment in renewables rose 12% year-over-year...",
        publication_date="2024-06-01",
    ),
    ClaimSource(
        claim="Global renewable energy investment grew 8% in 2023",
        source_url="https://about.bnef.com/reports/2024-outlook",
        document_name="Bloomberg NEF 2024 Outlook",
        relevant_excerpt="...preliminary figures show 8% growth in renewables spend...",
        publication_date="2024-03-01",
    ),
]


def naive_synthesis(findings: list) -> str:
    """Models the documented failure: synthesis compresses without
    explicit preservation instructions, and attribution dies.
    """
    return "Investment has grown significantly."  # no amounts, sources, or dates!


def attribution_preserving_synthesis(findings: list) -> list:
    """Carries the full structured mapping through synthesis instead of
    collapsing to prose -- every claim remains traceable to a source.
    """
    return [
        {
            "claim": f.claim,
            "source": f.document_name,
            "url": f.source_url,
            "published": f.publication_date,
        }
        for f in findings
    ]


# ---------------------------------------------------------------------------
# Step 2: conflict handling -- annotate both, never average or pick one
# ---------------------------------------------------------------------------

def wrong_resolve_by_averaging(findings: list) -> float:
    """ANTI-PATTERN: averaging destroys both source's actual claims and
    invents a number neither source reported.
    """
    values = [12, 8]  # extracted percentages
    return sum(values) / len(values)


def wrong_resolve_by_most_recent(findings: list) -> ClaimSource:
    """ANTI-PATTERN: silently preferring the most recent source discards
    the other source's finding entirely, presenting false certainty.
    """
    return max(findings, key=lambda f: f.publication_date)


def correct_conflict_annotation(findings: list) -> dict:
    """CORRECT: annotate both values with full attribution, flag the
    conflict, and let the consumer decide relevance -- preserving the
    full picture instead of manufacturing false certainty.
    """
    return {
        "field": "renewable_energy_investment_growth_2023",
        "conflict_detected": True,
        "values": [
            {"value": f.claim.split(" ")[-3], "source": f.document_name, "published": f.publication_date}
            for f in findings
        ],
        "possible_explanation": "Different methodologies/reporting periods (IEA final vs. BNEF preliminary figures).",
    }


# ---------------------------------------------------------------------------
# Step 3: temporal awareness -- trend vs contradiction
# ---------------------------------------------------------------------------

@dataclass
class TimestampedClaim:
    value: float
    publication_date: str  # ISO date


def classify_discrepancy(a: TimestampedClaim, b: TimestampedClaim) -> str:
    """Distinguishes a genuine TREND (different dates, values moving in
    one direction) from a genuine CONTRADICTION (same or overlapping
    reporting period, but different values) using publication dates.
    """
    if a.publication_date == b.publication_date:
        return "contradiction -- same period, different values, no temporal explanation"
    earlier, later = sorted([a, b], key=lambda c: c.publication_date)
    direction = "increasing" if later.value > earlier.value else "decreasing"
    return f"trend ({direction}) -- different reporting periods explain the differing values, not a data quality issue"


# ---------------------------------------------------------------------------
# Step 4: content-appropriate rendering
# ---------------------------------------------------------------------------

def render_table(rows: list, columns: list) -> str:
    header = " | ".join(columns)
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append(" | ".join(str(row.get(c, "")) for c in columns))
    return "\n".join(lines)


def render_prose(sentences: list) -> str:
    return " ".join(sentences)


def render_structured_list(items: list) -> str:
    return "\n".join(f"- {item}" for item in items)


def render_content(content_type: str, data) -> str:
    """Picks format based on content type -- financial data as a table
    (comparison-friendly), news/current-events as prose (narrative
    context), technical findings as a structured list (specifications).
    Forcing everything into one format degrades comprehension.
    """
    renderers = {
        "financial": lambda d: render_table(d, columns=["metric", "value", "source"]),
        "news": render_prose,
        "technical": render_structured_list,
    }
    if content_type not in renderers:
        raise ValueError(f"unknown content type: {content_type}")
    return renderers[content_type](data)


def main():
    print("=== Step 1: Attribution surviving synthesis ===")
    print("  Naive synthesis (attribution dies):")
    print(f"    {naive_synthesis(RESEARCH_FINDINGS)!r}")
    print("  Attribution-preserving synthesis:")
    for entry in attribution_preserving_synthesis(RESEARCH_FINDINGS):
        print(f"    {entry}")

    print("\n=== Step 2: Conflict handling ===")
    print(f"  WRONG (averaging): {wrong_resolve_by_averaging(RESEARCH_FINDINGS)}%  (a number neither source reported)")
    picked = wrong_resolve_by_most_recent(RESEARCH_FINDINGS)
    print(f"  WRONG (most recent only): {picked.claim} -- discards the other source silently")
    print(f"  CORRECT (annotate both): {correct_conflict_annotation(RESEARCH_FINDINGS)}")

    print("\n=== Step 3: Temporal awareness (trend vs contradiction) ===")
    trend_case = classify_discrepancy(
        TimestampedClaim(8.0, "2023-03-01"), TimestampedClaim(12.0, "2024-06-01")
    )
    contradiction_case = classify_discrepancy(
        TimestampedClaim(8.0, "2024-06-01"), TimestampedClaim(12.0, "2024-06-01")
    )
    print(f"  Different dates:  {trend_case}")
    print(f"  Same date:        {contradiction_case}")

    print("\n=== Step 4: Content-appropriate rendering ===")
    financial_data = [{"metric": "Revenue", "value": "$4.2M", "source": "10-K"}]
    news_sentences = ["The policy was announced Tuesday.", "Analysts expect swift implementation."]
    technical_items = ["Uses event-driven architecture", "Redis-backed caching layer", "gRPC between services"]
    print("  Financial (table):\n" + render_content("financial", financial_data))
    print("\n  News (prose):\n  " + render_content("news", news_sentences))
    print("\n  Technical (structured list):\n" + render_content("technical", technical_items))


if __name__ == "__main__":
    main()
