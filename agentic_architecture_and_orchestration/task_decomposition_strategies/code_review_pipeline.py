"""
Task Decomposition Strategies -- Multi-Pass Code Review Pipeline
===================================================================

Demonstrates the exam's "attention dilution" scenario:

  A single agent asked to review 14 files in one pass gives detailed
  feedback for the first few files, then quietly degrades -- missing
  obvious bugs in the later files -- and flags an identical pattern as a
  problem in one file while approving it in another. This is a STRUCTURAL
  attention-allocation problem, not a model-capability or prompting
  problem, so the fix is architectural: decompose the single pass into

    1. a PER-FILE local-analysis pass (equal budget per file, so quality
       doesn't degrade with file count), plus
    2. a separate CROSS-FILE integration pass (data-flow, API-consistency,
       and pattern-usage checks that only make sense once every file's
       findings are visible together).

A bigger context window or a stronger "be equally thorough" system prompt
do not fix this: they either don't touch the underlying attention
allocation, or degrade in the same way at a larger scale. Batching without
a cross-file pass also isn't sufficient -- it removes the dilution but
still misses cross-cutting issues no single file exposes on its own.

This module is self-contained (deterministic rule-based "review" instead
of a real LLM call) so the structural difference between single-pass and
multi-pass can be verified precisely.
"""

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Step 1: A directory of 14 source files, large enough for dilution to show
# ---------------------------------------------------------------------------

# Pattern A: an inefficient loop that manually appends instead of using a
# list comprehension. Present in several files, at different positions in
# the review order -- this is the "identical pattern, inconsistent verdict"
# case.
_LOOP_PATTERN = "for item in items:\n    results.append(item * 2)"

# Pattern B: a shared API called with two DIFFERENT signatures across files.
# No single file's contents reveal this -- it is only visible once you
# compare call sites across the whole directory.
_API_CALL_OLD = "process_item(item)"
_API_CALL_NEW = "process_item(item, mode=\"fast\")"

FILES = {}
for i in range(1, 15):
    name = f"file_{i:02d}.py"
    lines = [f"# {name}", "def handler(items):", "    results = []"]
    if i in (1, 3, 10, 12):
        lines.append("    " + _LOOP_PATTERN.replace("\n", "\n    "))
    else:
        lines.append("    results = [item * 2 for item in items]")
    if i in (2, 7, 11):
        call = _API_CALL_OLD if i in (2,) else _API_CALL_NEW
        lines.append(f"    {call}")
    lines.append("    return results")
    FILES[name] = "\n".join(lines)


# ---------------------------------------------------------------------------
# Deterministic rule-based "reviewer" primitives (stand in for an LLM call)
# ---------------------------------------------------------------------------

def _has_loop_pattern(content: str) -> bool:
    return "results.append(item * 2)" in content


def _api_call_signature(content: str) -> str:
    if _API_CALL_NEW in content:
        return "process_item(item, mode)"
    if _API_CALL_OLD in content:
        return "process_item(item)"
    return ""


# ---------------------------------------------------------------------------
# Step 2: Single-pass review -- baseline that demonstrates attention dilution
# ---------------------------------------------------------------------------

@dataclass
class SinglePassResult:
    findings: dict = field(default_factory=dict)   # file -> list[str]
    files_reviewed_thoroughly: list = field(default_factory=list)
    files_reviewed_shallow: list = field(default_factory=list)


def single_pass_review(files: dict, attention_budget: int = 5) -> SinglePassResult:
    """Review all files in one pass with a fixed 'attention budget'. Once
    the budget is exhausted, thoroughness silently degrades -- exactly the
    attention-dilution symptom the exam describes: detailed feedback for
    the first few files, then missed bugs later, with no signal to the
    caller that quality has dropped.
    """
    result = SinglePassResult()
    for idx, (name, content) in enumerate(files.items(), start=1):
        findings = []
        if idx <= attention_budget:
            result.files_reviewed_thoroughly.append(name)
            if _has_loop_pattern(content):
                findings.append("inefficient loop: use a list comprehension")
        else:
            result.files_reviewed_shallow.append(name)
            # Attention exhausted: pattern checks are skipped entirely, so
            # the same bug that was caught earlier now goes unnoticed.
        result.findings[name] = findings
    return result


def find_contradictions(single_pass: SinglePassResult, files: dict) -> list:
    """Step 6: detect cases where an identical pattern was flagged in one
    file but approved (silently passed) in another -- the concrete,
    checkable symptom of attention dilution.
    """
    flagged = {f for f, issues in single_pass.findings.items() if issues}
    has_pattern = {f for f, content in files.items() if _has_loop_pattern(content)}
    contradictions = sorted(has_pattern - flagged)
    return contradictions


# ---------------------------------------------------------------------------
# Step 3: Per-file local analysis -- equal budget per file, order-independent
# ---------------------------------------------------------------------------

@dataclass
class FileFinding:
    file: str
    bugs: list = field(default_factory=list)
    severity: str = "none"
    api_signature: str = ""


def per_file_review(name: str, content: str) -> FileFinding:
    """Full-attention review of exactly one file. Because each call is
    independent and gets the same fixed budget, thoroughness never decays
    with position in a longer list of files.
    """
    bugs = []
    if _has_loop_pattern(content):
        bugs.append(f"{name}: inefficient loop (line 4) -- use a list comprehension")
    severity = "medium" if bugs else "none"
    return FileFinding(file=name, bugs=bugs, severity=severity, api_signature=_api_call_signature(content))


def run_per_file_pass(files: dict) -> dict:
    return {name: per_file_review(name, content) for name, content in files.items()}


# ---------------------------------------------------------------------------
# Step 4: Cross-file integration pass -- data flow / API consistency
# ---------------------------------------------------------------------------

def cross_file_integration_pass(per_file_findings: dict) -> list:
    """Checks that only make sense with every file's findings visible at
    once: here, whether a shared function is called with a consistent
    signature across the whole directory. No single per-file pass can see
    this on its own.
    """
    signatures_used = {}
    for name, finding in per_file_findings.items():
        if finding.api_signature:
            signatures_used.setdefault(finding.api_signature, []).append(name)

    issues = []
    if len(signatures_used) > 1:
        detail = ", ".join(f"{sig} in {files}" for sig, files in signatures_used.items())
        issues.append(f"API consistency: process_item() called with inconsistent signatures: {detail}")
    return issues


# ---------------------------------------------------------------------------
# Step 5: Compare single-pass vs multi-pass results
# ---------------------------------------------------------------------------

@dataclass
class ComparisonReport:
    single_pass_bug_count: int
    multi_pass_bug_count: int
    contradictions: list
    cross_file_only_issues: list

    def multi_pass_strictly_better(self) -> bool:
        return (
            self.multi_pass_bug_count > self.single_pass_bug_count
            and not self.contradictions_in_multi_pass()
        )

    def contradictions_in_multi_pass(self) -> bool:
        return False  # per-file pass is applied uniformly; never applicable


def compare(files: dict) -> ComparisonReport:
    single = single_pass_review(files)
    contradictions = find_contradictions(single, files)

    per_file = run_per_file_pass(files)
    cross_file_issues = cross_file_integration_pass(per_file)

    single_bug_count = sum(len(v) for v in single.findings.values())
    multi_bug_count = sum(len(f.bugs) for f in per_file.values()) + len(cross_file_issues)

    return ComparisonReport(
        single_pass_bug_count=single_bug_count,
        multi_pass_bug_count=multi_bug_count,
        contradictions=contradictions,
        cross_file_only_issues=cross_file_issues,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    assert len(FILES) >= 10, "Need 10+ files to replicate the scale where dilution appears."
    print(f"[PASS] directory has {len(FILES)} files.")

    # --- Step 2: single-pass shows attention dilution ------------------------
    single = single_pass_review(FILES)
    assert single.files_reviewed_thoroughly == [f"file_{i:02d}.py" for i in range(1, 6)]
    assert "file_10.py" in single.files_reviewed_shallow
    assert "file_12.py" in single.files_reviewed_shallow
    # Loop pattern is present in file_01 (caught) AND file_10/file_12 (missed).
    assert single.findings["file_01.py"], "Early file should be caught (within budget)."
    assert not single.findings["file_10.py"], "Late file's identical bug should be MISSED (dilution)."
    assert not single.findings["file_12.py"], "Late file's identical bug should be MISSED (dilution)."
    print("[PASS] single-pass review demonstrates attention dilution after the budget is exhausted.")

    # --- Step 6: contradiction detection --------------------------------------
    contradictions = find_contradictions(single, FILES)
    assert contradictions == ["file_10.py", "file_12.py"]
    print(f"[PASS] contradictions recorded: identical pattern flagged in file_01.py/file_03.py "
          f"but silently approved in {contradictions}.")

    # --- Step 3: per-file pass is order-independent, no degradation ----------
    per_file = run_per_file_pass(FILES)
    for name in ("file_01.py", "file_03.py", "file_10.py", "file_12.py"):
        assert per_file[name].bugs, f"Per-file pass should catch the loop bug in {name}."
    for name in FILES:
        if name not in ("file_01.py", "file_03.py", "file_10.py", "file_12.py"):
            assert not per_file[name].bugs
    print("[PASS] per-file pass flags the loop pattern consistently in every file that has it, "
          "regardless of position in the directory.")

    # --- Step 4: cross-file pass catches what no single file reveals --------
    cross_issues = cross_file_integration_pass(per_file)
    assert cross_issues, "Cross-file pass should detect the inconsistent process_item() signatures."
    assert "inconsistent signatures" in cross_issues[0]
    print(f"[PASS] cross-file integration pass caught: {cross_issues[0]}")

    single_cross = []  # single-pass never does cross-file comparison at all
    assert single_cross == [], "Single-pass has no mechanism to catch cross-file issues."
    print("[PASS] single-pass review has no cross-file lens, so it cannot catch this class of issue.")

    # --- Step 5: multi-pass is strictly better --------------------------------
    report = compare(FILES)
    assert report.multi_pass_bug_count > report.single_pass_bug_count
    assert report.contradictions == ["file_10.py", "file_12.py"]
    assert report.cross_file_only_issues
    print(
        f"\n[COMPARISON] single-pass found {report.single_pass_bug_count} issue(s); "
        f"multi-pass found {report.multi_pass_bug_count} issue(s) "
        f"(including {len(report.cross_file_only_issues)} cross-file-only issue(s))."
    )

    print("\n[ALL TESTS PASSED]")
