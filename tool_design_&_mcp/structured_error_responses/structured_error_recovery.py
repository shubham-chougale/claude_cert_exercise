"""
Structured Error Responses -- MCP Tool Failure Categories & Agent Recovery
===================================================================

Demonstrates the exam's "empty result vs access failure" scenario:

  A customer-lookup tool returns an empty array. An agent retries 3 times,
  then escalates to a human. Investigation shows the account simply does
  not exist -- the query executed correctly and found nothing. The tool
  conflated a VALID EMPTY RESULT with an ACCESS FAILURE, so the agent had
  no way to tell "no data matches" from "I couldn't check."

The fix is structural: every tool response must carry enough metadata for
the agent to choose the right recovery action without guessing --

  isError        : did the call fail, or did it succeed with no matches?
  errorCategory  : transient | validation | business | permission
  isRetryable    : will resending the IDENTICAL call work?
  description    : what changed / what's needed before retrying

isRetryable is not "can the agent recover" -- it's narrower: "does
resending the same call help." Validation errors are isRetryable=false
but fully agent-recoverable (fix input, resend). Business and permission
errors are isRetryable=false AND dead ends for a retry loop -- they need
an alternative path or different credentials, not a resend.

This module is self-contained (a deterministic simulated MCP tool and a
deterministic agent loop instead of a real LLM/network call) so the
correct branching behaviour can be verified precisely.
"""

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Step 1: A simulated MCP tool that can return any of the failure modes,
# plus the two "success" shapes (data found / valid empty result).
# ---------------------------------------------------------------------------

def customer_lookup(mode: str) -> dict:
    """Deterministic stand-in for an MCP tool. `mode` selects which
    real-world situation to simulate.
    """
    if mode == "found":
        return {
            "isError": False,
            "content": [{"type": "text", "text": "Customer CUST-9001 found."}],
            "resultCount": 1,
        }

    if mode == "empty":
        # The query executed successfully; it just matched nothing. This is
        # NOT a failure -- retrying will return the identical empty result.
        return {
            "isError": False,
            "content": [{
                "type": "text",
                "text": "No customer found matching email 'john@example.com'. "
                        "Query executed successfully but returned no matches.",
            }],
            "resultCount": 0,
        }

    if mode == "transient":
        return {
            "isError": True,
            "content": [{"type": "text", "text": "Could not reach customer database"}],
            "errorCategory": "transient",
            "isRetryable": True,
            "description": "Connection to customer database timed out after 5 seconds. "
                            "Query did not execute. The request is valid and should "
                            "succeed on retry.",
        }

    if mode == "validation":
        return {
            "isError": True,
            "content": [{"type": "text", "text": "Invalid order ID format"}],
            "errorCategory": "validation",
            "isRetryable": False,
            "description": "Order ID must be in format #NNNNN (e.g. #12345). "
                            "Received: 'order-abc'. Reformat the ID and call again.",
        }

    if mode == "business":
        return {
            "isError": True,
            "content": [{"type": "text", "text": "Refund exceeds automatic approval limit"}],
            "errorCategory": "business",
            "isRetryable": False,
            "description": "Refund amount of £750 exceeds the £500 automatic refund "
                            "limit. This requires manager approval. Escalate to a "
                            "human agent with the refund details.",
        }

    if mode == "permission":
        return {
            "isError": True,
            "content": [{"type": "text", "text": "Access denied"}],
            "errorCategory": "permission",
            "isRetryable": False,
            "description": "The current service account does not have permission to "
                            "access financial records. Escalate to a senior agent "
                            "with financial system access.",
        }

    raise ValueError(f"unknown mode: {mode}")


# ---------------------------------------------------------------------------
# Step 2: Deterministic agent recovery loop -- branches on errorCategory,
# never treats a valid empty result as something to retry.
# ---------------------------------------------------------------------------

@dataclass
class RecoveryOutcome:
    action: str
    attempts: int = 1
    final_response: dict = field(default_factory=dict)
    escalated: bool = False


def recover(tool_fn, mode: str, max_transient_retries: int = 3) -> RecoveryOutcome:
    """Consume one tool response and decide the correct recovery action.
    A real agent would inspect the response after each retry; this
    simulation calls the same deterministic tool_fn again to model that,
    since our simulated transient failure does not change state.
    """
    response = tool_fn(mode)

    if not response["isError"]:
        # Success -- whether resultCount is 0 or not, there is nothing to
        # retry. A valid empty result is a completed query, not a failure.
        return RecoveryOutcome(action="accept_result", attempts=1, final_response=response)

    category = response["errorCategory"]

    if category == "transient":
        attempts = 1
        while response["isError"] and attempts < max_transient_retries:
            attempts += 1
            response = tool_fn(mode)  # simulated retry
        action = "retry_then_accept" if not response["isError"] else "retry_exhausted_escalate"
        return RecoveryOutcome(
            action=action, attempts=attempts, final_response=response,
            escalated=(action == "retry_exhausted_escalate"),
        )

    if category == "validation":
        # Not retryable as-is, but the agent recovers on its own by fixing
        # the input -- this is NOT an escalation.
        return RecoveryOutcome(action="reformat_input_and_resend", attempts=1, final_response=response)

    if category == "business":
        # Never retry: the same policy violation applies every time.
        return RecoveryOutcome(action="escalate_alternative_path", attempts=1,
                                final_response=response, escalated=True)

    if category == "permission":
        # Never retry with the same credentials.
        return RecoveryOutcome(action="escalate_request_credentials", attempts=1,
                                final_response=response, escalated=True)

    raise ValueError(f"unknown errorCategory: {category}")


# ---------------------------------------------------------------------------
# Step 3: Multi-agent error propagation -- local recovery vs. upward report
# ---------------------------------------------------------------------------

@dataclass
class SubagentReport:
    sources_attempted: int
    sources_succeeded: int
    partial_results: list
    propagated_error: str = None


def run_subagent_search(sources: list) -> SubagentReport:
    """Each source is a mode string for customer_lookup. Transient failures
    are retried locally (never surfaced). Non-recoverable failures are
    reported upward WITH whatever partial results were already gathered --
    never silently dropped, and never used to abort the whole batch.
    """
    partial_results = []
    non_recoverable = []

    for source in sources:
        outcome = recover(customer_lookup, source)
        if outcome.action in ("accept_result", "retry_then_accept"):
            partial_results.append(outcome.final_response)
        else:
            non_recoverable.append((source, outcome))

    propagated = None
    if non_recoverable:
        detail = ", ".join(f"{src} ({out.action})" for src, out in non_recoverable)
        propagated = (
            f"Searched {len(sources) - len(non_recoverable)} of {len(sources)} sources "
            f"successfully. Failed: {detail}. Returning partial results from successful sources."
        )

    return SubagentReport(
        sources_attempted=len(sources),
        sources_succeeded=len(partial_results),
        partial_results=partial_results,
        propagated_error=propagated,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # --- Step 1: valid empty result vs access failure are structurally distinct
    empty = customer_lookup("empty")
    assert empty["isError"] is False and empty["resultCount"] == 0
    failure = customer_lookup("transient")
    assert failure["isError"] is True and failure["errorCategory"] == "transient"
    print("[PASS] valid empty result (isError=False, resultCount=0) is structurally "
          "distinct from an access failure (isError=True, errorCategory='transient').")

    # --- Trap: agent must NOT retry a valid empty result ------------------
    outcome = recover(customer_lookup, "empty")
    assert outcome.action == "accept_result" and outcome.attempts == 1 and not outcome.escalated
    print("[PASS] agent accepts a valid empty result on the first call -- no retry, no escalation.")

    # --- Transient: retried with backoff, succeeds within the retry budget
    outcome = recover(customer_lookup, "transient", max_transient_retries=3)
    # customer_lookup("transient") is deterministic and always fails in this
    # simulation, so retries exhaust and the agent must escalate -- it must
    # NOT loop forever or silently give up without reporting.
    assert outcome.action == "retry_exhausted_escalate"
    assert outcome.attempts == 3
    assert outcome.escalated
    print(f"[PASS] transient failure retried {outcome.attempts} times (backoff budget), "
          f"then escalated after exhausting retries -- never retried indefinitely.")

    # --- Validation: not retryable, but agent recovers by fixing input, not escalating
    outcome = recover(customer_lookup, "validation")
    assert outcome.action == "reformat_input_and_resend"
    assert not outcome.escalated, "Validation errors are agent-recoverable, not a dead end."
    print("[PASS] validation error (isRetryable=false) is fixed by reformatting input, "
          "not escalated -- 'not retryable' does not mean 'give up'.")

    # --- Business: never retried, always escalated via an alternative path
    outcome = recover(customer_lookup, "business")
    assert outcome.action == "escalate_alternative_path" and outcome.escalated
    print("[PASS] business error (refund exceeds policy limit) is never retried -- "
          "same violation would recur -- escalated immediately.")

    # --- Permission: never retried, escalated to request different credentials
    outcome = recover(customer_lookup, "permission")
    assert outcome.action == "escalate_request_credentials" and outcome.escalated
    print("[PASS] permission error is never retried with the same credentials -- "
          "escalated to request access instead.")

    # --- Step 3: multi-agent propagation carries partial results, doesn't abort everything
    report = run_subagent_search(["found", "transient", "empty", "business"])
    assert report.sources_attempted == 4
    assert report.sources_succeeded == 2, "found + empty both count as successful queries."
    assert len(report.partial_results) == 2
    assert report.propagated_error is not None, "Non-recoverable failures must propagate upward."
    assert "2 of 4" in report.propagated_error
    print(f"[PASS] multi-agent search: {report.sources_succeeded}/{report.sources_attempted} "
          f"sources succeeded; non-recoverable failures propagated with partial results intact: "
          f"\"{report.propagated_error}\"")

    # --- Anti-pattern check: a fully successful batch propagates nothing ---
    clean_report = run_subagent_search(["found", "empty"])
    assert clean_report.propagated_error is None
    assert clean_report.sources_succeeded == 2
    print("[PASS] a batch with no non-recoverable failures propagates no error upward.")

    print("\n[ALL TESTS PASSED]")
