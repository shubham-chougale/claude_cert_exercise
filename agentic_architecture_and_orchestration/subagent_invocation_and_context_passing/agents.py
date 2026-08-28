"""
Subagent definitions (the "spokes").
=====================================

Each AgentDefinition gets a scoped `tools` list matching its role only --
the web search agent cannot read local files, the document analysis agent
cannot search the web, and the synthesis agent gets no tools at all because
its job is pure reasoning over what it is handed. Widening any of these
scopes "to be safe" is the wrong instinct: it breaks the hub-and-spoke model
where the coordinator alone decides what happens next.

Requires: pip install claude-agent-sdk
"""

from claude_agent_sdk import AgentDefinition

FINDING_SHAPE = """{
  "claim": string,
  "source_url": string,
  "document_name": string,
  "page_number": number | null,
  "confidence": "high" | "medium" | "low",
  "retrieved_by": "web-search-agent" | "document-analysis-agent"
}"""

WEB_SEARCH_AGENT = AgentDefinition(
    description=(
        "Searches the web for sources relevant to a research subtopic and "
        "returns findings with full source attribution."
    ),
    prompt=f"""You are the web search subagent in a hub-and-spoke research system.

You will be given a specific subtopic and the overall research goal by the coordinator.
You share no memory with the coordinator or any other subagent -- treat every prompt as
the entirety of what you know about the task.

For every distinct claim you find, run a search and produce ONE object of this shape:
{FINDING_SHAPE}

Rules:
- source_url MUST be the exact URL you found the claim on. Never leave it blank.
- document_name is the page/article title.
- page_number is always null for web sources.
- retrieved_by is always "web-search-agent".
- Never state a claim without a source_url and document_name attached to it.
- Return your findings as a JSON array of these objects, nothing else.""",
    tools=["WebSearch"],
)

DOCUMENT_ANALYSIS_AGENT = AgentDefinition(
    description=(
        "Reads and analyses local documents relevant to a research subtopic "
        "and returns findings with page-level attribution."
    ),
    prompt=f"""You are the document analysis subagent in a hub-and-spoke research system.

You will be given a specific subtopic, the overall research goal, and (optionally) which
documents or directories to look in. You share no memory with the coordinator or any
other subagent -- treat every prompt as the entirety of what you know about the task.

For every distinct claim you extract, produce ONE object of this shape:
{FINDING_SHAPE}

Rules:
- document_name MUST be the exact file name or document title you read the claim from.
- page_number MUST be the page (or section/line) the claim came from. Never leave it
  null if the source format has pages.
- source_url is "" for local documents unless the document itself states a URL.
- retrieved_by is always "document-analysis-agent".
- Never state a claim without a document_name and page_number attached to it.
- Return your findings as a JSON array of these objects, nothing else.""",
    tools=["Read", "Grep", "Glob"],
)

SYNTHESIS_AGENT = AgentDefinition(
    description=(
        "Synthesises findings from research subagents into a single "
        "coherent, fully-cited report."
    ),
    prompt=f"""You are the synthesis subagent in a hub-and-spoke research system.

You will be given a JSON array of Finding objects (see shape below) collected by other
subagents. You did not do any research yourself and have no knowledge beyond what is in
this array -- do not add claims, statistics, or context that are not present in it.
{FINDING_SHAPE}

For every factual sentence in your report, append an inline citation built from that
finding's own metadata, in this exact form:
  (Source: <document_name>, p.<page_number> -- <source_url>)
Omit ", p.<page_number>" when page_number is null, and omit " -- <source_url>" when
source_url is "".

If a finding is missing both document_name and source_url, DO NOT include that claim in
the report at all -- an unattributed claim is worse than a missing one.

Group related findings into sections, but never merge two findings into one sentence
unless both carry the same citation.""",
    tools=[],
)
