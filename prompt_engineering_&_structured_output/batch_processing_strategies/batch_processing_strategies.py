"""
Batch Processing Strategies
==============================

Demonstrates the exam's Message Batches API decision rules with real,
deterministic calculations (no LLM API call):

  1. SYNCHRONOUS VS BATCH DECISION RULE
     Synchronous handles blocking workflows (something/someone is
     waiting on the result right now). Batch handles latency-tolerant
     workflows, in exchange for 50% cost savings and a processing
     window of up to 24 hours with NO guaranteed SLA.

  2. FAILURE HANDLING PATTERN
     Identify failures via custom_id, resubmit ONLY the failures with
     targeted prompt/document fixes (never the whole batch), and refine
     prompts against a small sample (5-10 documents) before submitting
     the full batch.

  3. SLA SCHEDULING MATH
     Given an end-to-end SLA, work backwards from the 24-hour maximum
     processing window to compute the required submission cadence.

  4. COST OF SKIPPING SAMPLE-DRIVEN REFINEMENT
     Comparing retry counts at different first-pass success rates
     quantifies why refining on a sample before the full run matters.
"""

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Step 1: synchronous vs batch decision rule
# ---------------------------------------------------------------------------

def choose_api_mode(is_blocking: bool, needs_multi_turn_tool_use: bool) -> str:
    """Models the documented decision rule. A blocking workflow (a human
    or a downstream process is waiting right now) or one that needs
    multi-turn tool execution mid-processing must use the synchronous
    API; the Batch API cannot support either.
    """
    if is_blocking:
        return "synchronous"
    if needs_multi_turn_tool_use:
        return "synchronous"  # batch has no multi-turn tool calling support
    return "batch"


SCENARIOS = [
    ("Pre-merge PR review blocking the merge button", True, False),
    ("Real-time code quality feedback in an IDE", True, False),
    ("Overnight technical-debt analysis across the repo", False, False),
    ("Weekly audit summary emailed to compliance", False, False),
    ("Nightly test generation for changed files", False, False),
    ("Agentic pipeline needing tool calls mid-run, run overnight", False, True),
]


# ---------------------------------------------------------------------------
# Step 2: failure handling -- identify via custom_id, resubmit selectively
# ---------------------------------------------------------------------------

@dataclass
class BatchResult:
    custom_id: str
    status: str          # "succeeded" | "failed"
    reason: str = ""


def collect_failures(results: list) -> list:
    """Identify exactly which requests failed via custom_id -- never
    reprocess the whole batch.
    """
    return [r for r in results if r.status == "failed"]


def build_resubmission(failures: list) -> list:
    """Applies TARGETED fixes per documented failure reason, rather than
    blindly resubmitting the identical failing request.
    """
    resubmit = []
    for f in failures:
        if "too large" in f.reason:
            fix = "chunked document into smaller sections"
        elif "unusual format" in f.reason:
            fix = "simplified extraction prompt for this format"
        elif "structural variety" in f.reason:
            fix = "added few-shot examples for structural variety"
        else:
            fix = "generic retry (no targeted fix identified)"
        resubmit.append({"custom_id": f.custom_id, "fix_applied": fix})
    return resubmit


# ---------------------------------------------------------------------------
# Step 3: SLA scheduling math
# ---------------------------------------------------------------------------

MAX_BATCH_WINDOW_HOURS = 24


def compute_submission_cadence(sla_hours: float, safety_margin: float = 1.5) -> dict:
    """Given an end-to-end SLA, computes the collection/validation buffer
    left after subtracting the worst-case 24h processing window, then
    derives a submission cadence that keeps the queue continuously fed
    with a safety margin -- never assume faster-than-worst-case
    completion. A 30h SLA leaves a 6h buffer; submitting every 4h
    (buffer / 1.5) keeps items from ever waiting near the edge of that
    buffer.
    """
    if sla_hours <= MAX_BATCH_WINDOW_HOURS:
        raise ValueError(
            f"SLA of {sla_hours}h cannot rely on batch (max window is "
            f"{MAX_BATCH_WINDOW_HOURS}h with no guaranteed SLA); use synchronous."
        )
    buffer_hours = sla_hours - MAX_BATCH_WINDOW_HOURS
    cadence_hours = buffer_hours / safety_margin
    return {
        "buffer_hours": buffer_hours,
        "submit_every_hours": cadence_hours,
    }


# ---------------------------------------------------------------------------
# Step 4: cost of skipping sample-driven refinement
# ---------------------------------------------------------------------------

def retries_required(document_count: int, first_pass_success_rate: float) -> int:
    failures = document_count * (1 - first_pass_success_rate)
    return round(failures)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def main():
    print("=== Step 1: Synchronous vs Batch ===")
    for name, blocking, needs_tools in SCENARIOS:
        mode = choose_api_mode(blocking, needs_tools)
        print(f"  [{mode:10}] {name}")

    print("\n=== Step 2: Failure handling ===")
    results = [
        BatchResult("doc-001", "succeeded"),
        BatchResult("doc-002", "failed", reason="document too large for context"),
        BatchResult("doc-003", "failed", reason="unusual format not seen in training examples"),
        BatchResult("doc-004", "succeeded"),
        BatchResult("doc-005", "failed", reason="structural variety not covered by prompt"),
    ]
    failures = collect_failures(results)
    print(f"  Identified {len(failures)} failures via custom_id: {[f.custom_id for f in failures]}")
    resubmission = build_resubmission(failures)
    for r in resubmission:
        print(f"    resubmit {r['custom_id']}: {r['fix_applied']}")

    print("\n=== Step 3: SLA scheduling math (30-hour SLA) ===")
    cadence = compute_submission_cadence(sla_hours=30, safety_margin=1.5)
    print(f"  Buffer after worst-case 24h window: {cadence['buffer_hours']}h")
    print(f"  Submit at least every: {cadence['submit_every_hours']}h to keep the queue continuously fed")

    print("\n=== Step 4: Cost of skipping sample-driven refinement (1000 docs) ===")
    print(f"  At 90% first-pass success (refined on a sample first): {retries_required(1000, 0.90)} retries")
    print(f"  At 60% first-pass success (skipped sample refinement):  {retries_required(1000, 0.60)} retries")


if __name__ == "__main__":
    main()
