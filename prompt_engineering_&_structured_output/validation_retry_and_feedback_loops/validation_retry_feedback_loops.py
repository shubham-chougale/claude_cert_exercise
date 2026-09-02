"""
Validation, Retry, and Feedback Loops
========================================

Demonstrates the exam's retry-with-error-feedback pattern using real
Pydantic validators (no LLM API call -- the "model" is a small
deterministic function standing in for an LLM extraction call, so the
retry loop and its termination condition are fully inspectable).

  1. SCHEMA SYNTAX ERRORS VS SEMANTIC VALIDATION ERRORS
     Pydantic enforces STRUCTURE (types, required fields) the same way
     tool_use schemas do. Custom validators enforce BUSINESS RULES
     schemas can't express (line items summing to the stated total).
     The two are handled by different layers.

  2. RETRY-WITH-ERROR-FEEDBACK
     A failed extraction is retried with three ingredients: the
     original document, the previous (failed) output, and the SPECIFIC
     validation error. A retry without the specific error reproduces
     the same mistake; a retry with it self-corrects.

  3. THE FIXABLE/UNFIXABLE BOUNDARY
     Format and placement errors are fixable by retry. Information
     genuinely absent from the source document is not -- retrying
     forever cannot manufacture data that was never there. The correct
     behavior is to stop retrying and return null / flag for review.

  4. SELF-CORRECTION SCHEMA DESIGN
     Extracting both calculated_total and stated_total (rather than a
     single "total" field) makes the discrepancy detectable without any
     external logic, by construction.
"""

from typing import Optional
from pydantic import BaseModel, ValidationError, model_validator


# ---------------------------------------------------------------------------
# Step 1: Pydantic model with structural typing AND a business-rule validator
# ---------------------------------------------------------------------------

class LineItem(BaseModel):
    description: str
    amount: float


class Invoice(BaseModel):
    vendor: str
    line_items: list[LineItem]
    calculated_total: float   # sum of line items, self-correction field
    stated_total: float       # what the document literally says
    department: Optional[str] = None  # nullable -- see module 4.3

    @model_validator(mode="after")
    def totals_must_match(self):
        actual_sum = sum(item.amount for item in self.line_items)
        if abs(actual_sum - self.stated_total) > 0.01:
            raise ValueError(
                f"line_items sum to {actual_sum} but stated_total is {self.stated_total}"
            )
        if abs(self.calculated_total - actual_sum) > 0.01:
            raise ValueError(
                f"calculated_total ({self.calculated_total}) does not match "
                f"sum of line_items ({actual_sum})"
            )
        return self


def format_validation_errors(exc: ValidationError) -> str:
    lines = ["Validation errors:"]
    for err in exc.errors():
        field = ".".join(str(p) for p in err["loc"]) or "(model)"
        lines.append(f"  {field}: {err['msg']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Step 2: a deterministic stand-in for "the model", modeling a fixable bug
# ---------------------------------------------------------------------------

DOCUMENT = (
    "Vendor: Acme Corp. Line items: Widgets 200.00, Gadgets 250.00. "
    "Total due: 450.00."
)


def extraction_attempt(document: str, previous_output: Optional[dict],
                        previous_error: Optional[str]) -> dict:
    """Models an LLM extraction call. On the FIRST attempt it makes a
    classic fixable mistake (drops a line item, so stated_total doesn't
    match). On RETRY, if given the specific error message naming the
    mismatch, it self-corrects by including the missing item. If retried
    WITHOUT the specific error, it reproduces the same mistake --
    modeling "without the specific error, the model has no guidance for
    what to fix."
    """
    if previous_error is not None and "stated_total is 450.0" in previous_error:
        # given the specific error, the model adds the missing line item
        return {
            "vendor": "Acme Corp",
            "line_items": [
                {"description": "Widgets", "amount": 200.00},
                {"description": "Gadgets", "amount": 250.00},
            ],
            "calculated_total": 450.00,
            "stated_total": 450.00,
            "department": None,
        }
    if previous_error is not None:
        # retried, but WITHOUT specific feedback -> reproduces the same bug
        return previous_output

    # first attempt: forgets the "Gadgets" line item entirely
    return {
        "vendor": "Acme Corp",
        "line_items": [{"description": "Widgets", "amount": 200.00}],
        "calculated_total": 200.00,
        "stated_total": 450.00,
        "department": None,
    }


def run_retry_loop(document: str, max_retries: int = 2, give_specific_feedback: bool = True):
    """The documented retry-with-error-feedback loop: parse/validate,
    and on failure, retry with (document, previous_output, specific
    error) -- unless the error indicates genuinely missing source data,
    in which case retrying is pointless.
    """
    previous_output = None
    previous_error = None
    for attempt in range(1, max_retries + 2):
        raw = extraction_attempt(document, previous_output, previous_error)
        try:
            invoice = Invoice.model_validate(raw)
            return {"status": "success", "attempt": attempt, "invoice": invoice}
        except ValidationError as exc:
            previous_error = format_validation_errors(exc)
            previous_output = raw
            if not give_specific_feedback:
                previous_error = "Validation failed. Try again."  # no specifics -> won't help
            if attempt == max_retries + 1:
                return {"status": "exhausted", "attempt": attempt, "last_error": previous_error}


# ---------------------------------------------------------------------------
# Step 3: the fixable/unfixable boundary
# ---------------------------------------------------------------------------

def extract_department(document: str, retries_so_far: int) -> Optional[str]:
    """Models the unfixable case: the source document genuinely never
    mentions a department. No number of retries manufactures the data;
    the correct behavior is to return None (nullable field) rather than
    retry indefinitely or fabricate a value.
    """
    if "Department:" in document:
        return document.split("Department:")[1].split(".")[0].strip()
    return None  # genuinely absent -- retrying will not help


def demo_unfixable_case():
    result = extract_department(DOCUMENT, retries_so_far=3)
    return result  # None: retries cannot fix genuinely missing data


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def main():
    print("=== Step 1: structural vs business-rule validation ===")
    try:
        Invoice.model_validate({
            "vendor": "Acme Corp",
            "line_items": [{"description": "Widgets", "amount": "not-a-number"}],
            "calculated_total": 200.0,
            "stated_total": 200.0,
        })
    except ValidationError as exc:
        print("Structural (type) error caught by Pydantic:")
        print(format_validation_errors(exc))

    print("\n=== Step 2: retry WITHOUT specific error feedback ===")
    result_no_feedback = run_retry_loop(DOCUMENT, max_retries=2, give_specific_feedback=False)
    print(f"  status={result_no_feedback['status']} after {result_no_feedback['attempt']} attempt(s)")

    print("\n=== Step 2b: retry WITH specific error feedback ===")
    result_with_feedback = run_retry_loop(DOCUMENT, max_retries=2, give_specific_feedback=True)
    print(f"  status={result_with_feedback['status']} after {result_with_feedback['attempt']} attempt(s)")
    if result_with_feedback["status"] == "success":
        print(f"  final invoice: {result_with_feedback['invoice']}")

    print("\n=== Step 3: fixable vs unfixable ===")
    print(f"  department extracted from a document that never mentions one: {demo_unfixable_case()!r}")
    print("  (correct behavior: return None, not fabricate a value or retry forever)")


if __name__ == "__main__":
    main()
