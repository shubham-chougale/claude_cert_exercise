"""
CI/CD Integration -- Running Claude Code Non-Interactively
===================================================================

Demonstrates the exam's headless-pipeline scenario:

  A CI pipeline invokes Claude Code with a prompt and the job hangs
  indefinitely. Logs show Claude waiting for interactive input that will
  never arrive, because Claude Code defaults to interactive mode.

The fix is the `-p` / `--print` flag, which switches Claude Code to
non-interactive print mode: it processes the prompt, writes the result to
stdout, and exits. Decoy "fixes" that do NOT work: a `CLAUDE_HEADLESS=true`
env var (does not exist), a `--batch` flag (does not exist), and
redirecting stdin from `/dev/null` (does not address the interactive-mode
problem at all).

This module also covers four other CI-integration concepts from the exam:

  1. Structured, machine-parseable output via `--output-format json` and
     `--json-schema`, whose schema-conforming payload lands in the
     envelope's `structured_output` field.
  2. Why same-session code review is measurably weaker than an
     independent-session review: the reviewer retains the generator's own
     justification reasoning, which biases it toward approving its own
     decisions.
  3. Incremental review: without carrying forward prior findings, every
     run re-reports every unfixed issue on every push, drowning out new
     signal and eroding developer trust.
  4. Choosing between the real-time (synchronous) API and the Batch API:
     blocking pre-merge checks need real-time; the Batch API has no
     latency SLA (up to 24h) and is only appropriate for non-blocking,
     schedule-tolerant workflows.

This module is self-contained -- it never shells out to a real `claude`
binary. Every CLI/API interaction is a deterministic Python simulation so
the structural difference between correct and incorrect CI configuration
can be verified precisely.
"""

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Step 1: The `-p` flag -- the real fix for a hanging CI pipeline
# ---------------------------------------------------------------------------

# Flags/patterns that look like plausible fixes but do not exist or do not
# solve the interactive-mode problem, per the exam content.
_DECOY_ENV_VARS = {"CLAUDE_HEADLESS"}
_DECOY_FLAGS = {"--batch"}


def validate_ci_command(argv: list, env: dict = None) -> dict:
    """Inspect a simulated CI invocation and report whether it is safe to
    run non-interactively. Only `-p` / `--print` actually switches Claude
    Code out of interactive mode; everything else is a decoy.
    """
    env = env or {}
    has_print_flag = "-p" in argv or "--print" in argv
    has_decoy_env = any(k in env for k in _DECOY_ENV_VARS)
    has_decoy_flag = any(f in argv for f in _DECOY_FLAGS)
    stdin_redirected = "< /dev/null" in " ".join(argv)

    return {
        "ci_safe": has_print_flag,
        "would_hang": not has_print_flag,
        "decoys_present": has_decoy_env or has_decoy_flag or stdin_redirected,
    }


# ---------------------------------------------------------------------------
# Step 2: Structured output -- --output-format json + --json-schema
# ---------------------------------------------------------------------------

FINDINGS_SCHEMA = {
    "type": "array",
    "items": {
        "required": ["file", "line", "severity", "message"],
    },
}


def run_headless(prompt: str, findings: list) -> dict:
    """Simulate a `claude -p ... --output-format json --json-schema ...`
    invocation: the schema-conforming payload lands in `structured_output`
    alongside session bookkeeping fields.
    """
    return {
        "result": f"Reviewed: {prompt}",
        "session_id": "sess-ci-0001",
        "usage": {"input_tokens": 4200, "output_tokens": 380},
        "structured_output": findings,
    }


def validate_against_schema(structured_output, schema: dict) -> bool:
    if schema["type"] == "array":
        if not isinstance(structured_output, list):
            return False
        required = schema["items"]["required"]
        return all(
            isinstance(item, dict) and all(key in item for key in required)
            for item in structured_output
        )
    raise ValueError(f"Unsupported schema type: {schema['type']}")


# ---------------------------------------------------------------------------
# Step 3: Session isolation -- same-session review is biased
# ---------------------------------------------------------------------------

def generate(code_request: str):
    """Simulate code generation plus the reasoning that justified it."""
    code = f"# implementation for: {code_request}\ndef handler(): pass"
    reasoning = (
        "Chose a minimal handler with no input validation because the caller "
        "is assumed to be trusted internal code, and skipped auth checks "
        "since this endpoint is only reachable from the internal network."
    )
    return code, reasoning


_ALL_ISSUES = [
    "no input validation on handler",
    "missing auth check before handler executes",
    "no logging on failure path",
]


def review_same_session(code: str, generation_reasoning: str) -> list:
    """A reviewer sharing the generation session's reasoning is biased
    toward accepting the justifications it already produced -- issues that
    reasoning explicitly rationalized get suppressed.
    """
    flagged = []
    for issue in _ALL_ISSUES:
        rationalized = any(
            keyword in generation_reasoning.lower()
            for keyword in issue.lower().split()[:3]
        )
        if not rationalized:
            flagged.append(issue)
    return flagged


def review_independent_session(code: str) -> list:
    """A reviewer with no access to the generation session's reasoning
    evaluates the code purely on its own merits.
    """
    return list(_ALL_ISSUES)


# ---------------------------------------------------------------------------
# Step 4: Incremental review -- avoid re-reporting unfixed issues as noise
# ---------------------------------------------------------------------------

def full_review(current_findings: list) -> list:
    """Naive baseline: dumps every current finding every run, with no
    notion of what was already reported.
    """
    return list(current_findings)


def incremental_review(current_findings: list, previous_findings: list) -> dict:
    """Report only genuinely new issues plus previously-flagged issues that
    are still present. Issues that were in `previous_findings` but are no
    longer in `current_findings` were fixed and must not be re-reported.
    """
    current_set = set(current_findings)
    previous_set = set(previous_findings)
    new_issues = sorted(current_set - previous_set)
    still_present = sorted(current_set & previous_set)
    fixed = sorted(previous_set - current_set)
    return {"new": new_issues, "still_present": still_present, "fixed": fixed}


# ---------------------------------------------------------------------------
# Step 5: Batch API vs. real-time API
# ---------------------------------------------------------------------------

@dataclass
class Workflow:
    name: str
    is_blocking: bool
    is_time_sensitive: bool


def choose_api(workflow: Workflow) -> str:
    """Blocking, time-sensitive work (developers waiting to merge) needs
    real-time. The Batch API has no latency SLA (up to 24h), so it is only
    appropriate for non-blocking, schedule-tolerant workflows.
    """
    if workflow.is_blocking or workflow.is_time_sensitive:
        return "realtime"
    return "batch"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # --- Step 1: -p is the only real fix ----------------------------------
    hanging = validate_ci_command(["claude", "Analyze this PR"])
    assert hanging["would_hang"], "Missing -p should be flagged as hanging."
    print("[HANG] `claude \"Analyze this PR\"` with no -p flag: would_hang=True (waits for interactive input forever).")

    fixed = validate_ci_command(["claude", "-p", "Analyze this PR"])
    assert fixed["ci_safe"] and not fixed["would_hang"]
    print("[FIX] `claude -p \"Analyze this PR\"`: ci_safe=True.")

    decoy_env = validate_ci_command(["claude", "Analyze this PR"], env={"CLAUDE_HEADLESS": "true"})
    assert decoy_env["would_hang"], "CLAUDE_HEADLESS is not a real flag -- must still hang."
    decoy_flag = validate_ci_command(["claude", "--batch", "Analyze this PR"])
    assert decoy_flag["would_hang"], "--batch is not a real flag -- must still hang."
    decoy_stdin = validate_ci_command(["claude", "Analyze this PR", "< /dev/null"])
    assert decoy_stdin["would_hang"], "stdin redirection does not fix interactive mode -- must still hang."
    print("[DECOYS] CLAUDE_HEADLESS=true, --batch, and `< /dev/null` all fail to prevent hanging -- only -p works.")

    # --- Step 2: structured output validates against schema ---------------
    good_findings = [{"file": "auth.py", "line": 42, "severity": "high", "message": "missing check"}]
    bad_findings = [{"file": "auth.py", "line": 42, "message": "missing severity field"}]

    envelope = run_headless("Review auth.py", good_findings)
    assert validate_against_schema(envelope["structured_output"], FINDINGS_SCHEMA)
    print(f"[SCHEMA] well-formed structured_output validates: {envelope['structured_output']}")

    bad_envelope = run_headless("Review auth.py", bad_findings)
    assert not validate_against_schema(bad_envelope["structured_output"], FINDINGS_SCHEMA)
    print("[SCHEMA] malformed structured_output (missing 'severity') correctly fails validation.")

    # --- Step 3: independent review is unbiased ----------------------------
    code, reasoning = generate("internal admin handler")
    same_session_flags = review_same_session(code, reasoning)
    independent_flags = review_independent_session(code)
    assert len(independent_flags) > len(same_session_flags), (
        "Independent review must flag strictly more issues than a same-session "
        "review that inherited the generator's own justifications."
    )
    print(f"[BIAS] same-session review flagged {len(same_session_flags)} issue(s): {same_session_flags}")
    print(f"[UNBIASED] independent-session review flagged {len(independent_flags)} issue(s): {independent_flags}")

    # --- Step 4: incremental review eliminates duplicate noise -------------
    previous = ["missing auth check", "no rate limiting", "unclear error message"]
    current = ["missing auth check", "no rate limiting", "SQL string concatenation"]
    # "unclear error message" was fixed; "SQL string concatenation" is new;
    # the other two are still present and should not be re-reported as new.

    naive = full_review(current)
    assert naive == current, "Naive full review just dumps every current finding, every time."

    delta = incremental_review(current, previous)
    assert delta["new"] == ["SQL string concatenation"]
    assert delta["still_present"] == ["missing auth check", "no rate limiting"]
    assert delta["fixed"] == ["unclear error message"]
    print(f"[INCREMENTAL] new: {delta['new']}, still present: {delta['still_present']}, "
          f"fixed (no longer reported): {delta['fixed']}")
    print(f"[NAIVE] full_review would re-dump all {len(naive)} current findings every run, "
          f"with no distinction between new and already-seen issues.")

    # --- Step 5: real-time vs batch selection -------------------------------
    pre_merge_check = Workflow(name="pre-merge PR check", is_blocking=True, is_time_sensitive=True)
    overnight_debt_report = Workflow(name="overnight tech-debt report", is_blocking=False, is_time_sensitive=False)

    assert choose_api(pre_merge_check) == "realtime", (
        "Blocking pre-merge checks cannot tolerate Batch API's up-to-24h, no-SLA latency."
    )
    assert choose_api(overnight_debt_report) == "batch", (
        "Non-blocking, schedule-tolerant work should use Batch API for the 50% cost saving."
    )
    print(f"[API] '{pre_merge_check.name}' -> {choose_api(pre_merge_check)} "
          f"(developers are blocked waiting; Batch API's lack of latency SLA is disqualifying).")
    print(f"[API] '{overnight_debt_report.name}' -> {choose_api(overnight_debt_report)} "
          f"(not time-sensitive; Batch API's 50% cost saving applies).")

    print("\n[ALL TESTS PASSED]")
