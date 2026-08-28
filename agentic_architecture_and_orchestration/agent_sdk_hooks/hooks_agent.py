"""
Agent SDK Hooks -- Normalisation and Policy Enforcement
=========================================================

Demonstrates two Task Statement 1.4 concepts end to end:

  1. PostToolUse hooks run AFTER a tool executes but BEFORE the model sees
     the result. They are the correct place for DATA NORMALISATION: turning
     heterogeneous formats from multiple MCP tools into one consistent
     schema so the model never has to guess whether "P" means "pending" or
     "processed", or whether a date is DD/MM/YYYY or MM/DD/YYYY.

  2. PreToolUse hooks run BEFORE a tool executes. They are the correct (and
     ONLY correct) place for POLICY ENFORCEMENT that must block an action:
     a PostToolUse hook can observe that a refund was too large, but by
     then the refund has already happened. Only a PreToolUse hook can stop
     it from happening at all.

  Decision framework: hooks for 100% requirements (compliance, financial
  limits, prerequisite ordering), prompts for preferences (formatting,
  tone) where an occasional miss is not a business risk.

This module is self-contained (no external API keys required) so the
normalisation and enforcement logic can be exercised and tested directly.
Tool A/B/C stand in for three heterogeneous MCP tools; in a real system the
hooks would be registered with the Agent SDK's hook system, here they are
plain functions so the before/after semantics can be verified precisely.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Step 1: Three MCP tools returning data in three different formats
# ---------------------------------------------------------------------------

# Tool A: Unix timestamps (epoch seconds) + numeric status codes
_TOOL_A_STATUS_CODES = {0: "pending", 1: "processing", 2: "completed", 3: "failed"}

_TOOL_A_DATA = {
    "TASK-A1": {"updated_at": 1732233600, "status_code": 2},   # 2024-11-22
    "TASK-A2": {"updated_at": 1732320000, "status_code": 0},   # 2024-11-23
}


def tool_a_get_task(task_id: str) -> dict:
    """MCP Tool A: Unix timestamps + numeric status codes."""
    record = _TOOL_A_DATA.get(task_id, {})
    return {
        "task_id": task_id,
        "updated_at": record.get("updated_at"),
        "status_code": record.get("status_code"),
        "_source": "tool_a",
    }


# Tool B: ISO 8601 dates + English status strings (already "normal", but the
# agent must not assume every tool is this well-behaved).
_TOOL_B_DATA = {
    "TASK-B1": {"updated_at": "2024-11-22T00:00:00Z", "status": "completed"},
    "TASK-B2": {"updated_at": "2024-11-24T00:00:00Z", "status": "pending"},
}


def tool_b_get_task(task_id: str) -> dict:
    """MCP Tool B: ISO 8601 dates + English status strings."""
    record = _TOOL_B_DATA.get(task_id, {})
    return {
        "task_id": task_id,
        "updated_at": record.get("updated_at"),
        "status": record.get("status"),
        "_source": "tool_b",
    }


# Tool C: DD/MM/YYYY dates + single-character status codes
_TOOL_C_STATUS_CODES = {"P": "pending", "R": "processing", "C": "completed", "F": "failed"}

_TOOL_C_DATA = {
    "TASK-C1": {"updated_at": "22/11/2024", "status": "C"},
    "TASK-C2": {"updated_at": "25/11/2024", "status": "P"},
}


def tool_c_get_task(task_id: str) -> dict:
    """MCP Tool C: DD/MM/YYYY dates + single-character status codes."""
    record = _TOOL_C_DATA.get(task_id, {})
    return {
        "task_id": task_id,
        "updated_at": record.get("updated_at"),
        "status": record.get("status"),
        "_source": "tool_c",
    }


TOOLS = {
    "tool_a_get_task": tool_a_get_task,
    "tool_b_get_task": tool_b_get_task,
    "tool_c_get_task": tool_c_get_task,
}


# ---------------------------------------------------------------------------
# Step 2 & 3: PostToolUse hook -- normalise heterogeneous formats
# ---------------------------------------------------------------------------

def _normalise_date(raw) -> str:
    """Detect the incoming date format and convert to ISO 8601 (date-only)."""
    if isinstance(raw, (int, float)):
        # Unix epoch seconds (Tool A)
        return datetime.fromtimestamp(raw, tz=timezone.utc).strftime("%Y-%m-%d")
    if isinstance(raw, str):
        if "T" in raw or raw.count("-") == 2 and raw.index("-") == 4:
            # Already ISO 8601 (Tool B), e.g. 2024-11-22T00:00:00Z
            return raw.split("T")[0]
        if "/" in raw:
            # DD/MM/YYYY (Tool C)
            day, month, year = raw.split("/")
            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    raise ValueError(f"Unrecognised date format: {raw!r}")


def _normalise_status(raw) -> str:
    """Detect the incoming status representation and convert to a full
    English word."""
    if isinstance(raw, int):
        return _TOOL_A_STATUS_CODES.get(raw, "unknown")
    if isinstance(raw, str):
        if raw in _TOOL_C_STATUS_CODES:
            # Single-character code (Tool C). Checked before "already English"
            # because a bare single letter is ambiguous otherwise.
            return _TOOL_C_STATUS_CODES[raw]
        if raw.lower() in _TOOL_A_STATUS_CODES.values():
            # Already an English word (Tool B)
            return raw.lower()
    raise ValueError(f"Unrecognised status format: {raw!r}")


def post_tool_use_normalise(tool_name: str, result: dict) -> dict:
    """PostToolUse hook: runs AFTER the tool executes, BEFORE the model sees
    the result. Produces one consistent schema regardless of which of the
    three tools produced the raw data:

        {"task_id": ..., "updated_at": "YYYY-MM-DD", "status": "<english>"}
    """
    date_field = "updated_at"
    status_field = "status_code" if "status_code" in result else "status"

    normalised = {
        "task_id": result["task_id"],
        "updated_at": _normalise_date(result[date_field]),
        "status": _normalise_status(result[status_field]),
        "_source": result["_source"],
    }
    return normalised


def call_tool_normalised(tool_name: str, task_id: str) -> dict:
    """Simulates the SDK's tool-call pipeline: invoke the tool, then run the
    registered PostToolUse hook on its result before returning to the model.
    """
    raw_result = TOOLS[tool_name](task_id)
    return post_tool_use_normalise(tool_name, raw_result)


# ---------------------------------------------------------------------------
# Step 4 & 5: PreToolUse hooks -- deterministic policy enforcement
# ---------------------------------------------------------------------------

class PreToolUseBlocked(Exception):
    """Raised by a PreToolUse hook to stop a tool call before it executes."""


REFUND_LIMIT = 500.0


@dataclass
class HookSessionState:
    """Per-session state that PreToolUse hooks consult. Tracks facts that
    must be true BEFORE a gated tool is allowed to run."""
    aml_passed_accounts: set = field(default_factory=set)


def pre_tool_use_refund_limit(tool_name: str, tool_input: dict, session: HookSessionState) -> None:
    """PreToolUse hook: blocks process_refund before execution if the amount
    exceeds the policy threshold. Because this runs BEFORE the tool, the
    refund never happens for blocked calls -- a PostToolUse hook could only
    notice the problem after the money had already moved.
    """
    if tool_name != "process_refund":
        return
    amount = tool_input.get("amount", 0)
    if amount > REFUND_LIMIT:
        raise PreToolUseBlocked(
            f"process_refund blocked pre-execution: amount ${amount:.2f} exceeds "
            f"the ${REFUND_LIMIT:.2f} auto-approval limit. Redirecting to human "
            f"escalation workflow."
        )


def pre_tool_use_aml_check(tool_name: str, tool_input: dict, session: HookSessionState) -> None:
    """PreToolUse hook: blocks transfer_funds before execution until
    aml_check has returned a pass result for this account in the current
    session. Prompt instructions ("always run an AML check first") achieve
    ~95% compliance; this hook makes the requirement deterministic, which is
    what a regulatory control demands.
    """
    if tool_name != "transfer_funds":
        return
    account_id = tool_input.get("account_id")
    if account_id not in session.aml_passed_accounts:
        raise PreToolUseBlocked(
            f"transfer_funds blocked pre-execution: no passing aml_check on "
            f"record for account '{account_id}' in this session. Run "
            f"aml_check first."
        )


PRE_TOOL_USE_HOOKS = [pre_tool_use_refund_limit, pre_tool_use_aml_check]


@dataclass
class GatedAgent:
    """Runs registered PreToolUse hooks before executing gated tools, so
    blocked calls never reach the underlying implementation."""
    session: HookSessionState = field(default_factory=HookSessionState)
    hooks: list = field(default_factory=lambda: list(PRE_TOOL_USE_HOOKS))
    executed_calls: list = field(default_factory=list)

    def aml_check(self, account_id: str) -> dict:
        self.session.aml_passed_accounts.add(account_id)
        self.executed_calls.append(("aml_check", account_id))
        return {"account_id": account_id, "result": "pass"}

    def process_refund(self, amount: float) -> dict:
        for hook in self.hooks:
            hook("process_refund", {"amount": amount}, self.session)
        self.executed_calls.append(("process_refund", amount))
        return {"status": "refunded", "amount": amount}

    def transfer_funds(self, account_id: str, amount: float) -> dict:
        for hook in self.hooks:
            hook("transfer_funds", {"account_id": account_id, "amount": amount}, self.session)
        self.executed_calls.append(("transfer_funds", account_id, amount))
        return {"status": "transferred", "account_id": account_id, "amount": amount}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # --- Test 1 & 2: three heterogeneous tools normalise to one schema ------
    result_a = call_tool_normalised("tool_a_get_task", "TASK-A1")
    result_b = call_tool_normalised("tool_b_get_task", "TASK-B1")
    result_c = call_tool_normalised("tool_c_get_task", "TASK-C1")

    assert result_a == {"task_id": "TASK-A1", "updated_at": "2024-11-22", "status": "completed", "_source": "tool_a"}
    assert result_b == {"task_id": "TASK-B1", "updated_at": "2024-11-22", "status": "completed", "_source": "tool_b"}
    assert result_c == {"task_id": "TASK-C1", "updated_at": "2024-11-22", "status": "completed", "_source": "tool_c"}
    print("[PASS] all three tools normalised to identical ISO 8601 date + English status.")

    # DD/MM vs MM/DD ambiguity check: 25/11/2024 must NOT become month=25
    result_c2 = call_tool_normalised("tool_c_get_task", "TASK-C2")
    assert result_c2["updated_at"] == "2024-11-25"
    assert result_c2["status"] == "pending"  # "P" must map to pending, not "processed"
    print("[PASS] DD/MM/YYYY parsed correctly and 'P' correctly mapped to 'pending'.")

    # --- Step 3: query spanning all three tools stays consistent -------------
    all_results = [
        call_tool_normalised("tool_a_get_task", "TASK-A2"),
        call_tool_normalised("tool_b_get_task", "TASK-B2"),
        call_tool_normalised("tool_c_get_task", "TASK-C2"),
    ]
    for r in all_results:
        assert r["status"] == "pending"
        assert r["updated_at"].count("-") == 2 and len(r["updated_at"]) == 10
    print("[PASS] cross-tool query returns consistent ISO dates and English statuses:")
    for r in all_results:
        print(f"    {r}")

    # --- Test 4: PreToolUse blocks refunds over $500 --------------------------
    agent = GatedAgent()
    blocked = False
    try:
        agent.process_refund(amount=750.00)
    except PreToolUseBlocked:
        blocked = True
    assert blocked, "Refund over $500 should have been blocked pre-execution."
    assert not any(call[0] == "process_refund" for call in agent.executed_calls), (
        "Blocked refund must never reach execution."
    )
    print("[PASS] process_refund > $500 blocked before execution; underlying tool never ran.")

    refund = agent.process_refund(amount=120.00)
    assert refund["status"] == "refunded"
    print("[PASS] process_refund <= $500 executes normally.")

    # --- Test 5: PreToolUse blocks transfer_funds without a passing AML check -
    agent2 = GatedAgent()
    blocked_transfer = False
    try:
        agent2.transfer_funds(account_id="ACC-9001", amount=10_000)
    except PreToolUseBlocked:
        blocked_transfer = True
    assert blocked_transfer, "transfer_funds should be blocked without a prior aml_check pass."
    assert not any(call[0] == "transfer_funds" for call in agent2.executed_calls), (
        "Blocked transfer must never reach execution."
    )
    print("[PASS] transfer_funds blocked before execution without a passing AML check.")

    agent2.aml_check(account_id="ACC-9001")
    transfer = agent2.transfer_funds(account_id="ACC-9001", amount=10_000)
    assert transfer["status"] == "transferred"
    print("[PASS] transfer_funds executes after aml_check passes for that account.")

    # AML pass is scoped per-account, not a global switch
    blocked_other_account = False
    try:
        agent2.transfer_funds(account_id="ACC-9002", amount=500)
    except PreToolUseBlocked:
        blocked_other_account = True
    assert blocked_other_account, "AML pass for one account must not authorise another account."
    print("[PASS] AML pass correctly scoped to the checked account only.")

    print("\n[ALL TESTS PASSED]")
