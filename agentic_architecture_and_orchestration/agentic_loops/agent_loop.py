"""
Multi-Tool Agent Loop
======================
A hand-written agentic loop against the Anthropic Messages API.

Demonstrates:
  - Two tools (calculator, web_search stub) with JSON Schema input_schema
  - A while loop driven by response.stop_reason (not content parsing)
  - tool_use handling: execute tool(s), append assistant + tool_result messages
  - end_turn handling: extract final text and exit
  - A MAX_ITERATIONS safety cap that is a fallback, not the primary stop condition
"""

import json
import os

import anthropic

MODEL = "claude-sonnet-4-5-20250929"
MAX_ITERATIONS = 20  # safety cap only -- normal runs must exit via stop_reason well before this

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


# ---------------------------------------------------------------------------
# Step 1: Tool definitions + implementations
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "calculator",
        "description": (
            "Evaluates a basic arithmetic expression and returns the numeric result. "
            "Supports +, -, *, /, parentheses, and decimals. Use this whenever the user "
            "needs a computed number rather than an estimate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "The arithmetic expression to evaluate, e.g. '(3 + 4) * 2'.",
                }
            },
            "required": ["expression"],
        },
    },
    {
        "name": "web_search",
        "description": (
            "Searches the web for a query and returns a short list of mock results. "
            "Use this when the user asks about information you don't already know, "
            "such as current facts, prices, or figures."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query string.",
                }
            },
            "required": ["query"],
        },
    },
]


def run_calculator(expression: str) -> str:
    """Safely evaluate a basic arithmetic expression."""
    allowed_chars = set("0123456789+-*/(). ")
    if not set(expression) <= allowed_chars:
        return f"Error: expression contains unsupported characters: {expression!r}"
    try:
        result = eval(expression, {"__builtins__": {}}, {})
    except Exception as exc:  # noqa: BLE001 - surfaced to the model as a tool error
        return f"Error evaluating expression: {exc}"
    return str(result)


# Mock "search index" so the demo is deterministic and needs no network/API key for search.
_MOCK_SEARCH_INDEX = {
    "eiffel tower height": "The Eiffel Tower is 330 meters tall (including antennas).",
    "number of floors in the empire state building": "The Empire State Building has 102 floors.",
}


def run_web_search(query: str) -> str:
    """Return mock search results for a query (stub -- no real network call)."""
    key = query.strip().lower()
    for indexed_query, fact in _MOCK_SEARCH_INDEX.items():
        if indexed_query in key or key in indexed_query:
            return json.dumps(
                {"query": query, "results": [{"title": indexed_query.title(), "snippet": fact}]}
            )
    return json.dumps(
        {
            "query": query,
            "results": [
                {
                    "title": f"Mock result for: {query}",
                    "snippet": "No indexed mock data for this query; treat as unknown.",
                }
            ],
        }
    )


TOOL_IMPLEMENTATIONS = {
    "calculator": lambda tool_input: run_calculator(tool_input["expression"]),
    "web_search": lambda tool_input: run_web_search(tool_input["query"]),
}


# ---------------------------------------------------------------------------
# Steps 2-4 + 6: the agentic loop itself
# ---------------------------------------------------------------------------

def run_agent(user_message: str) -> str:
    messages = [{"role": "user", "content": user_message}]

    for iteration in range(1, MAX_ITERATIONS + 1):
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            tools=TOOLS,
            messages=messages,
        )

        print(f"[iteration {iteration}] stop_reason={response.stop_reason}")

        if response.stop_reason == "tool_use":
            # Preserve the assistant turn (may mix text + one or more tool_use blocks)
            messages.append({"role": "assistant", "content": response.content})

            tool_result_blocks = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                tool_fn = TOOL_IMPLEMENTATIONS.get(block.name)
                if tool_fn is None:
                    tool_output = f"Error: unknown tool '{block.name}'"
                    is_error = True
                else:
                    print(f"  -> calling {block.name}({block.input})")
                    try:
                        tool_output = tool_fn(block.input)
                        is_error = False
                    except Exception as exc:  # noqa: BLE001
                        tool_output = f"Error running tool: {exc}"
                        is_error = True

                tool_result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": tool_output,
                        "is_error": is_error,
                    }
                )

            messages.append({"role": "user", "content": tool_result_blocks})
            continue  # loop again so Claude can see the tool results

        if response.stop_reason == "end_turn":
            final_text = "".join(
                block.text for block in response.content if block.type == "text"
            )
            return final_text

        # Any other stop_reason (max_tokens, stop_sequence, etc.) ends the loop too,
        # since none of them mean "call another tool."
        final_text = "".join(
            block.text for block in response.content if block.type == "text"
        )
        print(f"[warning] loop ended on unexpected stop_reason={response.stop_reason}")
        return final_text

    print(f"[warning] MAX_ITERATIONS ({MAX_ITERATIONS}) reached without end_turn; aborting loop")
    return "Agent stopped: exceeded maximum iterations without reaching a final answer."


# ---------------------------------------------------------------------------
# Step 5: test with a prompt requiring sequential tool calls
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    prompt = (
        "Search for the height of the Eiffel Tower, then calculate what that height "
        "would be if it were doubled. Give me the final doubled height in meters."
    )
    print(f"USER: {prompt}\n")
    answer = run_agent(prompt)
    print(f"\nFINAL ANSWER:\n{answer}")
