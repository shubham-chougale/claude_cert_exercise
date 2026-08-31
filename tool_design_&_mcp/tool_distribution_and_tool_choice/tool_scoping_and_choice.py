"""
Tool Distribution & Tool Choice -- Scoping, Consolidation, tool_choice Modes
===================================================================

Demonstrates four exam scenarios about how many tools an agent carries and
how it is told to use them:

  1. TOOL OVERLOAD -- selection reliability degrades as the number of
     candidate tools on one agent grows, independent of how good any
     single description is. The fix is scoping agents to ~4-5 tools per
     role, not longer descriptions.

  2. CONSOLIDATION vs SPLITTING vs SHARPENING -- three different symptoms
     require three different fixes, and using the wrong one leaves the
     underlying problem untouched:
       - few tools, ambiguous wording           -> sharpen descriptions
       - genuinely different jobs               -> split by role (4-5 each)
       - many near-duplicate variants of one job -> consolidate into one
         parameterized tool
       - agent capable of doing too much         -> constrain (least privilege)

  3. tool_choice MODES -- "auto" (model may answer in free text or call a
     tool), "any" (must call some tool -- prevents conversational
     fallback when structured output is required from an unknown-in-advance
     schema), and forced/named choice (must call one specific tool -- used
     to make a workflow step mandatory).

  4. SCOPED CROSS-ROLE TOOLS -- routing every cross-role request through a
     coordinator costs round trips. Giving the requesting agent a
     constrained version of the capability for the common simple case
     (here, 85% of verifications) avoids that cost while the rare complex
     case still goes through the coordinator.

This module is self-contained (deterministic simulations instead of real
LLM calls) so each effect can be verified precisely.
"""

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Step 1: Tool overload -- selection accuracy degrades as candidate count grows
# ---------------------------------------------------------------------------

def simulated_selection_accuracy(num_tools: int) -> float:
    """Deterministic stand-in for how reliably a model picks the right tool
    out of `num_tools` candidates. Below the ~4-5 tool sweet spot, accuracy
    is effectively perfect; beyond it, each extra tool adds decision
    complexity and accuracy degrades monotonically -- independent of
    description quality.
    """
    if num_tools <= 5:
        return 1.0
    excess = num_tools - 5
    return max(0.0, 1.0 - 0.03 * excess)


# ---------------------------------------------------------------------------
# Step 2: Consolidating near-duplicate tools -- 22 tools -> 4, nothing lost
# ---------------------------------------------------------------------------

QUERY_TOOLS = ["run_query", "explain_query", "cancel_query"]

TRANSFORM_VARIANTS = [
    "pivot_table", "calculate_percentile", "normalise_currency", "dedupe_rows",
    "filter_rows", "sort_rows", "group_by", "aggregate_sum", "aggregate_avg",
    "aggregate_count", "join_tables", "unpivot_table", "fill_missing",
    "rename_columns", "cast_types", "round_values", "clip_outliers",
    "bucket_values", "rank_rows",
]

CONSOLIDATED_TRANSFORM_TOOL = {
    "transform_data": {"operation": TRANSFORM_VARIANTS},
}


def consolidate(variants: list, tool_name: str) -> dict:
    """Collapse N near-duplicate tools that differ only in which operation
    they perform into a single parameterized tool with an operation enum.
    Every original capability remains reachable via the enum value.
    """
    return {tool_name: {"operation": list(variants)}}


def reachable_operations(consolidated: dict) -> set:
    ops = set()
    for spec in consolidated.values():
        ops.update(spec.get("operation", []))
    return ops


# ---------------------------------------------------------------------------
# Step 3: Decision matrix -- pick the right fix for the right symptom
# ---------------------------------------------------------------------------

FIX_SHARPEN = "sharpen_descriptions"
FIX_SPLIT = "split_by_role"
FIX_CONSOLIDATE = "consolidate_into_parameterized_tool"
FIX_CONSTRAIN = "constrain_capabilities"


def recommend_fix(num_tools: int, are_near_duplicates: bool, are_different_jobs: bool) -> str:
    """The classic exam trap: with many near-duplicate tools, rewriting
    descriptions leaves decision complexity (the tool count) completely
    unchanged -- consolidation is required instead of sharpening.
    """
    if are_near_duplicates and num_tools > 5:
        return FIX_CONSOLIDATE
    if are_different_jobs and num_tools > 5:
        return FIX_SPLIT
    if num_tools <= 5 and not are_near_duplicates:
        return FIX_SHARPEN
    return FIX_CONSTRAIN


# ---------------------------------------------------------------------------
# Step 4: tool_choice modes
# ---------------------------------------------------------------------------

CHOICE_AUTO = "auto"
CHOICE_ANY = "any"
CHOICE_FORCED = "forced"


def recommend_tool_choice(needs_structured_output: bool, schema_unknown_in_advance: bool,
                           must_run_specific_tool_next: str = None) -> str:
    if must_run_specific_tool_next:
        return CHOICE_FORCED
    if needs_structured_output and schema_unknown_in_advance:
        # "any" guarantees a tool call without committing to which schema
        # in advance -- forcing one named tool would be wrong since the
        # document type (invoice/receipt/contract) isn't known yet.
        return CHOICE_ANY
    return CHOICE_AUTO


# ---------------------------------------------------------------------------
# Step 5: Scoped cross-role tools -- avoid coordinator round-trip overhead
# ---------------------------------------------------------------------------

@dataclass
class RoundTripReport:
    total_requests: int
    round_trips_baseline: int
    round_trips_scoped: int

    @property
    def round_trips_saved(self) -> int:
        return self.round_trips_baseline - self.round_trips_scoped


def simulate_verification_batch(total_requests: int, simple_fraction: float = 0.85,
                                 coordinator_round_trips: int = 3,
                                 scoped_round_trips: int = 1,
                                 complex_round_trips: int = 3) -> RoundTripReport:
    """Baseline: every verification -- simple or complex -- routes through
    the coordinator (coordinator_round_trips each). Scoped: simple
    verifications are handled directly by the requesting agent's own
    verify_fact tool (scoped_round_trips each); only complex ones still go
    through the coordinator.
    """
    num_simple = round(total_requests * simple_fraction)
    num_complex = total_requests - num_simple

    baseline = total_requests * coordinator_round_trips
    scoped = num_simple * scoped_round_trips + num_complex * complex_round_trips

    return RoundTripReport(
        total_requests=total_requests,
        round_trips_baseline=baseline,
        round_trips_scoped=scoped,
    )


# ---------------------------------------------------------------------------
# Step 6: Least privilege -- generic fetch_url vs constrained load_document
# ---------------------------------------------------------------------------

def fetch_url(url: str) -> str:
    """Generic: fetches anything from anywhere -- no scope restriction."""
    return f"fetched raw content from {url}"


DOCUMENT_HOSTS = {"docs.internal.example.com", "files.internal.example.com"}


def load_document(url: str) -> str:
    """Constrained: only resolves URLs on approved document hosts. Same
    underlying need (get document content) with least privilege enforced
    at the tool boundary instead of trusted to agent judgment.
    """
    host = url.split("/")[2] if "://" in url else url.split("/")[0]
    if host not in DOCUMENT_HOSTS:
        raise ValueError(f"load_document cannot access host '{host}': not an approved document host")
    return f"loaded document content from {url}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # --- Step 1: tool overload degrades selection accuracy -----------------
    assert simulated_selection_accuracy(4) == 1.0
    assert simulated_selection_accuracy(5) == 1.0
    acc_18 = simulated_selection_accuracy(18)
    assert acc_18 < 1.0, "18 tools on one agent should show degraded selection reliability."
    assert simulated_selection_accuracy(22) < acc_18, "Accuracy should keep degrading as tool count grows further."
    print(f"[OVERLOAD] accuracy at 5 tools: {simulated_selection_accuracy(5):.2f}, "
          f"at 18 tools: {acc_18:.2f}, at 22 tools: {simulated_selection_accuracy(22):.2f}.")

    # --- Step 2: consolidation collapses tool count, keeps every operation --
    original_tool_count = len(QUERY_TOOLS) + len(TRANSFORM_VARIANTS)
    assert original_tool_count == 22
    consolidated = {**{name: {} for name in QUERY_TOOLS}, **consolidate(TRANSFORM_VARIANTS, "transform_data")}
    assert len(consolidated) == 4, "22 tools should collapse to 4: 3 query tools + 1 parameterized transform tool."
    assert reachable_operations(consolidated) == set(TRANSFORM_VARIANTS), "No transformation should become unreachable."
    print(f"[CONSOLIDATE] {original_tool_count} tools -> {len(consolidated)} tools; "
          f"all {len(TRANSFORM_VARIANTS)} transformations remain reachable via the operation enum.")

    # --- Step 3: decision matrix picks the right fix per symptom -----------
    assert recommend_fix(num_tools=2, are_near_duplicates=False, are_different_jobs=False) == FIX_SHARPEN
    assert recommend_fix(num_tools=8, are_near_duplicates=False, are_different_jobs=True) == FIX_SPLIT
    assert recommend_fix(num_tools=22, are_near_duplicates=True, are_different_jobs=False) == FIX_CONSOLIDATE
    # The trap: sharpening descriptions on 22 near-duplicate tools is NOT
    # the recommended fix, even though the symptom "misrouting" looks the
    # same as Task 2.1's ambiguous-description case.
    trap_fix = recommend_fix(num_tools=22, are_near_duplicates=True, are_different_jobs=False)
    assert trap_fix != FIX_SHARPEN, "Rewriting descriptions on 22 near-duplicates leaves decision complexity unchanged."
    print(f"[DECISION MATRIX] 22 near-duplicate tools -> recommended fix is '{trap_fix}', not description rewrites.")

    # --- Step 4: tool_choice mode selection ---------------------------------
    assert recommend_tool_choice(needs_structured_output=False, schema_unknown_in_advance=False) == CHOICE_AUTO
    assert recommend_tool_choice(needs_structured_output=True, schema_unknown_in_advance=True) == CHOICE_ANY
    assert recommend_tool_choice(
        needs_structured_output=True, schema_unknown_in_advance=True,
        must_run_specific_tool_next="extract_metadata",
    ) == CHOICE_FORCED
    print("[TOOL_CHOICE] extraction across unknown invoice/receipt/contract schemas -> 'any'; "
          "general conversation -> 'auto'; mandatory workflow step -> forced named tool.")

    # --- Step 5: scoped cross-role tool avoids coordinator round-trips -----
    report = simulate_verification_batch(total_requests=100)
    assert report.round_trips_baseline == 300
    assert report.round_trips_scoped < report.round_trips_baseline
    savings_pct = report.round_trips_saved / report.round_trips_baseline
    assert savings_pct >= 0.40, "Scoping the common-case tool should recover roughly the ~40% latency the coordinator route adds."
    print(f"[SCOPED TOOL] 100 verifications: baseline {report.round_trips_baseline} round trips "
          f"vs scoped {report.round_trips_scoped} round trips "
          f"({savings_pct:.0%} saved by handling the 85% simple case locally).")

    # --- Step 6: least privilege -- constrained tool rejects out-of-scope use
    assert fetch_url("http://evil.example.com/anything") == "fetched raw content from http://evil.example.com/anything"
    assert load_document("https://docs.internal.example.com/report.pdf").startswith("loaded document content")
    try:
        load_document("http://evil.example.com/anything")
        raise AssertionError("load_document should reject hosts outside the approved document-host allowlist.")
    except ValueError as e:
        print(f"[LEAST PRIVILEGE] load_document correctly rejected an out-of-scope host: {e}")

    print("\n[ALL TESTS PASSED]")
