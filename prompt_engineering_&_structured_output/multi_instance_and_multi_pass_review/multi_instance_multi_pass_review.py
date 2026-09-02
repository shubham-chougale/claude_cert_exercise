"""
Multi-Instance and Multi-Pass Review
=======================================

Demonstrates the exam's multi-instance/multi-pass review architecture
with a real, deterministic model of the failure modes it fixes (no LLM
API call):

  1. SELF-REVIEW BIAS
     A "generator" and its in-session "reviewer" share state (the
     generator's own reasoning), so the reviewer is biased toward
     confirming the original decision. An INDEPENDENT reviewer with no
     access to that shared state judges the output fresh and catches
     what the biased reviewer misses.

  2. ATTENTION DILUTION IN SINGLE-PASS REVIEW
     A single review pass over many files shows uneven depth (findings
     concentrated at the start/end, missed issues in the middle) --
     modeling why larger context alone doesn't fix review quality.
     Splitting into one focused pass per file gives uniform depth.

  3. TWO-PASS ARCHITECTURE: PER-FILE THEN CROSS-FILE
     Pass 1 reviews each file in isolation (uniform depth, no dilution).
     Pass 2 takes ALL pass-1 findings and looks for issues that only
     exist ACROSS files (e.g. contradictory findings on the same
     pattern, or an API contract mismatch between two files) --
     something no per-file pass alone could catch.

  4. CONFIDENCE-BASED ROUTING WITH CALIBRATION
     Raw self-reported confidence is shown to be poorly correlated with
     actual correctness until it is calibrated against a labeled
     validation set; only the calibrated threshold is used for routing.
"""

import random
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Step 1: self-review bias vs an independent instance
# ---------------------------------------------------------------------------

@dataclass
class GeneratedCode:
    reasoning: str
    has_bug: bool


def biased_self_review(generated: GeneratedCode) -> bool:
    """Models reviewing output in the SAME session: the reviewer has
    access to the generator's own reasoning and is biased to confirm it
    ('it already knows why it chose each approach'). It only flags a
    bug if the reasoning itself admits uncertainty.
    """
    return "uncertain" in generated.reasoning.lower() and generated.has_bug


def independent_review(generated: GeneratedCode) -> bool:
    """Models an INDEPENDENT instance with no access to the generator's
    reasoning chain: it judges the CODE alone (the observable ground
    truth), unbiased by the story the generator told itself.
    """
    return generated.has_bug


def demo_self_review_bias():
    sample = GeneratedCode(
        reasoning="Using a cache here because it's clearly the fastest approach.",
        has_bug=True,  # e.g. cache invalidation bug, but the generator is confident
    )
    return {
        "same_session_review_flags_bug": biased_self_review(sample),
        "independent_instance_flags_bug": independent_review(sample),
    }


# ---------------------------------------------------------------------------
# Step 2: attention dilution in single-pass review over many files
# ---------------------------------------------------------------------------

def single_pass_review(files: list, attention_budget: int) -> dict:
    """Models a single review pass with a fixed 'attention budget' spread
    across all files. Middle files get diluted attention and their bugs
    are missed -- the documented symptom of single-pass review on large
    inputs.
    """
    per_file_attention = attention_budget / len(files)
    findings = {}
    for i, f in enumerate(files):
        # attention dips in the middle of a long pass (dilution), and
        # a bug is only caught if per-file attention exceeds a fixed cost
        position_penalty = 1.0 if i in (0, len(files) - 1) else 0.5
        effective_attention = per_file_attention * position_penalty
        findings[f["name"]] = effective_attention >= f["bug_detection_cost"] if f["has_bug"] else None
    return findings


def multi_pass_per_file_review(files: list, attention_budget: int) -> dict:
    """Models the fix: EACH file gets its own full, focused pass instead
    of a shared, diluted budget -- so depth is uniform regardless of
    position in the batch.
    """
    findings = {}
    for f in files:
        # every file gets the FULL per-pass budget, not a diluted share
        findings[f["name"]] = attention_budget >= f["bug_detection_cost"] if f["has_bug"] else None
    return findings


FILES = [
    {"name": "auth.py", "has_bug": True, "bug_detection_cost": 3},
    {"name": "db.py", "has_bug": True, "bug_detection_cost": 3},     # middle file
    {"name": "cache.py", "has_bug": True, "bug_detection_cost": 3},  # middle file
    {"name": "utils.py", "has_bug": False, "bug_detection_cost": 0},
    {"name": "api.py", "has_bug": True, "bug_detection_cost": 3},
]


# ---------------------------------------------------------------------------
# Step 3: two-pass architecture -- per-file, then cross-file integration
# ---------------------------------------------------------------------------

@dataclass
class PerFileFinding:
    file: str
    pattern: str
    verdict: str  # "flagged" | "approved"


def cross_file_integration_pass(per_file_findings: list) -> list:
    """Pass 2: looks ACROSS all pass-1 findings for contradictions (same
    pattern flagged in one file, approved in another) -- something no
    single per-file pass could ever detect on its own.
    """
    by_pattern: dict = {}
    for finding in per_file_findings:
        by_pattern.setdefault(finding.pattern, []).append(finding)

    contradictions = []
    for pattern, findings in by_pattern.items():
        verdicts = {f.verdict for f in findings}
        if len(verdicts) > 1:
            contradictions.append({
                "pattern": pattern,
                "files": [f.file for f in findings],
                "verdicts": [f.verdict for f in findings],
            })
    return contradictions


PER_FILE_FINDINGS = [
    PerFileFinding("auth.py", "unvalidated-input", "flagged"),
    PerFileFinding("api.py", "unvalidated-input", "approved"),  # contradiction!
    PerFileFinding("db.py", "raw-sql-string", "flagged"),
]


# ---------------------------------------------------------------------------
# Step 4: confidence calibration before routing
# ---------------------------------------------------------------------------

@dataclass
class LabeledFinding:
    raw_confidence: float
    actually_correct: bool


def calibrate_threshold(labeled_set: list) -> float:
    """Models calibrating a routing threshold against a labeled
    validation set: find the confidence cutoff above which findings are
    actually correct at an acceptable rate, rather than trusting raw
    self-reported confidence at face value.
    """
    candidates = sorted(set(f.raw_confidence for f in labeled_set))
    best_threshold = 1.0
    for t in candidates:
        above = [f for f in labeled_set if f.raw_confidence >= t]
        if not above:
            continue
        precision = sum(1 for f in above if f.actually_correct) / len(above)
        if precision >= 0.9:
            best_threshold = min(best_threshold, t)
    return best_threshold


LABELED_SET = [
    LabeledFinding(raw_confidence=0.95, actually_correct=False),  # confidently wrong
    LabeledFinding(raw_confidence=0.55, actually_correct=True),   # unsure but right
    LabeledFinding(raw_confidence=0.90, actually_correct=True),
    LabeledFinding(raw_confidence=0.92, actually_correct=True),
    LabeledFinding(raw_confidence=0.60, actually_correct=False),
]


def main():
    print("=== Step 1: Self-review bias vs independent instance ===")
    for k, v in demo_self_review_bias().items():
        print(f"  {k}: {v}")

    print("\n=== Step 2: Single-pass dilution vs per-file passes ===")
    single = single_pass_review(FILES, attention_budget=16)
    multi = multi_pass_per_file_review(FILES, attention_budget=3)
    print(f"  Single-pass findings (budget shared across files): {single}")
    print(f"  Per-file-pass findings (full budget per file):     {multi}")

    print("\n=== Step 3: Cross-file integration pass ===")
    contradictions = cross_file_integration_pass(PER_FILE_FINDINGS)
    for c in contradictions:
        print(f"  contradiction on pattern '{c['pattern']}': {c['files']} -> {c['verdicts']}")

    print("\n=== Step 4: Confidence calibration ===")
    naive_threshold = 0.8  # a plausible-looking but uncalibrated guess
    calibrated = calibrate_threshold(LABELED_SET)
    print(f"  Naive (uncalibrated) threshold guess: {naive_threshold}")
    print(f"  Calibrated threshold from labeled set: {calibrated}")
    print("  Note: the 0.95-confidence finding above was WRONG, showing raw")
    print("  confidence alone (e.g. a naive 0.8 cutoff) is not reliable for routing.")


if __name__ == "__main__":
    main()
