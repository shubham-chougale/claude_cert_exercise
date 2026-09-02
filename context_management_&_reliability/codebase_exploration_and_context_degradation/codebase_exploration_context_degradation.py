"""
Codebase Exploration & Context Degradation
=============================================

Demonstrates the exam's mitigations for context degradation during
extended codebase exploration, with real, deterministic code (no LLM
API call). Context degradation is an ATTENTION QUALITY problem, not a
token-limit problem -- "increasing the context window doesn't fix it."

  1. THE DEGRADATION SYMPTOM
     As unrelated verbose exploration output accumulates, references to
     an early precise finding degrade from specific ("OrderRepository
     class at src/repos/order.ts") to generic ("typical repository
     patterns") -- modeled as attention decaying with distance/volume
     of intervening verbose output, independent of total window size.

  2. SCRATCHPAD FILES
     Writing key findings to a persistent file, outside the vulnerable
     conversation context, is shown to keep the finding retrievable
     verbatim regardless of how much exploration happens afterward.

  3. SUBAGENT DELEGATION FOR CONTEXT ISOLATION
     A focused subagent's verbose exploration never touches the main
     agent's context; only its structured summary does -- modeled by
     comparing "main context size" with vs without delegation.

  4. STATE MANIFEST FOR CRASH RECOVERY
     A structured manifest (phase, explored paths, key findings, next
     steps) is built and shown to allow a fresh session to resume
     exactly where a crashed one left off, without re-exploring.
"""

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Step 1: degradation symptom -- specificity decays with intervening volume
# ---------------------------------------------------------------------------

def recall_finding(finding: str, intervening_verbose_chars: int, window_is_fixed: bool = True) -> str:
    """Models attention decay: the more UNRELATED verbose output has
    accumulated since a finding was discovered, the more likely recall
    degrades to a generic description -- regardless of whether the
    context window itself has room left (window_is_fixed=True models
    that this is NOT a capacity problem).
    """
    degradation_threshold = 5000  # chars of intervening noise before recall degrades
    if intervening_verbose_chars < degradation_threshold:
        return finding  # precise recall
    return "typical repository patterns"  # degraded to generic


def demo_degradation_symptom():
    precise_finding = "OrderRepository class at src/repos/order.ts"
    early_recall = recall_finding(precise_finding, intervening_verbose_chars=500)
    late_recall = recall_finding(precise_finding, intervening_verbose_chars=12000)
    return {"early_recall": early_recall, "late_recall_after_much_exploration": late_recall}


# ---------------------------------------------------------------------------
# Step 2: scratchpad files keep findings immune to degradation
# ---------------------------------------------------------------------------

class Scratchpad:
    """Models writing findings to a file OUTSIDE conversation context."""

    def __init__(self):
        self._entries: list = []

    def write_finding(self, finding: str):
        self._entries.append(finding)

    def read_all(self) -> list:
        # a scratchpad read is NOT subject to the attention-decay model
        # above -- it is an exact, structured lookup, not "recall"
        return list(self._entries)


def demo_scratchpad_persistence():
    pad = Scratchpad()
    pad.write_finding("OrderRepository class at src/repos/order.ts")
    # simulate a large amount of subsequent unrelated exploration by NOT
    # touching the scratchpad -- conversation "recall" would degrade,
    # but the scratchpad read is exact regardless
    pad.write_finding("PaymentGateway interface at src/payments/gateway.ts")
    return pad.read_all()


# ---------------------------------------------------------------------------
# Step 3: subagent delegation for context isolation
# ---------------------------------------------------------------------------

@dataclass
class ExplorationTask:
    description: str
    verbose_output_chars: int  # how much raw file/search output this task produces


def explore_without_delegation(tasks: list) -> int:
    """All raw exploration output accumulates directly in the main
    agent's context.
    """
    return sum(t.verbose_output_chars for t in tasks)


def explore_with_subagent_delegation(tasks: list, summary_chars_per_task: int = 200) -> int:
    """Each task's verbose output stays inside its OWN subagent; only a
    fixed-size structured summary returns to the main agent. Context
    isolation, not parallelization, is the documented primary benefit.
    """
    return sum(summary_chars_per_task for _ in tasks)


def demo_subagent_isolation():
    tasks = [
        ExplorationTask("Find all test files and report coverage status", 8000),
        ExplorationTask("Trace refund flow from endpoint to database", 15000),
        ExplorationTask("Identify external API integrations and error handling", 11000),
    ]
    return {
        "main_context_chars_without_delegation": explore_without_delegation(tasks),
        "main_context_chars_with_delegation": explore_with_subagent_delegation(tasks),
    }


# ---------------------------------------------------------------------------
# Step 4: state manifest for crash recovery
# ---------------------------------------------------------------------------

@dataclass
class StateManifest:
    session_id: str
    current_phase: str
    explored_paths: list = field(default_factory=list)
    key_findings: list = field(default_factory=list)
    next_steps: list = field(default_factory=list)

    def resume_prompt(self) -> str:
        """What gets injected into a fresh session to resume without
        re-exploring anything already covered.
        """
        return (
            f"Resuming session {self.session_id} at phase '{self.current_phase}'.\n"
            f"Already explored: {', '.join(self.explored_paths)}\n"
            f"Key findings so far: {', '.join(self.key_findings)}\n"
            f"Next steps: {', '.join(self.next_steps)}"
        )


def demo_crash_recovery():
    manifest = StateManifest(
        session_id="explore-2026-09-02-01",
        current_phase="phase_2_cross_module_tracing",
        explored_paths=["src/repos/order.ts", "src/payments/gateway.ts"],
        key_findings=["OrderRepository class at src/repos/order.ts",
                       "PaymentGateway interface at src/payments/gateway.ts"],
        next_steps=["Trace refund flow through PaymentGateway.refund()"],
    )
    return manifest.resume_prompt()


def main():
    print("=== Step 1: Degradation symptom ===")
    for k, v in demo_degradation_symptom().items():
        print(f"  {k}: {v!r}")

    print("\n=== Step 2: Scratchpad persistence ===")
    for entry in demo_scratchpad_persistence():
        print(f"  {entry}")

    print("\n=== Step 3: Subagent delegation for context isolation ===")
    for k, v in demo_subagent_isolation().items():
        print(f"  {k}: {v} chars")

    print("\n=== Step 4: Crash recovery via state manifest ===")
    print(demo_crash_recovery())


if __name__ == "__main__":
    main()
