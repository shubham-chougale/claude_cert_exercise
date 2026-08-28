"""
Customer Support Agent -- Workflow Enforcement & Handoff
=========================================================

Demonstrates two Task Statement 1.4 concepts end to end:

  1. PROGRAMMATIC ENFORCEMENT vs prompt-based guidance. A system prompt that
     says "always verify identity before processing refunds" still fails
     ~8% of the time in production, because the model is probabilistic. A
     prerequisite gate is deterministic: process_refund physically cannot
     run until get_customer has returned a verified customer ID in the
     current session. 92% reliable -> 100% reliable.

  2. STRUCTURED HANDOFF. When the agent cannot resolve an issue, it hands
     off to a human agent who has NO access to the conversation transcript.
     The handoff is the only information the human receives, so it must be
     self-contained: customer ID, conversation summary, root cause, refund
     amount, and recommended action.

This module is self-contained (no external API keys required) so the tool
gate and handoff protocol can be exercised and tested directly. In a
production system, get_customer / lookup_order / process_refund would be
real tool implementations wired into an LLM tool-use loop; here they are
implemented directly so the enforcement logic can be verified.
"""

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# System prompt (kept for realism -- NOT what enforces the workflow)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a customer support agent. Always verify customer identity with
get_customer before processing any refund. If you cannot fully resolve a
customer's issue, hand off to a human agent with a complete summary.

Note: this instruction alone is NOT sufficient to guarantee compliance --
see the ToolGate below, which is what actually enforces the rule.
"""


# ---------------------------------------------------------------------------
# Simulated backend data
# ---------------------------------------------------------------------------

_CUSTOMERS = {
    "jane@example.com": {"customer_id": "CUST-1001", "name": "Jane Doe"},
    "bob@example.com": {"customer_id": "CUST-1002", "name": "Bob Smith"},
}

_ORDERS = {
    "ORD-5001": {"customer_id": "CUST-1001", "item": "Wireless Headphones", "amount": 79.99},
    "ORD-5002": {"customer_id": "CUST-1002", "item": "Desk Lamp", "amount": 34.50},
}


# ---------------------------------------------------------------------------
# Tool definitions (JSON Schema input_schema, as an LLM tool-use loop expects)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "get_customer",
        "description": "Look up a customer by name or email and verify their identity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "identifier": {
                    "type": "string",
                    "description": "Customer's name or email address.",
                }
            },
            "required": ["identifier"],
        },
    },
    {
        "name": "lookup_order",
        "description": "Retrieve order details by order ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "The order ID, e.g. ORD-5001."}
            },
            "required": ["order_id"],
        },
    },
    {
        "name": "process_refund",
        "description": "Process a refund for a verified customer. Blocked until identity is verified.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Verified customer ID."},
                "amount": {"type": "number", "description": "Refund amount in USD."},
            },
            "required": ["customer_id", "amount"],
        },
    },
]


class ToolBlockedError(Exception):
    """Raised when a tool call is blocked by a prerequisite gate."""


# ---------------------------------------------------------------------------
# Session state + prerequisite gate
# ---------------------------------------------------------------------------

@dataclass
class SessionState:
    """Per-session state tracking which prerequisites have been satisfied.

    This is the enforcement mechanism. It is NOT a suggestion the model can
    reason its way around -- process_refund checks this state directly and
    refuses to run if it isn't satisfied, regardless of what the model
    "intended" to do.
    """
    verified_customer_id: Optional[str] = None
    tool_log: list = field(default_factory=list)

    def mark_verified(self, customer_id: str) -> None:
        self.verified_customer_id = customer_id

    def is_verified(self, customer_id: str) -> bool:
        return self.verified_customer_id == customer_id


@dataclass
class SupportAgent:
    session: SessionState = field(default_factory=SessionState)

    # -- Tool implementations -------------------------------------------------

    def get_customer(self, identifier: str) -> dict:
        record = _CUSTOMERS.get(identifier.strip().lower())
        self.session.tool_log.append(("get_customer", identifier))
        if not record:
            return {"verified": False, "error": f"No customer found for '{identifier}'."}
        self.session.mark_verified(record["customer_id"])
        return {"verified": True, "customer_id": record["customer_id"], "name": record["name"]}

    def lookup_order(self, order_id: str) -> dict:
        order = _ORDERS.get(order_id)
        self.session.tool_log.append(("lookup_order", order_id))
        if not order:
            return {"error": f"No order found for '{order_id}'."}
        return {"order_id": order_id, **order}

    def process_refund(self, customer_id: str, amount: float) -> dict:
        """The prerequisite gate.

        This is what makes enforcement deterministic instead of probabilistic:
        it does not matter whether the model "remembered" to verify -- if
        get_customer hasn't returned this exact verified customer_id in this
        session, the refund is physically blocked.
        """
        self.session.tool_log.append(("process_refund", customer_id, amount))
        if not self.session.is_verified(customer_id):
            raise ToolBlockedError(
                f"process_refund blocked: customer '{customer_id}' has not been "
                f"verified via get_customer in this session. Call get_customer "
                f"first."
            )
        return {"status": "refunded", "customer_id": customer_id, "amount": amount}


# ---------------------------------------------------------------------------
# Structured handoff protocol
# ---------------------------------------------------------------------------

REQUIRED_HANDOFF_FIELDS = (
    "customer_id",
    "conversation_summary",
    "root_cause",
    "refund_amount",
    "recommended_action",
)


@dataclass
class HandoffSummary:
    """Self-contained handoff to a human agent.

    The human agent has NO access to the conversation transcript -- this
    object is the only information they will ever see. Every field must be
    populated with real content, not a placeholder, or the human agent has
    to make the customer repeat everything.
    """
    customer_id: str
    conversation_summary: str
    root_cause: str
    refund_amount: Optional[float]
    recommended_action: str

    def validate(self) -> None:
        for field_name in REQUIRED_HANDOFF_FIELDS:
            value = getattr(self, field_name)
            if field_name == "refund_amount":
                continue  # legitimately None when no refund is involved
            if not value or not str(value).strip():
                raise ValueError(f"Handoff summary missing required field: {field_name}")

    def as_dict(self) -> dict:
        return {
            "customer_id": self.customer_id,
            "conversation_summary": self.conversation_summary,
            "root_cause": self.root_cause,
            "refund_amount": self.refund_amount,
            "recommended_action": self.recommended_action,
        }


def build_handoff(
    customer_id: str,
    conversation_summary: str,
    root_cause: str,
    recommended_action: str,
    refund_amount: Optional[float] = None,
) -> HandoffSummary:
    summary = HandoffSummary(
        customer_id=customer_id,
        conversation_summary=conversation_summary,
        root_cause=root_cause,
        refund_amount=refund_amount,
        recommended_action=recommended_action,
    )
    summary.validate()
    return summary


# ---------------------------------------------------------------------------
# Multi-concern decomposition
# ---------------------------------------------------------------------------

@dataclass
class Concern:
    kind: str          # "return" | "billing_dispute" | "address_update"
    detail: str
    finding: str = ""


def decompose_request(concerns: list) -> list:
    """Coordinator-style decomposition: one Concern object per distinct
    issue in a compound customer request. Nothing here resolves the
    concerns -- it just makes sure none of them get silently dropped
    before investigation.
    """
    return [Concern(kind=kind, detail=detail) for kind, detail in concerns]


def investigate_concerns(agent: SupportAgent, concerns: list) -> list:
    """Investigate every concern (simulating parallel investigation using
    shared session context -- e.g. the verified customer_id) and attach a
    finding to each. No concern is skipped.
    """
    for concern in concerns:
        if concern.kind == "return":
            concern.finding = f"Return investigated: {concern.detail}"
        elif concern.kind == "billing_dispute":
            concern.finding = f"Billing dispute investigated: {concern.detail}"
        elif concern.kind == "address_update":
            concern.finding = f"Address update investigated: {concern.detail}"
        else:
            concern.finding = f"Unrecognized concern investigated: {concern.detail}"
    return concerns


def synthesize_resolution(concerns: list) -> str:
    lines = ["Resolution summary covering all reported concerns:"]
    for concern in concerns:
        lines.append(f"- [{concern.kind}] {concern.finding}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # --- Test 1: gate blocks an unverified refund attempt -------------------
    agent = SupportAgent()
    blocked = False
    try:
        agent.process_refund(customer_id="CUST-1001", amount=79.99)
    except ToolBlockedError:
        blocked = True
    assert blocked, "Gate failed to block unverified refund!"
    print("[PASS] process_refund blocked before verification.")

    # --- Test 2: verify, then refund succeeds --------------------------------
    result = agent.get_customer("jane@example.com")
    assert result["verified"], "Verification should have succeeded."
    refund = agent.process_refund(customer_id=result["customer_id"], amount=79.99)
    assert refund["status"] == "refunded"
    print("[PASS] process_refund succeeded after verification.")

    # --- Test 3: gate is per-customer, not a global switch -------------------
    blocked_other = False
    try:
        agent.process_refund(customer_id="CUST-1002", amount=34.50)
    except ToolBlockedError:
        blocked_other = True
    assert blocked_other, "Gate must verify the SPECIFIC customer_id, not just 'someone'."
    print("[PASS] gate correctly scoped to the verified customer only.")

    # --- Test 4: structured handoff must be complete -------------------------
    handoff = build_handoff(
        customer_id="CUST-1001",
        conversation_summary=(
            "Customer Jane Doe reported ORD-5001 (Wireless Headphones, $79.99) "
            "arrived defective and requested a refund."
        ),
        root_cause="Defective unit confirmed via customer description; within return window.",
        recommended_action="Approve refund of $79.99 to original payment method.",
        refund_amount=79.99,
    )
    print("[PASS] structured handoff built with all required fields:")
    for k, v in handoff.as_dict().items():
        print(f"    {k}: {v}")

    incomplete = False
    try:
        build_handoff(
            customer_id="CUST-1001",
            conversation_summary="",
            root_cause="unclear",
            recommended_action="escalate",
        )
    except ValueError:
        incomplete = True
    assert incomplete, "Handoff validation should reject empty required fields."
    print("[PASS] incomplete handoff correctly rejected.")

    # --- Test 5: multi-concern request is decomposed and fully resolved -----
    concerns = decompose_request(
        [
            ("return", "Return ORD-5001, Wireless Headphones, arrived defective."),
            ("billing_dispute", "Charged twice for ORD-5002 due to a duplicate transaction."),
            ("address_update", "Update shipping address to 42 Example Ave."),
        ]
    )
    assert len(concerns) == 3
    investigate_concerns(agent, concerns)
    assert all(c.finding for c in concerns), "Every concern must have a finding -- none skipped."
    resolution = synthesize_resolution(concerns)
    for kind in ("return", "billing_dispute", "address_update"):
        assert kind in resolution, f"Resolution is missing the '{kind}' concern!"
    print("\n" + resolution)
    print("\n[PASS] multi-concern request decomposed, investigated, and synthesized "
          "into one resolution covering all three concerns.")

    print("\n[ALL TESTS PASSED]")
