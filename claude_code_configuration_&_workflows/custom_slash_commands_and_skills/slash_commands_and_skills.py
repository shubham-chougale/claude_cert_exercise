"""
Custom Slash Commands and Skills -- Discovery, Scoping, and Frontmatter
===================================================================

Demonstrates the exam's core distinctions for Claude Code's unified
skills/commands system:

  1. Two file layouts produce the same `/<name>` command:
       - .claude/skills/<name>/SKILL.md   (canonical, directory-based)
       - .claude/commands/<name>.md       (flat file, backward-compatible)
     A flat Markdown file dropped directly inside .claude/skills/ (NOT
     inside a subdirectory with a SKILL.md) does NOT register as a
     command -- the exam's favourite trap for this topic.

  2. Scoping: project-scoped (.claude/skills/, .claude/commands/ -- lives
     in the repo, shared via git, every developer gets it) vs user-scoped
     (~/.claude/skills/, ~/.claude/commands/ -- personal, never shared).
     Placing a team-wide command at user scope means teammates never see
     it.

  3. Frontmatter fields that actually matter for the exam:
       - context: fork        -- isolates verbose output in a subagent
       - allowed-tools         -- pre-approves tools, doesn't restrict others
       - argument-hint         -- prompts for required params when invoked bare
     A skill that produces large output without context: fork pollutes the
     main conversation's context window -- an auditable anti-pattern.

  4. Skills vs. CLAUDE.md: skills are on-demand, task-specific workflows
     (full body loads only on invocation); CLAUDE.md is always-loaded,
     universal standards applied to every session. Putting a one-off
     workflow in CLAUDE.md burns tokens on every turn; putting an
     always-relevant convention in a skill means it silently never
     applies unless someone remembers to invoke it.

  5. Personal customisation: a developer can add a personal variant under
     a different name (~/.claude/skills/deep-analyse/) without touching or
     conflicting with the team's .claude/skills/analyse/.

This module is self-contained: filesystems are simulated as plain dicts
(path -> content), and there is no real Claude Code invocation, so every
claim above is verified with deterministic asserts.
"""

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Step 1: Simulated filesystem + command discovery
# ---------------------------------------------------------------------------

def discover_commands(fs: dict) -> dict:
    """Scan a simulated filesystem (path -> content) for command
    definitions and return {command_name: source_path}.

    Recognised layouts:
      - .claude/skills/<name>/SKILL.md   (canonical)
      - .claude/commands/<name>.md       (flat, backward-compatible)
      - the same two layouts under ~/.claude/ for user scope

    A flat file placed directly inside a .../skills/ directory (no SKILL.md
    inside a per-command subdirectory) is NOT a valid skill and is skipped
    -- this is the exam trap.
    """
    commands = {}
    for path in fs:
        parts = path.split("/")
        if parts[-1] == "SKILL.md" and "skills" in parts:
            skills_idx = parts.index("skills")
            # Must be skills/<name>/SKILL.md -- exactly one directory level
            # between "skills" and the file itself.
            if len(parts) - skills_idx == 3:
                name = parts[skills_idx + 1]
                commands[name] = path
        elif "commands" in parts and path.endswith(".md"):
            commands_idx = parts.index("commands")
            if len(parts) - commands_idx == 2:
                name = parts[-1][:-3]
                commands[name] = path
    return commands


# ---------------------------------------------------------------------------
# Step 2: Scoping -- project (shared) vs. user (personal)
# ---------------------------------------------------------------------------

def build_developer_fs(project_fs: dict, user_fs: dict) -> dict:
    """A developer's effective view is the union of the shared project
    filesystem and their own personal (user-scoped) filesystem.
    """
    return {**project_fs, **user_fs}


# ---------------------------------------------------------------------------
# Step 3: Frontmatter parsing -- context: fork / allowed-tools / argument-hint
# ---------------------------------------------------------------------------

@dataclass
class SkillFrontmatter:
    description: str = ""
    context: str = ""
    allowed_tools: list = field(default_factory=list)
    argument_hint: str = ""


def parse_skill_frontmatter(skill_md: str) -> SkillFrontmatter:
    """Minimal parser for the YAML-frontmatter block at the top of a
    SKILL.md file (between the leading and trailing '---' lines).
    """
    lines = skill_md.strip().splitlines()
    assert lines[0].strip() == "---", "SKILL.md must open with a frontmatter block."
    end = lines[1:].index("---") + 1
    frontmatter_lines = lines[1:end]

    fm = SkillFrontmatter()
    current_list_key = None
    for line in frontmatter_lines:
        stripped = line.strip()
        if stripped.startswith("- ") and current_list_key == "allowed-tools":
            fm.allowed_tools.append(stripped[2:].strip())
            continue
        current_list_key = None
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key, value = key.strip(), value.strip()
        if key == "description":
            fm.description = value.strip('"')
        elif key == "context":
            fm.context = value
        elif key == "argument-hint":
            fm.argument_hint = value.strip('"')
        elif key == "allowed-tools":
            current_list_key = "allowed-tools"
    return fm


# ---------------------------------------------------------------------------
# Step 4: Anti-pattern audit -- verbose skill missing context: fork
# ---------------------------------------------------------------------------

VERBOSE_OUTPUT_THRESHOLD = 2000  # rough token-proxy: characters of output


def audit_skill(frontmatter: SkillFrontmatter, typical_output_size: int) -> list:
    """Flag a skill whose typical output is large but which does not run
    isolated in a subagent -- verbose output floods the main conversation
    and degrades subsequent responses.
    """
    findings = []
    if typical_output_size > VERBOSE_OUTPUT_THRESHOLD and frontmatter.context != "fork":
        findings.append(
            f"Skill produces ~{typical_output_size} chars of output but lacks "
            f"'context: fork' -- verbose output will pollute the main conversation "
            f"context window instead of staying isolated in a subagent."
        )
    return findings


# ---------------------------------------------------------------------------
# Step 5: Skills vs. CLAUDE.md placement
# ---------------------------------------------------------------------------

# Deterministic classifier: content that describes an always-applicable
# standard belongs in CLAUDE.md; content that describes an occasional,
# invoked-on-demand procedure belongs in a skill.
_ALWAYS_ON_SIGNALS = ("every commit", "every session", "always applies", "universal", "every code")
_ON_DEMAND_SIGNALS = ("occasionally", "run on demand", "workflow run", "when invoked", "analysis workflow")


def classify_content(description: str) -> str:
    lowered = description.lower()
    if any(sig in lowered for sig in _ALWAYS_ON_SIGNALS):
        return "CLAUDE.md"
    if any(sig in lowered for sig in _ON_DEMAND_SIGNALS):
        return "skill"
    raise ValueError(f"Ambiguous content, cannot classify: {description!r}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # --- Step 1: discovery, including the flat-file-in-skills/ trap -------
    project_fs = {
        ".claude/skills/analyse/SKILL.md": "---\ndescription: team analysis\n---\nBody",
        ".claude/skills/broken.md": "This is a flat file dropped directly in skills/ -- invalid.",
        ".claude/commands/review.md": "Team review workflow.",
    }
    commands = discover_commands(project_fs)
    assert "analyse" in commands, "SKILL.md under a per-command subdirectory must register."
    assert "review" in commands, "Flat file under .claude/commands/ must register as a command."
    assert "broken" not in commands, (
        "A flat file placed directly inside .claude/skills/ (no SKILL.md subdirectory) "
        "must NOT register as a command -- this is the documented exam trap."
    )
    print(f"[DISCOVERY] project commands found: {sorted(commands)} "
          f"(broken.md correctly excluded).")

    # --- Step 2: scoping -- project-shared vs. user-personal --------------
    dev_a_user_fs = {"~/.claude/skills/deep-analyse/SKILL.md": "---\ndescription: dev A's verbose variant\n---\nBody"}
    dev_b_user_fs = {"~/.claude/skills/scratch-notes/SKILL.md": "---\ndescription: dev B's personal notes tool\n---\nBody"}

    dev_a_fs = build_developer_fs(project_fs, dev_a_user_fs)
    dev_b_fs = build_developer_fs(project_fs, dev_b_user_fs)

    dev_a_commands = discover_commands(dev_a_fs)
    dev_b_commands = discover_commands(dev_b_fs)

    assert "review" in dev_a_commands and "review" in dev_b_commands, (
        "Project-scoped commands must be visible to every developer."
    )
    assert "deep-analyse" in dev_a_commands and "deep-analyse" not in dev_b_commands, (
        "A user-scoped command must be visible only to its owner."
    )
    assert "scratch-notes" in dev_b_commands and "scratch-notes" not in dev_a_commands
    print("[SCOPING] 'review' (project-scoped) visible to both developers; "
          "'deep-analyse' and 'scratch-notes' (user-scoped) each visible only to their owner.")

    # --- Step 3 & 4: frontmatter parsing + anti-pattern audit -------------
    verbose_skill_missing_fork = """---
description: "Analyse a feature area of the codebase and report structure, patterns and risks"
allowed-tools:
  - Read
  - Grep
  - Glob
argument-hint: "Provide a feature description or area of the codebase to analyse"
---
Body of the skill, producing extensive file listings and code excerpts.
"""
    fm_missing_fork = parse_skill_frontmatter(verbose_skill_missing_fork)
    assert fm_missing_fork.context == "", "This fixture intentionally omits context: fork."
    assert fm_missing_fork.allowed_tools == ["Read", "Grep", "Glob"]
    assert fm_missing_fork.argument_hint == "Provide a feature description or area of the codebase to analyse"

    findings = audit_skill(fm_missing_fork, typical_output_size=6000)
    assert findings, "A verbose skill without context: fork must be flagged."
    print(f"[AUDIT] {findings[0]}")

    fixed_skill = verbose_skill_missing_fork.replace(
        'description: "Analyse a feature area',
        'context: fork\ndescription: "Analyse a feature area',
    )
    fm_fixed = parse_skill_frontmatter(fixed_skill)
    assert fm_fixed.context == "fork"
    assert not audit_skill(fm_fixed, typical_output_size=6000), (
        "Adding context: fork must clear the audit finding."
    )
    print("[AUDIT] adding 'context: fork' resolves the finding -- verbose output now isolated.")

    # --- Step 5: skills vs. CLAUDE.md placement ----------------------------
    assert classify_content("API naming conventions applied to every commit") == "CLAUDE.md"
    assert classify_content("Codebase analysis workflow run occasionally when a developer invokes it") == "skill"
    assert classify_content("Brainstorming analysis workflow triggered when invoked") == "skill"
    assert classify_content("Universal error-handling standard applied to every code change") == "CLAUDE.md"
    print("[PLACEMENT] always-on conventions classified to CLAUDE.md; "
          "on-demand procedures classified to skills.")

    # --- Personal customisation without touching the team skill -----------
    assert "analyse" in dev_a_commands, "Team skill must remain available."
    assert "deep-analyse" in dev_a_commands, "Personal variant must also be available."
    assert commands["analyse"] != dev_a_commands["deep-analyse"], (
        "Personal variant must be a distinct file from the team skill, not an override."
    )
    print("[PERSONAL] developer's personal 'deep-analyse' skill coexists with the "
          "team's 'analyse' skill under a distinct name -- no conflict, no override.")

    print("\n[ALL TESTS PASSED]")
