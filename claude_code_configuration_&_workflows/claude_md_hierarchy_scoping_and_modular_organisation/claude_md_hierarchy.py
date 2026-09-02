"""
CLAUDE.md Hierarchy, Scoping, and Modular Organisation
===================================================================

Demonstrates the exam's "new team member gets inconsistent behaviour"
scenario:

  Developer A has worked on the team for months; Claude Code follows the
  team's API naming conventions perfectly for them. Developer B joins,
  clones the SAME repo and branch, and Claude ignores those conventions.

  Root cause: the conventions live in Developer A's user-level config
  (~/.claude/CLAUDE.md), which is personal and NEVER travels through git.
  Only project-level config (.claude/CLAUDE.md or root CLAUDE.md) and
  directory-level CLAUDE.md files are version-controlled and shared.

This module simulates a filesystem (a plain dict of path -> content, no
real Claude Code process) to demonstrate, precisely:

  1. CLAUDE.md files at different scopes CONCATENATE into context in a
     documented load order (user, then project, then directory-level,
     broadest to most specific) -- they do NOT override each other, and
     contradictions resolve arbitrarily. This is fundamentally different
     from settings.json, which has a strict precedence chain and IS
     enforced by the client.
  2. `@relative/path` import syntax inlines a referenced file's content
     eagerly at load time -- splitting a CLAUDE.md into imports does not
     reduce what's loaded into context.
  3. CLAUDE.local.md loads after CLAUDE.md at the same level (a load-order
     fact, not a precedence claim) and is the personal, gitignored
     counterpart to a shared CLAUDE.md.
  4. Two developers with an identical project tree but different
     user-level configs get different effective context -- and moving the
     convention to project-level is what actually fixes it.
  5. /memory and /context are diagnostic only: they report what already
     loaded, they never change what loads.
"""

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Step 1: A tiny simulated filesystem -- dict of absolute path -> content.
# Two "developers" share the identical project tree but differ only in
# their personal, non-version-controlled user-level file.
# ---------------------------------------------------------------------------

PROJECT_ROOT = "/repo"
WORKING_DIR = "/repo/packages/api"

SHARED_PROJECT_FILES = {
    "/repo/CLAUDE.md": "# Project standards\nUse conventional commits.\n",
    "/repo/packages/api/CLAUDE.md": "# API package\nREST endpoints return {data, error}.\n",
}

DEVELOPER_A_FS = {
    **SHARED_PROJECT_FILES,
    "~/.claude/CLAUDE.md": "# Personal (Developer A)\nNaming convention: camelCase for all endpoint params.\n",
}

DEVELOPER_B_FS = {
    **SHARED_PROJECT_FILES,
    # Developer B never wrote the convention -- it only ever existed in A's
    # personal, un-shared file, so B's filesystem simply doesn't have it.
}


# ---------------------------------------------------------------------------
# Step 2: CLAUDE.md loading -- concatenation in documented order, NOT
# precedence. User-level first (broadest), then project root, then each
# directory level down to the working directory (most specific last).
# ---------------------------------------------------------------------------

def _directory_chain(project_root: str, working_dir: str) -> list:
    """Directories from project_root down to working_dir, inclusive."""
    rel = working_dir[len(project_root):].strip("/")
    parts = rel.split("/") if rel else []
    chain = [project_root]
    current = project_root
    for part in parts:
        current = f"{current}/{part}"
        chain.append(current)
    return chain


def load_claude_md_context(fs: dict, working_dir: str, project_root: str = PROJECT_ROOT) -> str:
    """Concatenate every applicable CLAUDE.md (and CLAUDE.local.md) into one
    context string, in documented load order: user-level first, then
    project root, then each directory down to working_dir. Files are
    CONCATENATED -- later content does not erase earlier content, unlike a
    precedence system.
    """
    sections = []

    user_md = fs.get("~/.claude/CLAUDE.md")
    if user_md:
        sections.append(user_md)

    for directory in _directory_chain(project_root, working_dir):
        md_path = f"{directory}/CLAUDE.md"
        if md_path in fs:
            sections.append(fs[md_path])
        local_path = f"{directory}/CLAUDE.local.md"
        if local_path in fs:
            # Loads after CLAUDE.md at the same level -- appended, not merged in place.
            sections.append(fs[local_path])

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Step 3: settings.json -- a genuinely different system. Strict precedence,
# client-enforced, higher scope WINS (overrides), it does not concatenate.
# ---------------------------------------------------------------------------

SETTINGS_PRECEDENCE = ("managed", "local", "project", "user")  # highest first


def resolve_settings_precedence(settings_by_scope: dict, key: str):
    """Unlike CLAUDE.md, settings.json has a strict precedence chain that
    the client enforces regardless of anything Claude decides: managed >
    local > project > user. The first scope (in that order) that defines
    the key wins outright -- lower scopes are discarded, not concatenated.
    """
    for scope in SETTINGS_PRECEDENCE:
        if key in settings_by_scope.get(scope, {}):
            return settings_by_scope[scope][key], scope
    return None, None


# ---------------------------------------------------------------------------
# Step 4: @ path imports -- eager, recursive inlining at load time.
# ---------------------------------------------------------------------------

def expand_imports(content: str, fs: dict, base_dir: str) -> str:
    """Replace each `@relative/path` reference with the referenced file's
    content, resolved relative to base_dir. Eager and recursive: imported
    files may themselves contain imports, resolved relative to THEIR OWN
    directory. This does NOT shrink what's loaded into context -- it only
    changes where the text is authored.
    """
    lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("@"):
            rel_path = stripped[1:]
            import_path = f"{base_dir}/{rel_path}".replace("/./", "/")
            imported = fs.get(import_path, f"[MISSING IMPORT: {import_path}]")
            import_dir = import_path.rsplit("/", 1)[0]
            lines.append(expand_imports(imported, fs, import_dir))
        else:
            lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Step 5: /memory and /context are diagnostic-only -- they report state,
# they never cause anything to load.
# ---------------------------------------------------------------------------

def diagnose(fs: dict, working_dir: str) -> str:
    """Stand-in for /memory or /context: purely read-only inspection of
    what load_claude_md_context() would produce. Calling this must not
    change the result of a subsequent real load.
    """
    return load_claude_md_context(fs, working_dir)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # --- Step 2: concatenation order -----------------------------------
    context_a = load_claude_md_context(DEVELOPER_A_FS, WORKING_DIR)
    assert "Personal (Developer A)" in context_a
    assert "Project standards" in context_a
    assert "API package" in context_a
    user_idx = context_a.index("Personal (Developer A)")
    project_idx = context_a.index("Project standards")
    dir_idx = context_a.index("API package")
    assert user_idx < project_idx < dir_idx, (
        "Load order must be user-level, then project root, then directory-level -- broadest to most specific."
    )
    print("[PASS] CLAUDE.md context concatenates in documented order: user -> project root -> directory-level.")

    # --- Step 2: concatenation, not override -- both root and dir content survive
    assert "Project standards" in context_a and "API package" in context_a, (
        "Directory-level CLAUDE.md must not erase project-root CLAUDE.md -- files concatenate."
    )
    print("[PASS] directory-level CLAUDE.md does not override project-root CLAUDE.md -- both are present.")

    # --- Step 3: settings.json has real precedence, unlike CLAUDE.md -----
    settings = {
        "user": {"theme": "dark", "auto_approve": True},
        "project": {"auto_approve": False},
        "managed": {},
        "local": {},
    }
    value, winning_scope = resolve_settings_precedence(settings, "auto_approve")
    assert value is False and winning_scope == "project", (
        "settings.json must resolve by strict precedence -- project overrides user outright."
    )
    theme_value, theme_scope = resolve_settings_precedence(settings, "theme")
    assert theme_value == "dark" and theme_scope == "user"
    print(f"[PASS] settings.json 'auto_approve' resolved via strict precedence: "
          f"project ({value}) overrides user (True) -- the user-level value is discarded, not concatenated.")
    print("[CONTRAST] CLAUDE.md concatenates every applicable file; settings.json enforces a "
          "strict override chain (managed > local > project > user). Use settings.json/hooks for mandatory rules.")

    # --- Step 4: @ imports inline eagerly, recursively --------------------
    fs_with_import = {
        "/repo/CLAUDE.md": "Coding standards:\n@./standards/naming-conventions.md\n",
        "/repo/standards/naming-conventions.md": "Use snake_case for Python, camelCase for TS.\n@./error-handling.md",
        "/repo/standards/error-handling.md": "Always wrap external calls in try/except.",
    }
    expanded = expand_imports(fs_with_import["/repo/CLAUDE.md"], fs_with_import, "/repo")
    assert "snake_case for Python" in expanded, "@ import must inline the referenced file's content."
    assert "try/except" in expanded, "Nested @ imports inside an imported file must also expand recursively."
    print("[PASS] @./standards/naming-conventions.md inlined eagerly at load time, including its own nested import.")

    # --- Step 3 (CLAUDE.local.md): appended after same-level CLAUDE.md ---
    fs_with_local = {
        "/repo/CLAUDE.md": "# Project standards\nUse conventional commits.",
        "/repo/CLAUDE.local.md": "# Personal notes\nPrefer verbose diffs for me.",
    }
    local_context = load_claude_md_context(fs_with_local, "/repo")
    assert local_context.index("Project standards") < local_context.index("Personal notes"), (
        "CLAUDE.local.md must load after CLAUDE.md at the same level."
    )
    print("[PASS] CLAUDE.local.md loads after CLAUDE.md at the same level -- personal notes appended, not merged in.")

    # --- Step 5: the exam's "new team member" scenario --------------------
    context_a = load_claude_md_context(DEVELOPER_A_FS, WORKING_DIR)
    context_b = load_claude_md_context(DEVELOPER_B_FS, WORKING_DIR)
    project_only_a = load_claude_md_context({k: v for k, v in DEVELOPER_A_FS.items() if k in SHARED_PROJECT_FILES}, WORKING_DIR)
    project_only_b = load_claude_md_context({k: v for k, v in DEVELOPER_B_FS.items() if k in SHARED_PROJECT_FILES}, WORKING_DIR)
    assert project_only_a == project_only_b, "Both developers share an identical project-level tree."
    assert context_a != context_b, (
        "Developer A and B must diverge -- A's naming convention lives only in A's personal, unshared user-level file."
    )
    assert "camelCase for all endpoint params" in context_a
    assert "camelCase for all endpoint params" not in context_b
    print("[PASS] root cause reproduced: identical project files, but Developer A's naming convention "
          "(stored in ~/.claude/CLAUDE.md) never reaches Developer B, who cloned the same repo/branch.")

    # --- Step 5: the fix -- move the convention to project-level ----------
    fixed_fs_a = {**{k: v for k, v in DEVELOPER_A_FS.items() if k != "~/.claude/CLAUDE.md"}}
    fixed_fs_a["/repo/packages/api/CLAUDE.md"] += "\nNaming convention: camelCase for all endpoint params.\n"
    fixed_fs_b = {**DEVELOPER_B_FS, "/repo/packages/api/CLAUDE.md": fixed_fs_a["/repo/packages/api/CLAUDE.md"]}
    fixed_context_a = load_claude_md_context(fixed_fs_a, WORKING_DIR)
    fixed_context_b = load_claude_md_context(fixed_fs_b, WORKING_DIR)
    assert "camelCase for all endpoint params" in fixed_context_a
    assert "camelCase for all endpoint params" in fixed_context_b
    print("[FIX] moving the convention from ~/.claude/CLAUDE.md to the version-controlled "
          "/repo/packages/api/CLAUDE.md makes it reach both developers identically.")

    # --- Step 6: /memory and /context are read-only diagnostics -----------
    before = load_claude_md_context(DEVELOPER_A_FS, WORKING_DIR)
    _ = diagnose(DEVELOPER_A_FS, WORKING_DIR)  # simulate running /memory or /context
    after = load_claude_md_context(DEVELOPER_A_FS, WORKING_DIR)
    assert before == after, "/memory and /context must be purely diagnostic -- they never change what loads."
    print("[PASS] running a diagnostic (/memory or /context) does not alter subsequent loaded context -- "
          "it only reports what already loaded automatically based on file location.")

    print("\n[ALL TESTS PASSED]")
