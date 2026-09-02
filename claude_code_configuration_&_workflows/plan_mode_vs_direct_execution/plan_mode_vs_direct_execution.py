"""
Plan Mode vs Direct Execution -- Ambiguity, Not Difficulty, Decides the Mode
=============================================================================

Demonstrates the exam's core distinction:

  Claude Code offers two execution modes. Plan mode explores the codebase,
  analyses dependencies, and proposes an approach WITHOUT modifying files.
  Direct execution skips that phase and makes changes straight away.

  The decision criterion is AMBIGUITY LEVEL, not task difficulty. A hard
  but well-understood bug fix is still direct execution. A simple-sounding
  task with several genuinely different valid implementations needs plan
  mode -- picking the wrong one costs a rewrite, not a retry.

This module simulates three things with plain, deterministic Python (no
real Claude Code invocation):

  1. `choose_mode(task)` -- a decision function driven only by information
     available when the task is FIRST described (scope, whether the
     approach is already known, how many valid approaches exist, whether
     it's architectural). It returns "plan", "direct", or
     "plan_then_direct" -- the hybrid used for large but pattern-consistent
     migrations: explore/design once, then apply the pattern file by file.
  2. The Explore subagent pattern -- isolating verbose discovery output
     (file listings, dependency graphs) into a subagent summary instead of
     dumping it into the main conversation, measured in simulated tokens.
  3. The "decide late" trap -- a task whose requirements already state
     multiple valid approaches upfront must be classified "plan" from
     that information alone, not after a simulated failed attempt.
"""

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Step 1: Task description and the mode-choice decision function
# ---------------------------------------------------------------------------

@dataclass
class Task:
    name: str
    scope: str              # "single-file" or "multi-file"
    approach_known: bool    # is the fix/location/approach already identified?
    num_valid_approaches: int
    architectural: bool     # service boundaries, module dependencies, API contracts
    files_affected: int = 1


def choose_mode(task: Task) -> str:
    """Ambiguity, not difficulty, drives this decision. A task is only
    "direct" when its scope is a single file AND the approach is already
    known AND there's exactly one valid way to do it. Architectural work,
    or work with more than one genuinely valid approach, needs plan mode
    first. A large multi-file job that nonetheless has ONE known,
    consistent pattern to apply is the hybrid: plan once, then execute
    file by file.
    """
    if task.architectural or task.num_valid_approaches > 1:
        return "plan"
    if task.scope == "single-file" and task.approach_known:
        return "direct"
    if task.scope == "multi-file" and task.approach_known and task.num_valid_approaches == 1:
        return "plan_then_direct"
    return "plan"


TASKS = [
    Task(
        name="Restructure monolith into microservices",
        scope="multi-file", approach_known=False, num_valid_approaches=3,
        architectural=True, files_affected=120,
    ),
    Task(
        name="Fix null pointer exception, single function, clear stack trace",
        scope="single-file", approach_known=True, num_valid_approaches=1,
        architectural=False, files_affected=1,
    ),
    Task(
        name="Migrate logging library across 30 files, one consistent API mapping",
        scope="multi-file", approach_known=True, num_valid_approaches=1,
        architectural=False, files_affected=30,
    ),
]


# ---------------------------------------------------------------------------
# Step 2: Explore subagent -- isolate verbose discovery output
# ---------------------------------------------------------------------------

@dataclass
class ExploreSummary:
    files_scanned: int
    entry_points: list
    dependency_notes: str


# Simulated per-file cost of exploration output, in "tokens", if it were
# dumped directly into the main conversation (full file listings, import
# graphs, matched line context).
_TOKENS_PER_FILE_RAW_DUMP = 150
_SUMMARY_TOKEN_COST = 40  # fixed cost of the subagent's returned summary


def explore_with_subagent(files_to_scan: list) -> tuple:
    """Runs discovery over `files_to_scan` "inside a subagent": the raw,
    per-file exploration cost is paid there and never reaches the main
    conversation. Only a small fixed-size summary crosses back. Returns
    (summary, main_context_tokens_used).
    """
    summary = ExploreSummary(
        files_scanned=len(files_to_scan),
        entry_points=[f for f in files_to_scan if f.endswith("_service.py")],
        dependency_notes=f"{len(files_to_scan)} files scanned; entry points identified.",
    )
    return summary, _SUMMARY_TOKEN_COST


def explore_with_direct_dump(files_to_scan: list) -> tuple:
    """Same underlying exploration work, but every file's discovery output
    is dumped straight into the main conversation -- the anti-pattern.
    """
    main_context_tokens = len(files_to_scan) * _TOKENS_PER_FILE_RAW_DUMP
    summary = ExploreSummary(
        files_scanned=len(files_to_scan),
        entry_points=[f for f in files_to_scan if f.endswith("_service.py")],
        dependency_notes=f"{len(files_to_scan)} files scanned; entry points identified.",
    )
    return summary, main_context_tokens


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # --- Step 1: ambiguity, not difficulty, decides the mode -------------
    expected_modes = {
        "Restructure monolith into microservices": "plan",
        "Fix null pointer exception, single function, clear stack trace": "direct",
        "Migrate logging library across 30 files, one consistent API mapping": "plan_then_direct",
    }
    for task in TASKS:
        mode = choose_mode(task)
        assert mode == expected_modes[task.name], (
            f"{task.name!r} should choose {expected_modes[task.name]!r}, got {mode!r}"
        )
        print(f"[MODE] {task.name}: {mode}")

    # A DIFFICULT but well-understood single-file fix must still be "direct" --
    # difficulty (many lines, tricky logic) is not in the decision function at all.
    hard_but_known = Task(
        name="Rewrite a gnarly 200-line parsing function, root cause already found",
        scope="single-file", approach_known=True, num_valid_approaches=1, architectural=False,
    )
    assert choose_mode(hard_but_known) == "direct", (
        "Difficulty alone must not push a well-understood single-file task into plan mode."
    )
    print("[TRAP AVOIDED] a difficult but well-understood single-file fix still resolves to 'direct'.")

    # A SIMPLE-SOUNDING but multi-approach feature must still be "plan" --
    # ambiguity (multiple valid approaches), not apparent simplicity, drives this.
    simple_sounding = Task(
        name="Add caching to the API layer",
        scope="single-file", approach_known=False, num_valid_approaches=3, architectural=False,
    )
    assert choose_mode(simple_sounding) == "plan", (
        "Multiple valid approaches must force plan mode even for a simple-sounding, small-scope task."
    )
    print("[TRAP AVOIDED] a simple-sounding task with 3 valid approaches still resolves to 'plan'.")

    # --- Trap: decide from upfront requirements, not a mid-task retry signal --
    # choose_mode must classify correctly using only info known at task creation --
    # no "attempt, fail, then switch to plan" step exists in the function at all.
    stated_upfront = Task(
        name="Feature statable 3 different ways, stated upfront",
        scope="single-file", approach_known=False, num_valid_approaches=3, architectural=False,
    )
    assert choose_mode(stated_upfront) == "plan", (
        "A task whose multiple valid approaches are already stated must resolve to 'plan' immediately."
    )
    print("[TRAP AVOIDED] complexity stated upfront resolves to 'plan' on the first classification -- "
          "no failed direct-execution attempt was needed to discover it.")

    # --- Step 2: Explore subagent preserves the main context window ------
    files = [f"module_{i}_service.py" if i % 5 == 0 else f"module_{i}.py" for i in range(30)]

    subagent_summary, subagent_tokens = explore_with_subagent(files)
    direct_summary, direct_tokens = explore_with_direct_dump(files)

    assert subagent_summary.files_scanned == direct_summary.files_scanned == 30
    assert subagent_summary.entry_points == direct_summary.entry_points, (
        "Both exploration paths must find the same entry points -- only where the tokens land differs."
    )
    assert subagent_tokens < direct_tokens, (
        "Routing discovery through the Explore subagent must use fewer main-context tokens "
        "than dumping every scanned file's output directly into the conversation."
    )
    print(f"[EXPLORE] same exploration ({direct_summary.files_scanned} files, "
          f"{len(direct_summary.entry_points)} entry points found either way): "
          f"direct dump costs {direct_tokens} main-context tokens, "
          f"Explore subagent costs {subagent_tokens} -- "
          f"{direct_tokens - subagent_tokens} tokens preserved for implementation.")

    print("\n[ALL TESTS PASSED]")
