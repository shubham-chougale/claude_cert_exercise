"""
System Prompts with Explicit Criteria
======================================

Demonstrates why vague system-prompt instructions ("be conservative",
"use your best judgment", "flag high-confidence issues") fail to produce
consistent behavior, and why explicit categorical criteria fix it.

This module does NOT call any LLM API. It models the exam's scenario with
real, deterministic code: a rule-based "reviewer" that classifies findings
using (a) a vague criteria function and (b) an explicit criteria function,
run against the same fixed set of code findings, so the difference in
consistency and false-positive rate is directly observable.

  1. VAGUE VS EXPLICIT CRITERIA
     A vague filter ("only report if you're confident it's bad") is
     re-implemented as an unstable heuristic that flips on borderline
     cases depending on irrelevant ordering/framing -- modeling how an
     LLM given vague instructions produces inconsistent output run to
     run. An explicit filter (concrete category allow-list + trigger
     conditions) is deterministic and reproducible.

  2. THE FALSE POSITIVE TRUST PROBLEM
     A category with a high false-positive rate is shown to erode
     "trust" (measured as the fraction of ALL findings a downstream
     consumer would keep looking at) even though other categories are
     accurate. Disabling the noisy category, rather than tweaking its
     threshold, is shown to restore aggregate precision immediately.

  3. SEVERITY CALIBRATION WITH CONCRETE EXAMPLES
     Severity is assigned by matching findings against concrete code
     PATTERNS (e.g. unsanitized string-formatted SQL) rather than a
     prose definition like "issues that could cause system failures".
     This is shown to classify consistently across repeated runs,
     unlike a prose-only definition applied to boundary cases.
"""

from dataclasses import dataclass, field
from typing import Callable


# ---------------------------------------------------------------------------
# Fixture: a fixed set of "code review findings" the model must classify
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    id: str
    category: str          # e.g. "security", "style", "correctness"
    code_snippet: str
    is_actually_a_bug: bool  # ground truth, known only to this test harness


FINDINGS = [
    Finding("f1", "security", 'query = f"SELECT * FROM users WHERE id={user_id}"', True),
    Finding("f2", "security", 'query = "SELECT * FROM users WHERE id=%s"', False),
    Finding("f3", "style", "x=1", False),
    Finding("f4", "style", "def  foo( ):pass", False),
    Finding("f5", "correctness", "if claimed_total != sum(line_items): pass  # no-op, bug swallowed", True),
    Finding("f6", "correctness", "return sum(line_items)", False),
    Finding("f7", "security", 'os.system("rm -rf " + user_path)', True),
    Finding("f8", "style", "unused_var = compute()", False),
]


# ---------------------------------------------------------------------------
# Step 1: vague vs explicit criteria
# ---------------------------------------------------------------------------

def vague_filter(finding: Finding, run_order_bias: int = 0) -> bool:
    """Models a vague instruction: 'flag it if you're confident it's a
    real problem'. With no concrete decision boundary, the only signal
    left is incidental (e.g. position in the batch) -- so the same
    finding gets different verdicts across runs. This is the failure
    mode the exam calls out: vague language provides no actionable
    decision boundary.
    """
    # "confidence" here stands in for an LLM's uncalibrated self-rating,
    # which drifts with irrelevant context like batch position.
    pseudo_confidence = (hash(finding.id) + run_order_bias) % 10
    return pseudo_confidence >= 5


def explicit_filter(finding: Finding) -> bool:
    """Models explicit categorical criteria: a concrete allow-list of
    what to report, and concrete trigger conditions, with no dependence
    on incidental framing.
    """
    report_categories = {"security", "correctness"}
    if finding.category not in report_categories:
        return False  # style is explicitly out of scope, always
    if finding.category == "security":
        return "f\"" in finding.code_snippet or "os.system" in finding.code_snippet
    if finding.category == "correctness":
        return "no-op" in finding.code_snippet or "swallowed" in finding.code_snippet
    return False


def run_is_consistent(filter_fn: Callable[..., bool], trials: int = 5) -> bool:
    """A filter is 'consistent' if it produces the same verdict on every
    finding across repeated trials, regardless of incidental framing.
    """
    baseline = [filter_fn(f) for f in FINDINGS]
    for trial in range(1, trials):
        result = [filter_fn(f, run_order_bias=trial) if filter_fn is vague_filter
                  else filter_fn(f) for f in FINDINGS]
        if result != baseline:
            return False
    return True


# ---------------------------------------------------------------------------
# Step 2: the false-positive trust problem
# ---------------------------------------------------------------------------

def precision(flags: list) -> float:
    """Fraction of flagged findings that are real bugs (ground truth)."""
    flagged = [f for f, kept in zip(FINDINGS, flags) if kept]
    if not flagged:
        return 1.0
    correct = sum(1 for f in flagged if f.is_actually_a_bug)
    return correct / len(flagged)


def disable_category(category: str, filter_fn: Callable[[Finding], bool]) -> Callable[[Finding], bool]:
    """The documented fix for a noisy category: temporarily disable it
    entirely rather than trying to tune its threshold, which restores
    trust (precision) in the remaining categories immediately.
    """
    def wrapped(finding: Finding) -> bool:
        if finding.category == category:
            return False
        return filter_fn(finding)
    return wrapped


# ---------------------------------------------------------------------------
# Step 3: severity calibration via concrete code patterns, not prose
# ---------------------------------------------------------------------------

SEVERITY_PATTERNS = {
    "critical": [
        lambda code: "f\"SELECT" in code or "f'SELECT" in code,   # unsanitized SQL
        lambda code: "os.system(" in code and "+" in code,        # shell injection via concat
    ],
    "high": [
        lambda code: "no-op" in code or "swallowed" in code,      # silently dropped error
    ],
    "low": [
        lambda code: True,  # fallback: anything else that was still flagged
    ],
}


def classify_severity(finding: Finding) -> str:
    """Matches a finding against CONCRETE code patterns per severity
    level, instead of a prose definition ('could cause system
    failures') that would require subjective interpretation on
    boundary cases.
    """
    for severity in ("critical", "high", "low"):
        if any(pattern(finding.code_snippet) for pattern in SEVERITY_PATTERNS[severity]):
            return severity
    return "low"


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def main():
    print("=== Step 1: Vague vs Explicit Criteria ===")
    print(f"Vague filter consistent across runs?    {run_is_consistent(vague_filter)}")
    print(f"Explicit filter consistent across runs? {run_is_consistent(explicit_filter)}")

    print("\n=== Step 2: False Positive Trust Problem ===")
    explicit_flags = [explicit_filter(f) for f in FINDINGS]
    print(f"Precision with security+correctness enabled: {precision(explicit_flags):.2f}")

    # Simulate a "noisy" style category that was mistakenly left on with
    # a low bar (flags everything containing '='), tanking precision.
    def noisy_filter(finding: Finding) -> bool:
        if finding.category == "style":
            return "=" in finding.code_snippet
        return explicit_filter(finding)

    noisy_flags = [noisy_filter(f) for f in FINDINGS]
    print(f"Precision with noisy 'style' category on:     {precision(noisy_flags):.2f}")

    fixed_filter = disable_category("style", noisy_filter)
    fixed_flags = [fixed_filter(f) for f in FINDINGS]
    print(f"Precision after disabling 'style' category:   {precision(fixed_flags):.2f}")

    print("\n=== Step 3: Severity Calibration by Concrete Pattern ===")
    for f in FINDINGS:
        if explicit_filter(f):
            print(f"  {f.id} [{f.category}] -> severity={classify_severity(f)}  (actual bug={f.is_actually_a_bug})")


if __name__ == "__main__":
    main()
