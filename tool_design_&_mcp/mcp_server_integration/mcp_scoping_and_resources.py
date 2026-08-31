"""
MCP Server Integration -- Scoping, Secrets, Resources, and Build-vs-Use
===================================================================

Demonstrates the exam's core MCP configuration and integration scenarios:

  1. Project-level `.mcp.json` (repo root, version-controlled, shared with
     the whole team -- e.g. Jira, GitHub) vs. user-level `~/.claude.json`
     (home directory, personal, NOT version-controlled -- e.g. an
     experimental server one developer is trying out). Both are merged at
     connection time: SERVER BOUNDARIES ARE INVISIBLE TO THE MODEL. It
     receives one flat list of every tool from every configured server,
     project- and user-level alike.
  2. `${VAR}` environment-variable expansion in `.mcp.json` keeps secrets
     out of version control -- a config committed with a literal token
     instead of `${VAR}` syntax is a credential-leak risk.
  3. MCP Resources expose a content catalogue (e.g. a DB schema) so an
     agent can see what's available WITHOUT spending a tool call --
     resources show agents what data exists; tools let them act on it.
  4. Build vs. use: standard integrations (Jira, GitHub, Slack, Linear,
     Notion) should use an existing community server; building a custom
     server is justified only for proprietary systems or workflows a
     community server genuinely cannot handle.
  5. Sparse MCP tool descriptions ("Searches code") lose out to a
     built-in tool with a richer description, even when the MCP tool is
     otherwise capable -- expanding to 3-5 sentences (capabilities,
     outputs, use cases, comparison to alternatives) fixes this, using
     the same word-overlap "preference" idea as tool_interface_design's
     description router.

This module is self-contained: configs are plain dicts, "resources" and
"tools" are simulated in memory, and preference is a deterministic
word-overlap score -- no real MCP connections or LLM calls are made, so
each behavior can be verified precisely with assertions.
"""

import os
import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Step 1: Project-level vs. user-level config, merged into one flat toolset
# ---------------------------------------------------------------------------

PROJECT_MCP_JSON = {
    # .mcp.json -- repo root, version-controlled, shared with the team
    "mcpServers": {
        "jira": {"command": "npx", "args": ["-y", "jira-mcp-server"], "env": {"JIRA_TOKEN": "${JIRA_TOKEN}"}},
        "github": {"command": "npx", "args": ["-y", "github-mcp-server"], "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"}},
    }
}

USER_CLAUDE_JSON = {
    # ~/.claude.json -- home directory, personal, NOT version-controlled
    "mcpServers": {
        "experimental-search": {"command": "npx", "args": ["-y", "my-experimental-search-server"], "env": {}},
    }
}

# Static tool inventory each server exposes, once connected -- stands in
# for the tools/list response a real MCP server would return.
SERVER_TOOLS = {
    "jira": ["create_issue", "search_issues", "transition_issue"],
    "github": ["create_pr", "list_prs", "merge_pr"],
    "experimental-search": ["fuzzy_search"],
}


def merged_server_names(project_config: dict, user_config: dict) -> set:
    return set(project_config["mcpServers"]) | set(user_config["mcpServers"])


def flat_tool_list(project_config: dict, user_config: dict, server_tools: dict) -> list:
    """The model sees ONE flat list -- it cannot tell, or care, whether a
    tool came from the project-level or user-level config.
    """
    tools = []
    for server in merged_server_names(project_config, user_config):
        tools.extend(server_tools[server])
    return sorted(tools)


# ---------------------------------------------------------------------------
# Step 2: Environment variable expansion + credential-leak audit
# ---------------------------------------------------------------------------

_VAR_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def expand_env_vars(value: str, environ: dict) -> str:
    """Expand ${VAR} references against a supplied environment mapping,
    the way a real MCP client resolves .mcp.json values at load time.
    """
    def _replace(match):
        var_name = match.group(1)
        if var_name not in environ:
            raise KeyError(f"Environment variable {var_name} is not set")
        return environ[var_name]

    return _VAR_PATTERN.sub(_replace, value)


def audit_config_for_leaked_credentials(config: dict) -> list:
    """Flag any env value that looks like a literal secret instead of a
    ${VAR} reference -- the config is committed to version control, so a
    literal token there is a leak, not just bad style.
    """
    findings = []
    for server_name, server in config["mcpServers"].items():
        for key, value in server.get("env", {}).items():
            if not _VAR_PATTERN.fullmatch(value):
                findings.append(
                    f"{server_name}.env.{key} = {value!r} is a literal value, not a ${{VAR}} "
                    f"reference -- committing this leaks a credential into version control."
                )
    return findings


# ---------------------------------------------------------------------------
# Step 3: Resources (see what's available) vs. tools (act on it)
# ---------------------------------------------------------------------------

DB_SCHEMA_RESOURCE = {
    "tables": {
        "customers": ["id", "email", "phone", "created_at"],
        "orders": ["id", "customer_id", "status", "total"],
        "line_items": ["id", "order_id", "sku", "quantity"],
    }
}


def discover_schema_via_exploratory_tool_calls(schema: dict) -> int:
    """Baseline: no resource is exposed, so the agent must spend one tool
    call to list tables, then one more PER TABLE to learn its columns.
    Returns the number of tool calls consumed purely on discovery.
    """
    calls = 1  # list_tables
    calls += len(schema["tables"])  # describe_table, once per table
    return calls


def discover_schema_via_resource(schema: dict) -> int:
    """With the schema exposed as an MCP resource, the agent reads it once
    -- zero tool calls spent on discovery before it can act.
    """
    _ = schema  # the whole catalogue is already visible, no calls needed
    return 0


# ---------------------------------------------------------------------------
# Step 4: Build vs. use
# ---------------------------------------------------------------------------

STANDARD_INTEGRATIONS = {"jira", "github", "slack", "linear", "notion"}


def decide_build_or_use(system_name: str, is_standard: bool, has_custom_workflow: bool) -> str:
    """Standard integrations should use a community server unless the team
    has a genuinely custom workflow a community server can't handle.
    Non-standard (proprietary) systems justify a custom build outright.
    """
    if not is_standard:
        return "build"
    if has_custom_workflow:
        return "build"
    return "use_community"


# ---------------------------------------------------------------------------
# Step 5: Sparse vs. expanded MCP tool descriptions vs. a built-in tool
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "the", "a", "an", "and", "or", "in", "on", "for", "to", "is", "this",
    "that", "of", "by", "with", "using", "up", "as", "such", "than",
    "it", "its", "into", "over",
}


def _words(text: str) -> set:
    return set(re.findall(r"[a-z0-9]+", text.lower())) - _STOPWORDS


BUILTIN_GREP_DESCRIPTION = (
    "Grep searches file contents for a regex pattern across the codebase "
    "and returns matching lines with file paths and line numbers. Use it "
    "to find function callers, error messages, or import statements. "
    "Faster and more precise than reading files manually to locate text."
)

SPARSE_MCP_DESCRIPTION = "Searches code"

EXPANDED_MCP_DESCRIPTION = (
    "Performs AST-aware semantic code search across the repository, "
    "returning matches ranked by structural relevance rather than plain "
    "text position. Understands language syntax, so it finds a function's "
    "callers even across renamed imports or destructured re-exports. "
    "Returns file path, line number, and the enclosing function/class for "
    "each match. Use this instead of grep-style search when you need "
    "semantic understanding of code structure, not just literal text "
    "matches."
)

DEVELOPER_QUERY = (
    "find every caller of this function across renamed imports, ranked by "
    "structural relevance with the enclosing function returned"
)


def preferred_tool(query: str, candidates: dict) -> str:
    query_words = _words(query)
    scores = {name: len(query_words & _words(desc)) for name, desc in candidates.items()}
    return max(scores, key=lambda name: scores[name])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # --- Step 1: merged config produces one flat, server-agnostic list ---
    servers = merged_server_names(PROJECT_MCP_JSON, USER_CLAUDE_JSON)
    assert servers == {"jira", "github", "experimental-search"}
    tools = flat_tool_list(PROJECT_MCP_JSON, USER_CLAUDE_JSON, SERVER_TOOLS)
    assert "create_issue" in tools and "create_pr" in tools and "fuzzy_search" in tools
    assert tools == sorted(tools), "Model receives one flat list -- no per-server grouping."
    print(f"[SCOPING] {len(servers)} servers (project + user) merge into one flat list of "
          f"{len(tools)} tools -- the model cannot see which config a tool came from.")

    # --- Step 2a: ${VAR} expansion resolves against the environment ------
    resolved = expand_env_vars(
        PROJECT_MCP_JSON["mcpServers"]["github"]["env"]["GITHUB_TOKEN"],
        environ={"GITHUB_TOKEN": "ghp_live_token_value"},
    )
    assert resolved == "ghp_live_token_value"
    print("[ENV EXPANSION] '${GITHUB_TOKEN}' resolved from the environment at load time -- "
          "the committed file never contains the real token.")

    # --- Step 2b: safe config has no findings; a leaked-literal config does
    safe_findings = audit_config_for_leaked_credentials(PROJECT_MCP_JSON)
    assert safe_findings == [], "A config using only ${VAR} references should raise no findings."

    LEAKY_CONFIG = {
        "mcpServers": {
            "jira": {"command": "npx", "args": [], "env": {"JIRA_TOKEN": "sk-live-abc123secret"}},
        }
    }
    leaky_findings = audit_config_for_leaked_credentials(LEAKY_CONFIG)
    assert leaky_findings, "A literal token in env (no ${VAR} syntax) must be flagged as a leak risk."
    print(f"[CREDENTIAL AUDIT] safe config: 0 findings. Leaky config: {leaky_findings[0]}")

    # --- Step 3: resource-based discovery costs zero exploratory calls ---
    exploratory_calls = discover_schema_via_exploratory_tool_calls(DB_SCHEMA_RESOURCE)
    resource_calls = discover_schema_via_resource(DB_SCHEMA_RESOURCE)
    assert exploratory_calls == 4, "1 list_tables call + 3 describe_table calls for 3 tables."
    assert resource_calls == 0
    assert resource_calls < exploratory_calls
    print(f"[RESOURCES] tool-call discovery costs {exploratory_calls} calls before the agent can act; "
          f"exposing the schema as a resource costs {resource_calls} -- resources show what's "
          f"available, tools let the agent act on it.")

    # --- Step 4: build-vs-use decision ------------------------------------
    assert decide_build_or_use("jira", is_standard=True, has_custom_workflow=False) == "use_community"
    assert decide_build_or_use("jira", is_standard=True, has_custom_workflow=True) == "build"
    assert decide_build_or_use("proprietary_erp", is_standard=False, has_custom_workflow=False) == "build"
    for name in STANDARD_INTEGRATIONS:
        assert decide_build_or_use(name, is_standard=True, has_custom_workflow=False) == "use_community"
    print("[BUILD VS USE] Jira/GitHub/Slack/Linear/Notion with no custom workflow -> use_community; "
          "a proprietary system, or a standard one with a genuinely custom workflow, -> build.")

    # --- Step 5: sparse MCP description loses to built-in; expanded wins -
    sparse_choice = preferred_tool(DEVELOPER_QUERY, {
        "mcp_code_search": SPARSE_MCP_DESCRIPTION,
        "Grep": BUILTIN_GREP_DESCRIPTION,
    })
    assert sparse_choice == "Grep", "A sparse MCP description should lose to the richer built-in description."

    expanded_choice = preferred_tool(DEVELOPER_QUERY, {
        "mcp_code_search": EXPANDED_MCP_DESCRIPTION,
        "Grep": BUILTIN_GREP_DESCRIPTION,
    })
    assert expanded_choice == "mcp_code_search", (
        "An expanded, specific MCP description should win when it is the better semantic fit."
    )
    print(f"[DESCRIPTION QUALITY] sparse MCP description -> model prefers built-in '{sparse_choice}'; "
          f"expanded 3-5 sentence description -> model correctly prefers '{expanded_choice}'.")

    print("\n[ALL TESTS PASSED]")
