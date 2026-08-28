"""
Session State and Resumption
==============================

Demonstrates the exam's three session-management options and when each
is correct:

  - resume: continue an existing named session. Correct when NOTHING has
    changed underneath it -- the session's tool-call history still
    accurately reflects the world.
  - fork_session: branch an existing session to explore a DIVERGENT path
    while keeping the original intact and its full context. Not a fix for
    stale data -- it inherits the same stale tool results as the parent.
  - fresh start + structured summary injection: the correct choice once
    files have changed underneath a session. A resumed session still
    contains the OLD tool results (file contents) in its history, so the
    agent reasons from data that no longer matches reality -- the "stale
    context problem". A fresh session carries no tool-result history, so
    injecting a structured summary of prior findings plus an explicit list
    of what changed lets the agent do a TARGETED re-analysis of only the
    changed files, without re-exploring the whole codebase from scratch.

This module is self-contained (deterministic rule-based "analysis" instead
of a real LLM call) so the stale-context failure and its fix can be
verified precisely end to end.
"""

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# A small codebase with three known issues, to be discovered and then fixed
# ---------------------------------------------------------------------------

_ORIGINAL_FILES = {
    "file_01.py": "def add(a, b):\n    return a + b\n",
    "file_02.py": "def load(path):\n    try:\n        return open(path).read()\n    except:\n        return None\n",
    "file_03.py": "def mul(a, b):\n    return a * b\n",
    "file_04.py": "def sub(a, b):\n    return a - b\n",
    "file_05.py": "def run():\n    # TODO: replace with real config loader\n    return {}\n",
    "file_06.py": "def div(a, b):\n    return a / b\n",
    "file_07.py": "def noop():\n    pass\n",
    "file_08.py": "def query(user_input):\n    return f\"SELECT * FROM users WHERE name = '{user_input}'\"\n",
    "file_09.py": "def identity(x):\n    return x\n",
    "file_10.py": "def greet(name):\n    return f'hello {name}'\n",
}

# Fixed versions of the three files that actually have issues.
_FIXED_FILES = dict(_ORIGINAL_FILES)
_FIXED_FILES["file_02.py"] = (
    "def load(path):\n    try:\n        return open(path).read()\n"
    "    except OSError:\n        return None\n"
)
_FIXED_FILES["file_05.py"] = "def run():\n    return load_config_from_disk()\n"
_FIXED_FILES["file_08.py"] = (
    "def query(user_input):\n    return \"SELECT * FROM users WHERE name = %s\", (user_input,)\n"
)

CHANGED_FILES = ["file_02.py", "file_05.py", "file_08.py"]


# ---------------------------------------------------------------------------
# Deterministic rule-based "analysis" (stands in for an LLM code review)
# ---------------------------------------------------------------------------

def _analyze_file(name: str, content: str) -> Optional[dict]:
    if "except:" in content:
        return {"file": name, "issue": "bare except clause", "severity": "medium",
                 "recommendation": "catch a specific exception type"}
    if "TODO" in content:
        return {"file": name, "issue": "leftover TODO / stub implementation", "severity": "low",
                 "recommendation": "implement the real config loader"}
    if "SELECT * FROM users WHERE name = '" in content:
        return {"file": name, "issue": "SQL injection risk via f-string interpolation",
                 "severity": "high", "recommendation": "use parameterised queries"}
    return None


# ---------------------------------------------------------------------------
# Step 1: Create a named session and analyze the codebase
# ---------------------------------------------------------------------------

@dataclass
class ToolResult:
    """A tool call's result as it would sit in session history -- a frozen
    snapshot of what the file contained AT CALL TIME."""
    file: str
    content: str


@dataclass
class Session:
    name: str
    tool_results: dict = field(default_factory=dict)   # file -> ToolResult (stale after edits)
    findings: dict = field(default_factory=dict)        # file -> finding dict


def create_named_session(name: str, files: dict) -> Session:
    """Analyzes every file once and records both the raw tool results
    (file reads) and the derived findings -- exactly what a real session's
    history would contain after a full-codebase review.
    """
    session = Session(name=name)
    for fname, content in files.items():
        session.tool_results[fname] = ToolResult(file=fname, content=content)
        finding = _analyze_file(fname, content)
        if finding:
            session.findings[fname] = finding
    return session


# ---------------------------------------------------------------------------
# Step 2: Structured summary -- the knowledge to carry forward
# ---------------------------------------------------------------------------

@dataclass
class StructuredSummary:
    entries: list  # list of finding dicts

    def render(self) -> str:
        lines = ["## Prior findings"]
        for f in self.entries:
            lines.append(
                f"- {f['file']}: {f['issue']} (severity={f['severity']}) "
                f"-> recommendation: {f['recommendation']}"
            )
        return "\n".join(lines)


def record_structured_summary(session: Session) -> StructuredSummary:
    return StructuredSummary(entries=list(session.findings.values()))


# ---------------------------------------------------------------------------
# Step 3: Modify files -- creates the conditions for stale context
# ---------------------------------------------------------------------------

def modify_files(changed: list = CHANGED_FILES) -> dict:
    """Returns the current on-disk contents after the 3 fixes are applied.
    The session created in Step 1 does NOT know about this -- its
    tool_results still hold the pre-fix content.
    """
    return dict(_FIXED_FILES)


# ---------------------------------------------------------------------------
# Step 4: Resume & observe the stale context problem
# ---------------------------------------------------------------------------

def resume_session(session: Session) -> dict:
    """Simulates `--resume`: the agent reasons from the session's EXISTING
    tool_results (the file contents as they were when first read), not
    from the actual current files. If those files have since changed, the
    agent's advice is stale -- it will re-flag issues that have already
    been fixed.
    """
    return {
        fname: _analyze_file(fname, result.content)
        for fname, result in session.tool_results.items()
    }


# ---------------------------------------------------------------------------
# Step 5: Fresh start with injected summary -- targeted re-analysis
# ---------------------------------------------------------------------------

def fresh_start_with_summary(summary: StructuredSummary, changed_files: list, current_files: dict) -> dict:
    """A brand-new session with NO tool-result history. It receives only:
      - the structured summary (prior knowledge, no stale file contents)
      - an explicit list of which files changed

    It re-analyzes ONLY those files, reading their CURRENT content -- never
    the other files in the codebase, and never the old cached content.
    """
    _ = summary  # informs the agent's prior knowledge; doesn't feed stale data
    return {
        fname: _analyze_file(fname, current_files[fname])
        for fname in changed_files
    }


# ---------------------------------------------------------------------------
# fork_session -- divergent exploration, NOT a fix for stale data
# ---------------------------------------------------------------------------

def fork_session(session: Session, branch_name: str) -> Session:
    """Branches a session to explore a different path while preserving the
    original. The fork inherits the SAME tool_results as the parent --
    it is exactly as stale as the parent if files have changed since. This
    is the wrong tool for the stale-context problem; it exists for
    divergent exploration (e.g. trying an alternative fix) while keeping
    the original session available to return to.
    """
    forked = Session(name=branch_name, tool_results=dict(session.tool_results),
                      findings=dict(session.findings))
    return forked


# ---------------------------------------------------------------------------
# Step 6: Compare advice quality
# ---------------------------------------------------------------------------

def compare_advice_quality(resume_result: dict, fresh_result: dict, changed_files: list) -> dict:
    stale_contradictions = [
        fname for fname in changed_files
        if resume_result.get(fname) is not None   # still "finds" the old issue
    ]
    fresh_confirms_fixed = [
        fname for fname in changed_files
        if fresh_result.get(fname) is None        # correctly sees it's fixed
    ]
    return {
        "stale_contradictions": stale_contradictions,
        "fresh_confirms_fixed": fresh_confirms_fixed,
        "fresh_files_analyzed": len(fresh_result),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # --- Step 1: named session analyzes the full codebase --------------------
    assert len(_ORIGINAL_FILES) == 10
    session = create_named_session("codebase-review-v1", _ORIGINAL_FILES)
    assert set(session.findings.keys()) == {"file_02.py", "file_05.py", "file_08.py"}
    print(f"[PASS] named session '{session.name}' found 3 issues across "
          f"{len(_ORIGINAL_FILES)} files: {sorted(session.findings.keys())}")

    # --- Step 2: structured summary preserves findings, not raw file text ---
    summary = record_structured_summary(session)
    rendered = summary.render()
    for fname in ("file_02.py", "file_05.py", "file_08.py"):
        assert fname in rendered
    assert "bare except" in rendered and "TODO" in rendered and "SQL injection" in rendered
    print("[PASS] structured summary lists file, issue, severity, recommendation for all 3 findings.")

    # --- Step 3: modify 3 files -----------------------------------------------
    current_files = modify_files()
    assert current_files["file_02.py"] != _ORIGINAL_FILES["file_02.py"]
    assert _analyze_file("file_02.py", current_files["file_02.py"]) is None
    assert _analyze_file("file_05.py", current_files["file_05.py"]) is None
    assert _analyze_file("file_08.py", current_files["file_08.py"]) is None
    print("[PASS] 3 files substantively modified on disk; all 3 issues actually resolved.")

    # --- Step 4: resume reproduces the stale context problem -----------------
    resumed = resume_session(session)
    assert resumed["file_02.py"] is not None, "Resume should still 'see' the old bare-except (stale tool result)."
    assert resumed["file_05.py"] is not None, "Resume should still flag the already-removed TODO."
    assert resumed["file_08.py"] is not None, "Resume should still flag the already-fixed SQL risk."
    print("[FAIL-STATE DEMONSTRATED] resumed session still reports all 3 issues as unresolved "
          "-- contradicts the actual (fixed) file contents. This is the stale context problem.")

    # --- Step 5: fresh start + summary injection gives accurate, targeted advice
    fresh = fresh_start_with_summary(summary, CHANGED_FILES, current_files)
    assert fresh["file_02.py"] is None
    assert fresh["file_05.py"] is None
    assert fresh["file_08.py"] is None
    assert len(fresh) == 3, "Fresh session must re-analyze ONLY the changed files, not all 10."
    print("[PASS] fresh session with injected summary correctly reports all 3 issues resolved, "
          "analyzing only the 3 changed files (not the full 10-file codebase).")

    # --- fork_session: inherits the SAME staleness as its parent -------------
    forked = fork_session(session, "codebase-review-v1-branch-a")
    forked_result = resume_session(forked)
    assert forked_result == resumed, "fork_session must inherit the parent's (stale) tool results verbatim."
    print("[PASS] fork_session confirmed as divergent-exploration only -- it inherits the same "
          "stale tool results as the parent, so it is NOT a fix for the stale-context problem.")

    # --- Step 6: compare advice quality ----------------------------------------
    comparison = compare_advice_quality(resumed, fresh, CHANGED_FILES)
    assert comparison["stale_contradictions"] == CHANGED_FILES
    assert comparison["fresh_confirms_fixed"] == CHANGED_FILES
    assert comparison["fresh_files_analyzed"] == 3
    print(f"\n[COMPARISON] resume falsely re-flags {comparison['stale_contradictions']} as still broken; "
          f"fresh-start-with-summary correctly confirms {comparison['fresh_confirms_fixed']} are fixed, "
          f"analyzing only {comparison['fresh_files_analyzed']} file(s) instead of re-exploring all 10.")

    print("\n[ALL TESTS PASSED]")
