"""
Escalation & Ambiguity Resolution
====================================

Demonstrates the exam's escalation-trigger rules with real, deterministic
code (no LLM API call):

  1. THREE VALID ESCALATION TRIGGERS
     Explicit human request (immediate, no exceptions), policy GAPS
     (as opposed to policy violations, which have a documented answer),
     and inability to make meaningful progress after genuine attempts.

  2. TWO UNRELIABLE ANTI-PATTERN TRIGGERS
     Sentiment-based escalation (frustration doesn't correlate with
     complexity) and raw self-reported confidence (poorly calibrated).
     Both are modeled and shown to mis-route cases the valid triggers
     handle correctly.

  3. AMBIGUOUS CUSTOMER MATCHING
     When multiple records match, the correct behavior is to request
     disambiguating information -- never guess via a heuristic like
     "most recent" or "most active", which risks acting on the wrong
     person's data.
"""

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Step 1: three valid escalation triggers
# ---------------------------------------------------------------------------

@dataclass
class Case:
    id: str
    explicit_human_request: bool = False
    policy_covers_situation: bool = True   # False = policy GAP (silent on this case)
    is_policy_violation: bool = False       # True = documented answer exists, not a gap
    attempts_made: int = 0
    attempts_failed: bool = False
    sentiment: str = "neutral"              # "angry" | "neutral" | "calm"
    self_reported_confidence: float = 0.9   # LLM's own confidence, deliberately unreliable


def should_escalate_valid_rules(case: Case) -> tuple:
    """Applies ONLY the three documented valid triggers, in priority
    order. Returns (should_escalate, reason).
    """
    if case.explicit_human_request:
        return True, "explicit human request -- escalate immediately, no investigation first"

    if not case.policy_covers_situation and not case.is_policy_violation:
        return True, "policy gap -- policy is silent on this situation (not a documented violation)"

    if case.attempts_made > 0 and case.attempts_failed:
        return True, "inability to make meaningful progress after genuine resolution attempts"

    return False, "no valid escalation trigger met -- continue attempting resolution"


# ---------------------------------------------------------------------------
# Step 2: unreliable anti-pattern triggers, shown to mis-route
# ---------------------------------------------------------------------------

def should_escalate_by_sentiment(case: Case) -> bool:
    """Anti-pattern: escalate whenever the customer sounds angry.
    Frustration does not correlate with case complexity, so this
    mis-routes easy angry cases to humans and lets hard calm cases
    through untouched.
    """
    return case.sentiment == "angry"


def should_escalate_by_raw_confidence(case: Case, threshold: float = 0.5) -> bool:
    """Anti-pattern: escalate only when the model's OWN confidence is
    low. Self-reported confidence is poorly calibrated -- a model can
    be confidently wrong on a genuinely hard case.
    """
    return case.self_reported_confidence < threshold


CASES = [
    # angry customer, but trivially resolvable (late delivery, tracking shows it's arriving)
    Case(id="c1", sentiment="angry", attempts_made=1, attempts_failed=False, self_reported_confidence=0.95),
    # calm customer, but requesting a genuine policy exception (competitor price match: policy silent)
    Case(id="c2", sentiment="calm", policy_covers_situation=False, is_policy_violation=False,
         self_reported_confidence=0.9),
]


def demo_anti_pattern_misrouting():
    results = []
    for case in CASES:
        valid_escalate, valid_reason = should_escalate_valid_rules(case)
        sentiment_escalate = should_escalate_by_sentiment(case)
        confidence_escalate = should_escalate_by_raw_confidence(case)
        results.append({
            "case": case.id,
            "correct_via_valid_rules": (valid_escalate, valid_reason),
            "sentiment_rule_says": sentiment_escalate,
            "confidence_rule_says": confidence_escalate,
            "sentiment_rule_wrong": sentiment_escalate != valid_escalate,
            "confidence_rule_wrong": confidence_escalate != valid_escalate,
        })
    return results


# ---------------------------------------------------------------------------
# Step 3: ambiguous customer matching -- request disambiguation, never guess
# ---------------------------------------------------------------------------

@dataclass
class CustomerRecord:
    customer_id: str
    name: str
    email: str
    last_active: str


CUSTOMER_DB = [
    CustomerRecord("CUST-001", "John Smith", "john.smith@aol.com", "2024-01-15"),
    CustomerRecord("CUST-002", "John Smith", "jsmith@gmail.com", "2026-08-30"),
    CustomerRecord("CUST-003", "John Smith", "j.smith@work.com", "2025-11-02"),
]


def resolve_customer(name: str, email: Optional[str] = None) -> dict:
    """Never guesses via a 'most recent' or 'most active' heuristic when
    multiple records match. If email disambiguates uniquely, use it;
    otherwise, request disambiguating information.
    """
    matches = [c for c in CUSTOMER_DB if c.name == name]
    if len(matches) <= 1:
        return {"status": "resolved", "record": matches[0] if matches else None}

    if email:
        by_email = [c for c in matches if c.email == email]
        if len(by_email) == 1:
            return {"status": "resolved", "record": by_email[0]}

    return {
        "status": "needs_disambiguation",
        "candidate_count": len(matches),
        "request": "Please provide your email, phone number, or order number to confirm your identity.",
    }


def wrong_heuristic_resolve_most_recent(name: str) -> CustomerRecord:
    """The documented ANTI-PATTERN: silently picking the most recently
    active matching record. Shown here only to demonstrate why it's
    unsafe -- it can act on the wrong person's data.
    """
    matches = [c for c in CUSTOMER_DB if c.name == name]
    return max(matches, key=lambda c: c.last_active)


def main():
    print("=== Step 1: Three valid escalation triggers ===")
    trigger_cases = [
        Case(id="explicit-request", explicit_human_request=True),
        Case(id="policy-gap", policy_covers_situation=False, is_policy_violation=False),
        Case(id="policy-violation-not-gap", policy_covers_situation=True, is_policy_violation=True),
        Case(id="failed-attempts", attempts_made=2, attempts_failed=True),
        Case(id="no-trigger", attempts_made=0),
    ]
    for c in trigger_cases:
        escalate, reason = should_escalate_valid_rules(c)
        print(f"  [{c.id:25}] escalate={escalate}  reason={reason}")

    print("\n=== Step 2: Anti-pattern triggers mis-routing cases ===")
    for r in demo_anti_pattern_misrouting():
        print(f"  case={r['case']}: correct={r['correct_via_valid_rules'][0]}  "
              f"sentiment_rule_wrong={r['sentiment_rule_wrong']}  confidence_rule_wrong={r['confidence_rule_wrong']}")

    print("\n=== Step 3: Ambiguous customer matching ===")
    print("  Correct approach (request disambiguation):", resolve_customer("John Smith"))
    print("  Correct approach with email match:         ", resolve_customer("John Smith", email="jsmith@gmail.com"))
    unsafe = wrong_heuristic_resolve_most_recent("John Smith")
    print(f"  UNSAFE heuristic ('most recent') would silently pick: {unsafe.customer_id} ({unsafe.email})"
          f" -- risks privacy violation / wrong-account action")


if __name__ == "__main__":
    main()
