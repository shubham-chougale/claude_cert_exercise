"""
Iterative Refinement Techniques -- Steering Claude Code Toward Desired Output
===============================================================================

Demonstrates the exam's technique hierarchy for steering an LLM's output when
the first attempt doesn't land:

  1. PROSE vs. CONCRETE EXAMPLES -- when a prose instruction is interpreted
     differently on different runs, the fix is not more prose (more precise
     wording still relies on interpretation); it is 2-3 concrete before/after
     example pairs, which the model generalizes from far more reliably.
  2. TEST-DRIVEN ITERATION -- for complex transformations with many edge
     cases, "Expected X, got Y" test failures give unambiguous feedback that
     requires no interpretation at all.
  3. THE INTERVIEW PATTERN -- in an unfamiliar domain, asking Claude to pose
     clarifying questions before implementing surfaces requirements (TTL
     policy, invalidation strategy, consistency guarantees) that a direct
     implementation silently skips.
  4. BATCH vs. SEQUENTIAL FEEDBACK -- interdependent review issues must be
     delivered together (a later fix can invalidate an earlier one if applied
     in isolation); independent issues converge to the same result either way.

This module is self-contained: a deterministic simulated "model" stands in
for a real LLM call in each of the four sections, so the structural
difference between techniques can be verified precisely instead of asserted
by anecdote.
"""

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Step 1: Prose instructions vs. concrete examples
# ---------------------------------------------------------------------------

# A vague prose instruction: "wrap return types in a Result type for error
# handling". Three structurally different (and mutually incompatible)
# interpretations a model might settle on across separate runs -- exactly the
# "inconsistent interpretation" symptom the exam describes.
_PROSE_INTERPRETATIONS = [
    lambda t: f"Promise<Result<{t}, Error>>",
    lambda t: f"Result<{t}>",
    lambda t: f"{t} | {{ error: string }}",
]


def apply_prose_instruction(return_type: str, run_index: int) -> str:
    """Simulates asking a model to apply a vague prose instruction. Each run
    picks a different interpretation -- the model has no anchor to converge
    on, so the shape of the output varies run to run.
    """
    render = _PROSE_INTERPRETATIONS[run_index % len(_PROSE_INTERPRETATIONS)]
    return render(return_type)


# The correct pattern, established with 2-3 concrete before/after pairs.
EXAMPLES = [
    ("UserData", "Result<UserData, ApiError>"),
    ("OrderSummary", "Result<OrderSummary, ApiError>"),
]


def apply_with_examples(return_type: str, examples: list) -> str:
    """Simulates a model that has generalized the pattern from concrete
    examples: given ANY new type, it applies the exact same transformation
    every time -- no interpretation, no drift.
    """
    return f"Result<{return_type}, ApiError>"


# ---------------------------------------------------------------------------
# Step 2: Test-driven iteration -- unambiguous "Expected X, got Y" feedback
# ---------------------------------------------------------------------------

@dataclass
class TestCase:
    name: str
    input: object
    expected: object


TEST_CASES = [
    TestCase("happy_path", {"id": 1, "name": "Ada"}, {"id": 1, "name": "Ada"}),
    TestCase("null_value", {"id": 2, "name": None}, {"id": 2, "name": None}),
    TestCase("empty_input", {}, {}),
    TestCase("boundary_zero_id", {"id": 0, "name": "Zero"}, {"id": 0, "name": "Zero"}),
]


def buggy_migrate(record: dict) -> dict:
    # Bug: silently replaces None with "" instead of preserving it.
    return {k: ("" if v is None else v) for k, v in record.items()}


def fixed_migrate(record: dict) -> dict:
    return dict(record)


@dataclass
class TestFailure:
    name: str
    message: str


def run_tests(transform) -> list:
    failures = []
    for case in TEST_CASES:
        got = transform(case.input)
        if got != case.expected:
            failures.append(TestFailure(
                name=case.name,
                message=f"FAIL: {case.name}\n  Expected: {case.expected!r}\n  Actual: {got!r}",
            ))
    return failures


# ---------------------------------------------------------------------------
# Step 3: The interview pattern -- unfamiliar domains
# ---------------------------------------------------------------------------

CLARIFYING_QUESTIONS = [
    "What TTL policy should cached entries use?",
    "How should the cache be invalidated on writes?",
    "What consistency guarantee is required (strong vs. eventual)?",
    "What should happen on a cache-backend failure?",
]


def direct_implementation(request: str) -> list:
    """Proceeds immediately with only the defaults a generic implementation
    would assume -- silently skips domain-specific requirements an expert
    would have asked about.
    """
    return ["basic get/set caching", "in-memory storage"]


def interview_then_implement(request: str, answers: dict) -> list:
    """Asks clarifying questions first, then folds every answered
    requirement into the implementation -- surfaces exactly the
    considerations direct_implementation silently skipped.
    """
    addressed = ["basic get/set caching", "in-memory storage"]
    for question in CLARIFYING_QUESTIONS:
        if question in answers:
            addressed.append(f"addressed: {question} -> {answers[question]}")
    return addressed


# ---------------------------------------------------------------------------
# Step 4: Batch vs. sequential feedback
# ---------------------------------------------------------------------------

@dataclass
class Issue:
    key: str
    fix: str
    depends_on: list = field(default_factory=list)  # keys of issues this one's fix assumes are already applied


# error_handling, logging_format, and type_definitions are interdependent:
# the logging fix assumes the error-handling shape is already in place, and
# the type-definitions fix assumes both are in place. style_naming is
# independent of all three. A real review tool reports issues in the order
# it finds them in the file -- not in dependency order -- so type_definitions
# (which depends on the other two) is listed FIRST here.
INTERDEPENDENT_ISSUES = [
    Issue("type_definitions", "type return values as Result<T, E>", depends_on=["error_handling", "logging_format"]),
    Issue("logging_format", "log Result.error field on failure", depends_on=["error_handling"]),
    Issue("error_handling", "wrap errors in Result<T, E>"),
]

INDEPENDENT_ISSUES = [
    Issue("style_naming", "rename getData to fetchData"),
    Issue("unused_import", "remove unused lodash import"),
]


def apply_feedback(issues: list, mode: str) -> dict:
    """Simulates applying a set of review issues either as one batch
    (all context available at once, so a fix can account for its
    dependencies) or sequentially (each fix applied in isolation, unaware of
    fixes not yet seen).
    """
    applied = {}
    if mode == "batch":
        # All issues are visible together, so each fix is applied with full
        # awareness of every dependency, regardless of dependency order.
        for issue in issues:
            applied[issue.key] = {"fix": issue.fix, "dependencies_seen": list(issue.depends_on)}
    elif mode == "sequential":
        # Each issue is fixed in isolation; a fix can only see issues that
        # were already applied earlier in the sequence, so any dependency
        # that appears LATER in the list is missed.
        applied_so_far = []
        for issue in issues:
            dependencies_seen = [dep for dep in issue.depends_on if dep in applied_so_far]
            applied[issue.key] = {"fix": issue.fix, "dependencies_seen": dependencies_seen}
            applied_so_far.append(issue.key)
    else:
        raise ValueError(f"unknown mode: {mode}")
    return applied


def is_consistent(applied: dict, issues: list) -> bool:
    """An end-state is consistent only if every issue's fix was applied with
    full awareness of every dependency it declared.
    """
    for issue in issues:
        seen = applied[issue.key]["dependencies_seen"]
        if set(seen) != set(issue.depends_on):
            return False
    return True


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # --- Step 1: prose is inconsistent, examples are not ------------------
    prose_outputs = {apply_prose_instruction("UserData", i) for i in range(6)}
    assert len(prose_outputs) >= 2, "Prose instruction should produce inconsistent output across runs."
    print(f"[PROSE] 6 runs of the same prose instruction produced {len(prose_outputs)} distinct "
          f"shapes: {sorted(prose_outputs)}")

    example_outputs = {apply_with_examples("UserData", EXAMPLES) for _ in range(6)}
    assert len(example_outputs) == 1, "With concrete examples, output must be identical every run."
    print(f"[EXAMPLES] 6 runs with 2 concrete before/after pairs all converged on: "
          f"{next(iter(example_outputs))}")

    # --- Step 2: test-driven iteration gives unambiguous feedback ---------
    buggy_failures = run_tests(buggy_migrate)
    assert buggy_failures, "Buggy transform should fail at least one test."
    assert any(f.name == "null_value" for f in buggy_failures)
    print(f"[TDD] buggy_migrate failed {len(buggy_failures)} test(s), including:\n  " +
          buggy_failures[0].message.replace("\n", "\n  "))

    fixed_failures = run_tests(fixed_migrate)
    assert not fixed_failures, "Fixed transform should pass every test case."
    print(f"[TDD] fixed_migrate passes all {len(TEST_CASES)} test cases "
          f"(happy path, null, empty, boundary).")

    # --- Step 3: interview pattern surfaces more requirements -------------
    direct = direct_implementation("build a caching layer for the API")
    interviewed = interview_then_implement("build a caching layer for the API", {
        q: "answered" for q in CLARIFYING_QUESTIONS
    })
    assert len(interviewed) > len(direct), (
        "Interview pattern should address strictly more requirements than a direct implementation."
    )
    print(f"[INTERVIEW] direct_implementation addressed {len(direct)} requirement(s); "
          f"interview_then_implement addressed {len(interviewed)} after asking "
          f"{len(CLARIFYING_QUESTIONS)} clarifying questions.")

    # --- Step 4: batch vs. sequential on interdependent issues -------------
    batch_result = apply_feedback(INTERDEPENDENT_ISSUES, "batch")
    sequential_result = apply_feedback(INTERDEPENDENT_ISSUES, "sequential")
    assert is_consistent(batch_result, INTERDEPENDENT_ISSUES), (
        "Batch feedback should produce a consistent end-state for interdependent issues."
    )
    assert not is_consistent(sequential_result, INTERDEPENDENT_ISSUES), (
        "Sequential feedback should miss forward dependencies for interdependent issues."
    )
    print("[BATCH] interdependent issues (error_handling -> logging_format -> type_definitions): "
          "batch fixing is consistent; sequential fixing misses forward-declared dependencies "
          "and is NOT consistent.")

    # --- Step 4b: batch vs. sequential on independent issues ---------------
    batch_independent = apply_feedback(INDEPENDENT_ISSUES, "batch")
    sequential_independent = apply_feedback(INDEPENDENT_ISSUES, "sequential")
    assert is_consistent(batch_independent, INDEPENDENT_ISSUES)
    assert is_consistent(sequential_independent, INDEPENDENT_ISSUES)
    print("[SEQUENTIAL] independent issues (style_naming, unused_import): both batch and "
          "sequential fixing converge to the same consistent result.")

    print("\n[ALL TESTS PASSED]")
