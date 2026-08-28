"""
Context-Passing Research Coordinator
=====================================

Demonstrates structured context passing across subagent boundaries using the
Claude Agent SDK's spawning primitives.

Key requirement (exam-tested, binary): the coordinator's `allowed_tools` MUST
include "Task" (the current name is "Agent" -- Task still works as an alias).
Task is the hard gate for subagent spawning. Without it, `options.agents`
can be fully defined and it will not matter: the coordinator has no way to
invoke any of them.

Pipeline:
  1. Coordinator spawns web-search-agent AND document-analysis-agent for
     independent subtopics -- via two Task tool calls emitted in the SAME
     assistant turn, not two sequential turns. That is the whole latency
     win: independent subagents have nothing to wait on each other for.
  2. Both subagents return Finding objects (see types.py) -- content and
     source metadata travel together, never as bare strings.
  3. The coordinator passes the COMPLETE, unmodified findings array to
     synthesis-agent. This is the step the exam is really testing: if the
     coordinator summarises, flattens, or drops metadata fields here, the
     synthesis agent will produce unattributed claims no matter how its own
     prompt is worded. The bug is always upstream of the agent that "looks"
     broken.
  4. We verify both properties mechanically: (a) were the two research
     agents actually spawned in parallel, and (b) does every factual
     sentence in the final report carry a citation.

fork_session vs. parallel Task calls (conceptual, not exercised in code
here): fork_session branches an existing conversation into independent
copies that diverge from a shared baseline and never see each other again --
it is for exploring alternative strategies from one analysis. Parallel Task
calls spawn brand-new, purpose-built subagents with no shared history at
all, to do independent pieces of ONE task concurrently. Forking answers
"what if I tried it two ways from here?"; parallel spawning answers "how do
I get two unrelated pieces of work done at once?"

Requires: pip install claude-agent-sdk
Run:      python coordinator.py "the environmental and economic tradeoffs of offshore wind farms"
"""

import asyncio
import re
import sys

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from agents import DOCUMENT_ANALYSIS_AGENT, SYNTHESIS_AGENT, WEB_SEARCH_AGENT

COORDINATOR_SYSTEM_PROMPT = """\
You are the Research Coordinator, the hub in a hub-and-spoke multi-agent
research system. You do no research yourself -- you decompose, delegate,
and pass context.

1. Split the incoming topic into two independent subtopics: one suited to
   web search, one suited to document analysis.
2. Invoke web-search-agent and document-analysis-agent for their subtopics
   IN THE SAME TURN -- emit both Task tool calls together. They do not
   depend on each other's output, so there is no reason to wait.
3. Each subagent returns a JSON array of Finding objects. Do not summarise,
   reformat, or drop any field from these objects.
4. Invoke synthesis-agent exactly once, passing it the FULL, UNMODIFIED
   findings arrays from both subagents concatenated together. If you strip
   source_url, document_name, or page_number before handing findings to
   synthesis-agent, its report will contain unattributed claims -- that
   failure is always caused by what you pass, never by synthesis-agent's
   own instructions.
5. Return synthesis-agent's report as your final answer, unchanged.
"""


async def run_research(topic: str) -> str:
    options = ClaudeAgentOptions(
        system_prompt=COORDINATOR_SYSTEM_PROMPT,
        # Task (aka Agent) is the hard gate for subagent spawning. The
        # coordinator has no other tools -- it only orchestrates.
        allowed_tools=["Task"],
        agents={
            "web-search-agent": WEB_SEARCH_AGENT,
            "document-analysis-agent": DOCUMENT_ANALYSIS_AGENT,
            "synthesis-agent": SYNTHESIS_AGENT,
        },
    )

    prompt = (
        f'Research this topic and produce a fully-cited report: "{topic}". '
        "Assign one subtopic to web-search-agent and a related subtopic to "
        "document-analysis-agent."
    )

    task_calls_by_turn: dict[int, list[str]] = {}
    turn = 0
    final_report = ""

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            turn += 1
            for block in message.content:
                if isinstance(block, ToolUseBlock) and block.name == "Task":
                    agent_name = block.input.get("subagent_type") or block.input.get(
                        "description", "unknown-agent"
                    )
                    task_calls_by_turn.setdefault(turn, []).append(agent_name)
        elif isinstance(message, ResultMessage):
            final_report = message.result or ""

    verify_parallel_spawn(task_calls_by_turn)
    verify_attribution(final_report)

    return final_report


def verify_parallel_spawn(task_calls_by_turn: dict[int, list[str]]) -> None:
    """Confirms web-search-agent and document-analysis-agent were spawned
    in the same assistant turn, not across two sequential turns."""
    parallel_turn = next(
        (
            (turn, agents)
            for turn, agents in task_calls_by_turn.items()
            if len(agents) >= 2
        ),
        None,
    )
    if parallel_turn:
        turn, agents = parallel_turn
        print(f"[OK] Parallel spawn confirmed in turn {turn}: {', '.join(agents)}")
    else:
        print(
            "[WARN] Subagents were spawned sequentially across separate turns -- "
            "check the coordinator's system prompt for step 2."
        )


CLAIM_VERB_PATTERN = re.compile(
    r"\b(is|are|was|were|shows?|found|increased?|decreased?|reduces?|causes?|grew|fell)\b",
    re.IGNORECASE,
)
CITATION_PATTERN = re.compile(r"\(Source:.*?\)")


def verify_attribution(report: str) -> None:
    """Confirms every factual sentence in the final report carries a
    (Source: ...) citation traceable back to a Finding's metadata."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", report) if s.strip()]
    unattributed = [
        s for s in sentences if CLAIM_VERB_PATTERN.search(s) and not CITATION_PATTERN.search(s)
    ]
    if not unattributed:
        print("[OK] Attribution check passed: every factual sentence is cited.")
    else:
        print(f"[WARN] {len(unattributed)} sentence(s) found without a citation:")
        for s in unattributed:
            print(f"   - {s}")


if __name__ == "__main__":
    topic = (
        " ".join(sys.argv[1:])
        or "the environmental and economic tradeoffs of offshore wind farms"
    )
    report = asyncio.run(run_research(topic))
    print("\n--- FINAL REPORT ---\n")
    print(report)
