"""
Context Window Management
============================

Demonstrates the exam's core context-management patterns with real,
deterministic code (no LLM API call):

  1. THE PROGRESSIVE SUMMARISATION TRAP
     A naive summarizer that compresses transactional text loses exact
     numbers, dates, and IDs. A persistent "case facts block" -- kept
     OUTSIDE the summarised text -- survives every summarisation cycle
     unchanged.

  2. THE LOST-IN-THE-MIDDLE EFFECT
     A structural fix (a "Key Findings Summary" placed at the START of
     aggregated input) is compared against a prompt-only fix ("pay
     attention everywhere"), by modeling an attention function that
     favors the beginning/end of input and dips in the middle.

  3. TOOL RESULT TRIMMING
     A verbose 40+ field tool result is trimmed to the handful of
     fields actually needed before it enters conversation history, so
     token cost doesn't compound across every subsequent turn.

  4. PROMPT CACHING LAYOUT
     A request is validated for the deterministic layout caching
     requires: static content (system/tools/reference docs) first, a
     cache_control breakpoint at the end of that block, then volatile
     per-request content -- with a check that flags a request that puts
     volatile content before the breakpoint (which would defeat caching).
"""

import json
import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Step 1: the progressive summarisation trap vs. a persistent case facts block
# ---------------------------------------------------------------------------

def naive_summarize(text: str) -> str:
    """Models a naive summarizer: it keeps the gist, but drops exact
    numbers/dates/IDs -- the documented failure mode.
    """
    if "refund" in text.lower():
        return "Customer wants a refund for a recent order."
    return "Customer message summarized."


def extract_case_facts(text: str) -> dict:
    """Extracts transactional essentials into a structured block that
    will be kept OUTSIDE the summarised narrative, so it survives every
    summarisation cycle unchanged.
    """
    amount = re.search(r"\$([\d,]+\.\d{2})", text)
    order_id = re.search(r"#(\w+)", text)
    date = re.search(r"(\w+ \d{1,2}(?:st|nd|rd|th)?)", text)
    return {
        "amount": amount.group(1) if amount else None,
        "order_id": order_id.group(1) if order_id else None,
        "date_mentioned": date.group(1) if date else None,
    }


def demo_case_facts_persistence():
    turns = [
        "I'd like a refund of $247.83 for order #8891 placed on March 3rd",
        "Also, I never got a response about my earlier ticket.",
        "Can you check on that refund status again?",
    ]
    case_facts = extract_case_facts(turns[0])  # captured once, kept outside summarisation

    summaries = []
    for turn in turns:
        summaries.append(naive_summarize(turn))  # narrative gets summarised every turn

    # after 3 rounds of summarisation, case_facts is untouched
    return {"case_facts_after_3_turns": case_facts, "narrative_summaries": summaries}


# ---------------------------------------------------------------------------
# Step 2: lost-in-the-middle -- structural fix vs prompt-only fix
# ---------------------------------------------------------------------------

def attention_weight(position: int, total: int) -> float:
    """Models the documented 'lost-in-the-middle' attention curve: high
    at the start and end, low in the middle. This models the model's
    behavior, not something a prompt instruction can override.
    """
    if position == 0 or position == total - 1:
        return 1.0
    # dips in the middle regardless of what the prompt asks for
    return 0.3


def retrieval_success(key_finding_position: int, total_sections: int, threshold: float = 0.5) -> bool:
    return attention_weight(key_finding_position, total_sections) >= threshold


def demo_lost_in_middle():
    total_sections = 6
    # naive aggregation: key finding buried in the middle (prompt-only "fix"
    # can't change where the attention curve dips)
    buried_position = 3
    # structural fix: key findings summary moved to position 0
    structural_position = 0

    return {
        "buried_in_middle_retrieved": retrieval_success(buried_position, total_sections),
        "moved_to_start_retrieved": retrieval_success(structural_position, total_sections),
    }


# ---------------------------------------------------------------------------
# Step 3: tool result trimming before it enters conversation history
# ---------------------------------------------------------------------------

VERBOSE_ORDER_LOOKUP = {
    "order_id": "ORD-8891",
    "order_date": "2026-03-03",
    "total_amount": 247.83,
    "return_eligible": True,
    "item_description": "Wireless Headphones",
    # ... the 35 fields below are never needed for a refund query, but a
    # naive integration would pass all of them straight into history
    "audit_created_at": "2026-03-03T10:22:00Z",
    "audit_updated_at": "2026-03-04T08:10:00Z",
    "warehouse_code": "WH-EAST-04",
    "carrier_id": "UPS-9931",
    "fulfillment_center": "FC-NJ-2",
    "internal_sku": "SKU-88213-BLK",
    "tax_jurisdiction_code": "US-NJ-021",
    "picking_batch_id": "BATCH-55210",
    # (imagine ~28 more fields here in the real payload)
}

RELEVANT_FIELDS = ["order_id", "order_date", "total_amount", "return_eligible", "item_description"]


def trim_tool_result(raw_result: dict, relevant_fields: list) -> dict:
    """Trims a verbose tool result to only the fields relevant to the
    current task, BEFORE it enters conversation history -- so the
    unused fields never compound across subsequent turns.
    """
    return {k: raw_result[k] for k in relevant_fields if k in raw_result}


def demo_tool_trimming():
    trimmed = trim_tool_result(VERBOSE_ORDER_LOOKUP, RELEVANT_FIELDS)
    raw_size = len(json.dumps(VERBOSE_ORDER_LOOKUP))
    trimmed_size = len(json.dumps(trimmed))
    return {
        "raw_field_count": len(VERBOSE_ORDER_LOOKUP),
        "trimmed_field_count": len(trimmed),
        "raw_json_bytes": raw_size,
        "trimmed_json_bytes": trimmed_size,
        "bytes_saved_per_turn": raw_size - trimmed_size,
    }


# ---------------------------------------------------------------------------
# Step 4: prompt caching layout validation
# ---------------------------------------------------------------------------

@dataclass
class PromptBlock:
    name: str
    is_static: bool
    has_cache_breakpoint: bool = False


def validate_cache_layout(blocks: list) -> dict:
    """Checks the deterministic layout prompt caching requires: static
    content first, breakpoint at the end of the static run, volatile
    content after. Returns whether the layout is cache-friendly and why.
    """
    breakpoint_index = next((i for i, b in enumerate(blocks) if b.has_cache_breakpoint), None)
    if breakpoint_index is None:
        return {"cache_friendly": False, "reason": "no cache_control breakpoint set"}

    static_before_breakpoint = all(b.is_static for b in blocks[:breakpoint_index + 1])
    volatile_after_breakpoint = all(not b.is_static for b in blocks[breakpoint_index + 1:])

    if not static_before_breakpoint:
        return {"cache_friendly": False, "reason": "volatile content appears before the breakpoint"}
    if not volatile_after_breakpoint:
        return {"cache_friendly": False, "reason": "static content appears after the breakpoint (wastes cache reuse)"}
    return {"cache_friendly": True, "reason": "static content, then breakpoint, then volatile content"}


def demo_cache_layout():
    good_layout = [
        PromptBlock("system_instructions", is_static=True),
        PromptBlock("tool_definitions", is_static=True),
        PromptBlock("reference_docs", is_static=True, has_cache_breakpoint=True),
        PromptBlock("user_message", is_static=False),
    ]
    bad_layout = [
        PromptBlock("system_instructions", is_static=True),
        PromptBlock("user_message", is_static=False, has_cache_breakpoint=True),  # volatile before/at breakpoint
        PromptBlock("reference_docs", is_static=True),
    ]
    return {
        "good_layout": validate_cache_layout(good_layout),
        "bad_layout": validate_cache_layout(bad_layout),
    }


def main():
    print("=== Step 1: Progressive summarisation trap vs case facts block ===")
    result = demo_case_facts_persistence()
    print(f"  Case facts (persist unchanged): {result['case_facts_after_3_turns']}")
    print(f"  Narrative summaries (lossy each turn): {result['narrative_summaries']}")

    print("\n=== Step 2: Lost-in-the-middle -- structural fix ===")
    for k, v in demo_lost_in_middle().items():
        print(f"  {k}: {v}")

    print("\n=== Step 3: Tool result trimming ===")
    for k, v in demo_tool_trimming().items():
        print(f"  {k}: {v}")

    print("\n=== Step 4: Prompt caching layout validation ===")
    for k, v in demo_cache_layout().items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
