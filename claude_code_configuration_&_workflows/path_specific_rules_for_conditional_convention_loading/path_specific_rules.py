"""
Path-Specific Rules for Conditional Convention Loading
===================================================================

Demonstrates the exam's "50+ scattered test directories" scenario:

  A project has test files co-located with source across 50+ directories
  (components, api, utils, pages). Every test file must follow identical
  conventions. Two naive fixes both fail:

    - Directory-level CLAUDE.md in every directory: 50+ copies of the
      same conventions, a maintenance burden, and convention drift as
      updates propagate inconsistently.
    - Root-level CLAUDE.md holding the conventions: always loaded for
      EVERY session regardless of what's being edited, so tokens burn
      "even while you're editing React components" that have nothing to
      do with testing.

  The fix is `.claude/rules/*.md`: a single file with YAML frontmatter
  `paths: [...]` glob patterns. The rule's body loads ONLY when a
  currently-edited file matches one of its patterns -- one file, glob
  coverage across the whole tree, and zero cost on sessions that never
  touch a matching path.

This module simulates glob-based conditional loading, compares token
cost against the two naive strategies, and demonstrates the separate
"rules vs skills" distinction the exam also tests: rules are passive,
path-triggered background guidance; skills are on-demand, invoked
procedures. Everything here is simulated in-memory (fnmatch-based glob
matching over Python data) -- no real Claude Code session is involved.
"""

from dataclasses import dataclass, field
from fnmatch import fnmatch


# ---------------------------------------------------------------------------
# Step 1: Rule files -- each has glob patterns and a body (its "tokens")
# ---------------------------------------------------------------------------

@dataclass
class Rule:
    name: str
    paths: list
    body: str

    @property
    def tokens(self) -> int:
        return len(self.body.split())


RULES = [
    Rule(
        name="test-conventions",
        paths=["*.test.ts", "*.test.tsx", "*.spec.ts", "*.spec.tsx"],
        body=(
            "Use describe/it blocks with descriptive names reading as sentences. "
            "Each test file must have a happy path and an error case. Use factory "
            "functions for test data, not inline literals. Mock external services "
            "at the module boundary. Assert behavior, not implementation details."
        ),
    ),
    Rule(
        name="api-conventions",
        paths=["src/api/*", "*routes*", "*.controller.ts"],
        body=(
            "All endpoints return a {data, error, metadata} response shape. Use "
            "Zod schemas for request validation at the handler boundary. Log the "
            "request ID on every error response. Rate limiting must be explicit, "
            "not inherited."
        ),
    ),
    Rule(
        name="infra-conventions",
        paths=["terraform/*", "*.tf", "infrastructure/*"],
        body=(
            "State files must reference remote backends. Use workspaces for "
            "environment separation. Every module must be versioned with a "
            "CHANGELOG."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Step 2: Conditional loading -- fnmatch-based glob activation
# ---------------------------------------------------------------------------

def _matches_any(path: str, patterns: list) -> bool:
    return any(fnmatch(path, f"*{p}" if not p.startswith("*") else p) or fnmatch(path, p)
               for p in patterns)


def load_active_rules(rules: list, files_being_edited: list) -> list:
    """Return only the rules whose glob patterns match at least one of the
    files currently being edited -- everything else stays out of context.
    """
    active = []
    for rule in rules:
        if any(_matches_any(f, rule.paths) for f in files_being_edited):
            active.append(rule)
    return active


# ---------------------------------------------------------------------------
# Step 3: Token-cost comparison -- path-specific rules vs. the two naive fixes
# ---------------------------------------------------------------------------

# All conventions combined into one always-loaded root CLAUDE.md.
ROOT_CLAUDE_MD_TOKENS = sum(rule.tokens for rule in RULES)

# Directory-level CLAUDE.md: the test-conventions body duplicated into every
# one of 50+ scattered test directories -- a maintenance count, not a
# per-session token cost (each directory's copy only loads when you're in
# that directory, but every copy must be kept in sync by hand).
SCATTERED_TEST_DIRECTORIES = 50


@dataclass
class SessionCostReport:
    root_claude_md_tokens: int
    path_specific_rule_tokens: int
    directory_level_files_to_maintain: int
    path_specific_files_to_maintain: int


def compare_strategies(files_being_edited: list) -> SessionCostReport:
    active = load_active_rules(RULES, files_being_edited)
    path_specific_tokens = sum(rule.tokens for rule in active)
    return SessionCostReport(
        root_claude_md_tokens=ROOT_CLAUDE_MD_TOKENS,
        path_specific_rule_tokens=path_specific_tokens,
        directory_level_files_to_maintain=SCATTERED_TEST_DIRECTORIES,
        path_specific_files_to_maintain=1,
    )


# ---------------------------------------------------------------------------
# Step 4: Rules vs. skills -- passive path-triggered guidance vs. invoked
# on-demand procedures
# ---------------------------------------------------------------------------

@dataclass
class Item:
    name: str
    kind: str  # "rule" or "skill"
    triggered_by: str  # "path" or "invocation"
    requires_explicit_run: bool


def classify(item: Item) -> str:
    """Rules stay in context as passive background guidance the moment a
    matching path is being edited -- no invocation step. Skills are
    multi-step procedures that must be explicitly invoked (by command name
    or intent match) before they run.
    """
    if item.triggered_by == "path" and not item.requires_explicit_run:
        return "rule"
    if item.requires_explicit_run:
        return "skill"
    return "unknown"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # --- Step 2: glob activation is conditional on the files being edited ---
    active_for_test_edit = load_active_rules(RULES, ["src/components/Button.test.tsx"])
    assert [r.name for r in active_for_test_edit] == ["test-conventions"], (
        "Editing a .test.tsx file should activate only the test-conventions rule."
    )
    print(f"[ACTIVE] editing Button.test.tsx -> {[r.name for r in active_for_test_edit]}")

    active_for_tf_edit = load_active_rules(RULES, ["terraform/network/main.tf"])
    assert [r.name for r in active_for_tf_edit] == ["infra-conventions"], (
        "Editing a .tf file should activate only the infra-conventions rule."
    )
    print(f"[ACTIVE] editing main.tf -> {[r.name for r in active_for_tf_edit]}")

    active_for_component_edit = load_active_rules(RULES, ["src/components/Button.tsx"])
    assert active_for_component_edit == [], (
        "Editing a plain component file (no test, no api, no infra) should activate no rules."
    )
    print(f"[ACTIVE] editing Button.tsx (no matching rule) -> {active_for_component_edit}")

    # --- Step 3: path-specific rules beat root-CLAUDE.md on a components-only session
    report = compare_strategies(["src/components/Button.tsx", "src/components/Card.tsx"])
    assert report.path_specific_rule_tokens == 0, (
        "A components-only editing session should load zero rule tokens -- nothing matches."
    )
    assert report.path_specific_rule_tokens < report.root_claude_md_tokens, (
        "Path-specific rules must load strictly fewer tokens than a root CLAUDE.md "
        "that always loads every convention regardless of what's being edited."
    )
    print(f"[COST] components-only session: root CLAUDE.md would cost "
          f"{report.root_claude_md_tokens} tokens every time; path-specific rules cost "
          f"{report.path_specific_rule_tokens} tokens (nothing matched).")

    assert report.directory_level_files_to_maintain == 50
    assert report.path_specific_files_to_maintain == 1
    print(f"[MAINTENANCE] directory-level CLAUDE.md requires keeping "
          f"{report.directory_level_files_to_maintain} copies in sync; "
          f"path-specific rules require maintaining {report.path_specific_files_to_maintain} file.")

    # A session that DOES touch a test file still only pays for that one rule,
    # not the whole root CLAUDE.md.
    test_session = compare_strategies(["src/utils/helpers.test.ts"])
    assert test_session.path_specific_rule_tokens == RULES[0].tokens
    assert test_session.path_specific_rule_tokens < ROOT_CLAUDE_MD_TOKENS
    print(f"[COST] test-editing session: path-specific rules cost "
          f"{test_session.path_specific_rule_tokens} tokens (test-conventions only) vs. "
          f"{ROOT_CLAUDE_MD_TOKENS} tokens for a root CLAUDE.md holding every convention.")

    # --- Step 4: rules vs. skills classification ---------------------------
    test_rule_item = Item(
        name="test-conventions",
        kind="rule",
        triggered_by="path",
        requires_explicit_run=False,
    )
    brainstorm_skill_item = Item(
        name="brainstorm",
        kind="skill",
        triggered_by="invocation",
        requires_explicit_run=True,
    )
    assert classify(test_rule_item) == "rule", (
        "Path-triggered background guidance with no invocation step is a rule."
    )
    assert classify(brainstorm_skill_item) == "skill", (
        "A multi-step procedure that must be explicitly invoked is a skill, "
        "not a rule -- matching a path alone is not enough to run it."
    )
    print(f"[CLASSIFY] '{test_rule_item.name}' -> {classify(test_rule_item)}; "
          f"'{brainstorm_skill_item.name}' -> {classify(brainstorm_skill_item)}")

    print("\n[ALL TESTS PASSED]")
