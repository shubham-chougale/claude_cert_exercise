"""
Error Propagation in Multi-Agent Systems
===========================================

Demonstrates the exam's structured-error-context pattern for
coordinator/subagent systems with real, deterministic code (no LLM API
call):

  1. FOUR-TYPE FAILURE CLASSIFICATION
     transient (may succeed on retry), validation (bad input), business
     (rule violation), permission (access denied) -- each routed to a
     different coordinator response.

  2. TWO ANTI-PATTERNS
     Silent suppression (returning empty results marked "success",
     which hides the failure from the coordinator entirely) and
     workflow termination (one subagent failure kills a pipeline that
     had other, already-successful results) are both modeled and shown
     to produce worse coordinator outcomes than structured error
     context.

  3. ACCESS FAILURE VS VALID EMPTY RESULT
     A "query executed successfully but found nothing" result is
     distinguished from "the query never executed" -- conflating them
     either skips a needed retry or wastes one on a query that will
     always return nothing.

  4. STRUCTURED ERROR RESPONSE
     A subagent failure carries failure type, attempted action,
     partial results already retrieved, and alternative approaches --
     letting the coordinator make an informed recovery decision instead
     of guessing.
"""

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Step 1: four-type failure classification
# ---------------------------------------------------------------------------

FAILURE_TYPES = {
    "transient": "timeout/rate-limit -- may succeed on retry",
    "validation": "bad input -- fix the query before retrying",
    "business": "rule violation -- escalate or find an alternative approach",
    "permission": "access denied -- requires authorization changes, not a retry",
}


def coordinator_response_for(failure_type: str) -> str:
    return {
        "transient": "retry_same_query",
        "validation": "fix_query_and_retry",
        "business": "escalate_or_alternative",
        "permission": "request_authorization",
    }.get(failure_type, "unknown_failure_type")


# ---------------------------------------------------------------------------
# Step 2: two anti-patterns modeled against structured error context
# ---------------------------------------------------------------------------

@dataclass
class SubagentResult:
    status: str                       # "success" | "partial_failure" | "error"
    results: list = field(default_factory=list)
    failure_type: Optional[str] = None
    attempted_action: Optional[dict] = None
    partial_results: list = field(default_factory=list)
    alternative_approaches: list = field(default_factory=list)


def silent_suppression_result() -> SubagentResult:
    """ANTI-PATTERN: a timeout is swallowed and reported as a successful
    empty search. The coordinator has no way to distinguish this from a
    genuinely-empty valid result, so it never retries or tries an
    alternative -- the gap becomes invisible in the final output.
    """
    return SubagentResult(status="success", results=[])  # timeout hidden!


def workflow_termination_result(other_subagent_results: list) -> dict:
    """ANTI-PATTERN: one subagent's failure aborts the ENTIRE pipeline,
    discarding results other subagents already completed successfully.
    """
    return {"status": "aborted", "discarded_successful_results": other_subagent_results}


def structured_error_result() -> SubagentResult:
    """CORRECT: the failure is surfaced with full structured context so
    the coordinator can make an informed decision.
    """
    return SubagentResult(
        status="partial_failure",
        failure_type="transient",
        attempted_action={"tool": "search_academic_db", "query": "renewable energy policy", "dateRange": "2022-2024"},
        partial_results=[{"title": "EU Renewable Energy Directive 2023", "source": "EUR-Lex", "retrieved": True}],
        alternative_approaches=[
            "Retry with narrower date range (2023-2024)",
            "Search alternative database: government_publications",
            "Use cached results from previous research session",
        ],
    )


def coordinator_decide(result: SubagentResult) -> str:
    """Models the coordinator making an informed choice ONLY possible
    because of structured error context: retry, try an alternative, use
    partial results, or escalate.
    """
    if result.status == "success":
        return "accept_as_final" if result.results else "accept_empty_as_valid (WRONG if this was actually a suppressed failure)"
    if result.status == "partial_failure" and result.failure_type == "transient":
        return f"retry_or_alternative: will try -> {result.alternative_approaches[0]}, keeping {len(result.partial_results)} partial result(s)"
    return "escalate"


# ---------------------------------------------------------------------------
# Step 3: access failure vs valid empty result
# ---------------------------------------------------------------------------

@dataclass
class QueryOutcome:
    query_executed: bool
    matches_found: int
    error: Optional[str] = None


def classify_outcome(outcome: QueryOutcome) -> dict:
    """Distinguishes 'the query never ran' (access failure, should
    retry) from 'the query ran and correctly found nothing' (valid
    empty result, no retry needed). Conflating these is the documented
    exam trap.
    """
    if not outcome.query_executed:
        return {"status": "error", "shouldRetry": True, "reason": outcome.error or "query did not execute"}
    return {"status": "success", "shouldRetry": False, "reason": "query executed; zero matches is the correct answer"}


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def main():
    print("=== Step 1: Four-type failure classification ===")
    for ftype, desc in FAILURE_TYPES.items():
        print(f"  {ftype:12} -> {coordinator_response_for(ftype):25} ({desc})")

    print("\n=== Step 2: Anti-patterns vs structured error context ===")
    suppressed = silent_suppression_result()
    print(f"  Silent suppression result: status={suppressed.status}, results={suppressed.results}")
    print(f"    Coordinator decision (BLIND to the real timeout): {coordinator_decide(suppressed)}")

    terminated = workflow_termination_result(other_subagent_results=["finding_A", "finding_B"])
    print(f"  Workflow termination result: {terminated}  (discards successful work!)")

    structured = structured_error_result()
    print(f"  Structured error result: status={structured.status}, failure_type={structured.failure_type}")
    print(f"    Coordinator decision (INFORMED): {coordinator_decide(structured)}")

    print("\n=== Step 3: Access failure vs valid empty result ===")
    access_failure = QueryOutcome(query_executed=False, matches_found=0, error="connection timeout")
    valid_empty = QueryOutcome(query_executed=True, matches_found=0)
    print(f"  Access failure  -> {classify_outcome(access_failure)}")
    print(f"  Valid empty     -> {classify_outcome(valid_empty)}")


if __name__ == "__main__":
    main()
