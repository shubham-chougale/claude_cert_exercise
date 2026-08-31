"""
Built-in Tools -- Grep vs. Glob, Edit vs. Read+Write, Incremental Tracing
===========================================================================

Demonstrates three exam scenarios about Claude Code's built-in tools
(Read, Write, Edit, Bash, Grep, Glob), using real helper implementations
of grep-like/glob-like/edit-like behavior operating on a real sample
project fixture in ./sample_project/ (not a mock or an LLM call).

  1. GREP VS GLOB
     Grep searches file CONTENTS for a pattern (function callers, error
     messages, imports). Glob matches file PATHS by naming pattern (test
     files, config files, extensions). Using the wrong one fails outright:
     Glob cannot find a function call inside a file's text, and Grep is
     not the tool for "give me every *.test.py file".

  2. EDIT VS READ+WRITE
     Edit performs a targeted unique-text-match replacement. When
     old_string matches more than once, Edit must refuse (a safety
     mechanism against unintended changes elsewhere in the file) rather
     than guess. The documented recovery order is: widen old_string with
     more surrounding context, or pass replace_all=True; only fall back
     to a full Read+Write rewrite when neither disambiguates.

  3. INCREMENTAL TRACING / THE DEPRECATION WORKFLOW
     Grep for entry points -> Read to follow imports/trace flow -> Grep
     again to trace usage through wrappers -> Read only justified files.
     Concretely, finding every caller of a soon-to-be-deprecated function
     plus its tests requires: Grep for the function name (catches direct
     callers), Glob for sibling test files (**/Name.test.*), then Grep
     again for any wrapper/re-export name that Grep on the original name
     alone would miss (an indirect caller through a wrapper).
"""

import fnmatch
import os
import re
from dataclasses import dataclass, field

SAMPLE_ROOT = os.path.join(os.path.dirname(__file__), "sample_project")


# ---------------------------------------------------------------------------
# Step 1: grep-like and glob-like helpers over a real sample project
# ---------------------------------------------------------------------------

def _all_files(root: str) -> list:
    paths = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            paths.append(os.path.relpath(os.path.join(dirpath, name), root))
    return sorted(p.replace(os.sep, "/") for p in paths)


def grep_like(root: str, pattern: str) -> list:
    """Search file CONTENTS for a regex pattern. Returns relative paths of
    files containing at least one match.
    """
    regex = re.compile(pattern)
    hits = []
    for rel_path in _all_files(root):
        with open(os.path.join(root, rel_path), "r", encoding="utf-8") as f:
            if regex.search(f.read()):
                hits.append(rel_path)
    return hits


def glob_like(root: str, glob_pattern: str) -> list:
    """Match file PATHS by naming pattern. Does not look at file contents
    at all.
    """
    return [p for p in _all_files(root) if fnmatch.fnmatch(p, glob_pattern)]


# ---------------------------------------------------------------------------
# Step 2: Edit with unique-match safety, and the documented recovery order
# ---------------------------------------------------------------------------

class NonUniqueMatchError(Exception):
    pass


def edit_text(content: str, old: str, new: str, replace_all: bool = False) -> str:
    count = content.count(old)
    if count == 0:
        raise ValueError(f"old_string not found: {old!r}")
    if count > 1 and not replace_all:
        raise NonUniqueMatchError(
            f"old_string matches {count} times; widen it with more context or pass replace_all=True"
        )
    if replace_all:
        return content.replace(old, new)
    return content.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Step 3: Deprecation-tracing workflow -- Grep, then Glob, then Grep again
# ---------------------------------------------------------------------------

@dataclass
class DeprecationTrace:
    direct_callers: list = field(default_factory=list)
    test_files: list = field(default_factory=list)
    wrapper_names: list = field(default_factory=list)
    indirect_callers: list = field(default_factory=list)


def trace_deprecated_function(root: str, function_name: str) -> DeprecationTrace:
    trace = DeprecationTrace()

    # Grep for the function name: catches its definition, its direct
    # callers, and any module that imports it by name.
    trace.direct_callers = grep_like(root, re.escape(function_name))

    # Glob for sibling test files -- a path-based lookup, not a content
    # search: no amount of grepping for the function name replaces this.
    defining_file = next(
        p for p in trace.direct_callers
        if re.search(rf"^def\s+{re.escape(function_name)}\s*\(", open(os.path.join(root, p)).read(), re.MULTILINE)
    )
    base = os.path.splitext(os.path.basename(defining_file))[0]
    trace.test_files = glob_like(root, f"*{base}.test.py")

    # Grep again for wrapper/re-export names: a module that imports the
    # function and re-exports it under a new name (e.g. submit_order
    # wrapping processLegacyOrder) is invisible to a Grep on the original
    # name alone once its own callers only ever reference the wrapper.
    # Identify wrapper modules: files that both import/call function_name
    # AND define a new function that simply forwards to it.
    for rel_path in trace.direct_callers:
        with open(os.path.join(root, rel_path), "r", encoding="utf-8") as f:
            body = f.read()
        for match in re.finditer(r"^def\s+(\w+)\s*\(", body, re.MULTILINE):
            wrapper_candidate = match.group(1)
            if wrapper_candidate != function_name and function_name in body:
                trace.wrapper_names.append(wrapper_candidate)

    for wrapper_name in trace.wrapper_names:
        trace.indirect_callers.extend(
            p for p in grep_like(root, re.escape(wrapper_name)) if p not in trace.direct_callers
        )

    return trace


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # --- Step 1a: Grep finds content; Glob cannot -------------------------
    grep_hits = grep_like(SAMPLE_ROOT, r"processLegacyOrder")
    assert "order_processor.py" in grep_hits
    assert "checkout.py" in grep_hits, "Grep must find the direct caller in checkout.py."
    print(f"[GREP] 'processLegacyOrder' found by content search in: {grep_hits}")

    glob_attempt_for_content = glob_like(SAMPLE_ROOT, "*processLegacyOrder*")
    assert glob_attempt_for_content == [], (
        "Glob matches file PATHS, not contents -- it must fail to find a function "
        "call that only appears inside file text, not in any filename."
    )
    print("[TRAP] Glob for '*processLegacyOrder*' found nothing -- it cannot see file contents.")

    # --- Step 1b: Glob finds paths by pattern; Grep is the wrong tool for it
    test_files = glob_like(SAMPLE_ROOT, "*.test.py")
    assert test_files == ["order_processor.test.py"]
    print(f"[GLOB] '*.test.py' found: {test_files}")

    config_files = glob_like(SAMPLE_ROOT, "*.json")
    assert config_files == ["config.json"]
    print(f"[GLOB] '*.json' found: {config_files}")

    # --- Step 2: Edit -- unique match, non-unique refusal, recovery order -
    content = (
        "def processOrder(id):\n"
        "    return id\n"
        "\n"
        "def processOrderLegacy(id):\n"
        "    return id\n"
    )
    ambiguous_anchor = "return id"
    try:
        edit_text(content, ambiguous_anchor, "return str(id)")
        raise AssertionError("Expected NonUniqueMatchError for an ambiguous anchor.")
    except NonUniqueMatchError:
        print(f"[EDIT] refused ambiguous anchor {ambiguous_anchor!r} (matches twice) -- correct safety behavior.")

    widened_anchor = "def processOrder(id):\n    return id"
    widened_result = edit_text(content, widened_anchor, "def processOrder(id):\n    return str(id)")
    assert widened_result.count("return str(id)") == 1
    assert "def processOrderLegacy(id):\n    return id" in widened_result, (
        "Widening the anchor must leave the unrelated function untouched."
    )
    print("[EDIT] recovery: widened old_string with surrounding context -- unique match, targeted change applied.")

    replace_all_result = edit_text(content, ambiguous_anchor, "return str(id)", replace_all=True)
    assert replace_all_result.count("return str(id)") == 2
    print("[EDIT] alternative recovery: replace_all=True applied the same change everywhere on purpose.")

    # A full Read+Write rewrite is a valid last resort, but not the first
    # move: widening the anchor already solved this case without it.
    assert widened_result != content and "processOrder" in widened_result
    print("[EDIT] Read+Write rewrite was never needed -- Edit recovery resolved it directly.")

    # --- Step 3: incremental tracing / deprecation workflow ----------------
    trace = trace_deprecated_function(SAMPLE_ROOT, "processLegacyOrder")
    assert "order_processor.py" in trace.direct_callers
    assert "checkout.py" in trace.direct_callers, "Direct caller via Grep on the function name."
    assert trace.test_files == ["order_processor.test.py"], "Glob must find the sibling test file."
    assert "submit_order" in trace.wrapper_names, "Must identify the wrapper function re-exporting the target."
    assert "utils/order_wrapper.py" in trace.direct_callers, "The wrapper module itself directly calls the target."
    assert "billing.py" in trace.indirect_callers, (
        "billing.py calls submit_order, not processLegacyOrder directly -- a single "
        "Grep for processLegacyOrder alone would miss this indirect caller entirely."
    )
    assert "billing.py" not in trace.direct_callers, (
        "Confirms billing.py's dependency on processLegacyOrder is only reachable "
        "through the wrapper-name Grep pass, not the first pass."
    )
    print(
        f"[TRACE] direct callers via Grep: {trace.direct_callers}; "
        f"test file via Glob: {trace.test_files}; "
        f"wrapper(s) found: {trace.wrapper_names}; "
        f"indirect callers only found via second Grep pass: {trace.indirect_callers}"
    )

    print("\n[ALL TESTS PASSED]")
