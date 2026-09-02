"""
Few-Shot Prompting
====================

Demonstrates the exam principle: "Few-shot examples are the most
effective technique for achieving consistent, well-formatted output from
Claude -- not more instructions." No LLM API is called; instead this
module models the three documented deployment triggers with a
deterministic "extractor" whose behavior visibly improves once a
matching few-shot example is added to its example bank, and visibly
fails to improve when only extra prose instructions are added.

  1. INCONSISTENT FORMATTING
     A formatter that has thorough prose instructions but no examples
     produces varying output shapes across similar inputs. Adding one
     targeted example (input -> exact desired format) fixes it; adding
     MORE prose instructions does not.

  2. AMBIGUOUS JUDGMENT CALLS
     A severity classifier is inconsistent on a borderline case (e.g.
     variable shadowing) until it is given a worked example WITH
     reasoning explaining why that case was classified a given way --
     modeling how few-shot reasoning teaches a generalizable principle,
     not just a literal pattern match.

  3. EMPTY / NULL EXTRACTION ON NARRATIVE TEXT
     An extractor pulls fields correctly from tabular text but returns
     null on the same fields when they appear in narrative prose. A
     narrative-structured example fixes narrative extraction without
     needing to touch the tabular case.
"""

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Step 1: inconsistent formatting -> fixed by an example, not more prose
# ---------------------------------------------------------------------------

def format_without_examples(item: str, extra_instructions: str = "") -> str:
    """Models a prompt with thorough prose but no examples: output shape
    varies based on incidental properties of the input (e.g. length),
    exactly like an LLM guessing a format from words alone.
    """
    if len(item) % 2 == 0:
        return f"- {item}"          # bullet style
    return f"| {item} |"            # table style -- inconsistent!


def format_with_example(item: str) -> str:
    """Models a prompt with ONE few-shot example demonstrating the exact
    desired output format. The shape is now fixed regardless of input
    length.
    """
    return f"- {item}"  # matches the example's format, every time


def demo_formatting_consistency():
    items = ["auth", "database", "networking", "cache", "config"]
    without = [format_without_examples(i) for i in items]
    without_more_prose = [format_without_examples(i, extra_instructions="Please always use bullets.") for i in items]
    with_example = [format_with_example(i) for i in items]

    consistent_without = len(set(line[0] for line in without)) == 1
    consistent_more_prose = len(set(line[0] for line in without_more_prose)) == 1
    consistent_with_example = len(set(line[0] for line in with_example)) == 1

    return {
        "consistent_without_examples": consistent_without,
        "consistent_with_more_prose_only": consistent_more_prose,
        "consistent_with_one_example": consistent_with_example,
    }


# ---------------------------------------------------------------------------
# Step 2: ambiguous judgment calls -> fixed by reasoning, not just labels
# ---------------------------------------------------------------------------

@dataclass
class Example:
    code: str
    verdict: str
    reasoning: str


FEW_SHOT_BANK: list = []


def classify_shadowing(code: str) -> str:
    """Without an example, the classifier applies an unstable heuristic.
    With a reasoning-bearing example in FEW_SHOT_BANK that covers the
    *principle* (does the shadowed variable's scope overlap with a use
    of the outer variable?), it generalizes correctly to new but
    similar cases -- not just to the literal example text.
    """
    if not FEW_SHOT_BANK:
        # unstable heuristic: flips based on incidental string length
        return "critical" if len(code) % 3 == 0 else "minor"

    # With a worked example teaching the underlying principle (does the
    # shadow hide a variable that is *still read* after the inner scope
    # closes?), apply that principle instead of a surface heuristic.
    outer_var_read_after = "outer_used_after" in code
    return "critical" if outer_var_read_after else "minor"


def demo_judgment_consistency():
    borderline_cases = [
        "def f():\n    x = 1\n    def g():\n        x = 2\n    g()\n    return x  # outer_used_after",
        "def f():\n    x = 1\n    def g():\n        x = 2\n        return x\n    return g()",
    ]

    before = [classify_shadowing(c) for c in borderline_cases]

    FEW_SHOT_BANK.append(Example(
        code="def f():\n    total = 0\n    def g():\n        total = 5  # shadows, never read outside\n    g()\n    return total",
        verdict="minor",
        reasoning=(
            "The inner 'total' shadows the outer one, but the outer "
            "variable is never read after g() returns, so the shadow "
            "has no observable effect. Classify as minor. Only treat "
            "shadowing as critical when the outer variable IS read "
            "after the shadowing scope closes."
        ),
    ))

    after = [classify_shadowing(c) for c in borderline_cases]
    return {"before_example": before, "after_example": after}


# ---------------------------------------------------------------------------
# Step 3: narrative-text extraction gaps -> fixed by a matching example
# ---------------------------------------------------------------------------

TABLE_TEXT = "Vendor: Acme Corp | Amount: 500.00 | Due: 2026-01-15"
NARRATIVE_TEXT = (
    "Please remit payment of five hundred dollars to Acme Corp; "
    "this invoice for 500.00 must be settled by January 15, 2026."
)


def extract_amount(text: str, narrative_example_seen: bool = False) -> Optional[str]:
    """Models an extractor that handles the tabular structure it was
    implicitly tuned for, but returns None on the same field expressed
    in narrative prose -- until a narrative-shaped few-shot example is
    supplied.
    """
    if "Amount:" in text:
        return text.split("Amount:")[1].split("|")[0].strip()
    if narrative_example_seen and "for " in text and "must be settled" in text:
        # only extracts narrative phrasing once an example demonstrated it
        chunk = text.split("for ")[1].split(" must be settled")[0]
        return chunk.strip()
    return None  # would otherwise silently drop real data


def demo_narrative_extraction():
    table_result = extract_amount(TABLE_TEXT)
    narrative_result_before = extract_amount(NARRATIVE_TEXT, narrative_example_seen=False)
    narrative_result_after = extract_amount(NARRATIVE_TEXT, narrative_example_seen=True)
    return {
        "table_extraction": table_result,
        "narrative_extraction_without_example": narrative_result_before,
        "narrative_extraction_with_example": narrative_result_after,
    }


def main():
    print("=== Step 1: Formatting Consistency ===")
    for k, v in demo_formatting_consistency().items():
        print(f"  {k}: {v}")

    print("\n=== Step 2: Judgment Consistency (variable shadowing) ===")
    result = demo_judgment_consistency()
    print(f"  Verdicts before example: {result['before_example']}")
    print(f"  Verdicts after example:  {result['after_example']}")

    print("\n=== Step 3: Narrative Extraction ===")
    for k, v in demo_narrative_extraction().items():
        print(f"  {k}: {v!r}")


if __name__ == "__main__":
    main()
