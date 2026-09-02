"""
Structured Output with Tool Use
==================================

Demonstrates the exam's reliability hierarchy for structured output:

  1. Tool use with a JSON schema eliminates SYNTAX errors (malformed
     JSON, missing brackets, unquoted keys) entirely, because output is
     constrained to conform to the schema's shape.
  2. It does NOT eliminate SEMANTIC errors: sum discrepancies, values in
     the wrong field, or fabricated data for fields the source document
     never actually specified.
  3. Nullable/optional fields + explicit "unclear"/"other" enum values
     prevent the model from being pressured into inventing plausible
     values just to satisfy a "required" field.
  4. tool_choice has three modes -- auto / any / {"type": "tool", ...} --
     with different guarantees.

No LLM API is called. A real `jsonschema`-validated pipeline (using only
the standard library, via a minimal hand-rolled validator) models a
"required-fields-only" schema vs a "nullable-fields + unclear enum"
schema applied to the same ambiguous/incomplete source documents, so the
fabrication difference is directly observable.
"""

from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Step 1: tool_choice modes
# ---------------------------------------------------------------------------

TOOL_CHOICE_MODES = {
    "auto": "Model decides whether to call a tool at all. No structured-output guarantee.",
    "any": "Model must call SOME tool, but picks which one. Guarantees structure; flexible schema selection.",
    "tool": "Model must call the NAMED tool. Guarantees structure AND which schema is used; zero flexibility.",
}


def pick_tool_choice(document_type_known: bool, multiple_possible_schemas: bool) -> str:
    """Models the documented decision rule for selecting a tool_choice
    mode based on what's known about the incoming document.
    """
    if not document_type_known and multiple_possible_schemas:
        return "any"     # unknown doc type, multiple schemas (invoice/receipt/contract) -> any
    if document_type_known:
        return "tool"    # known doc type, single mandatory schema -> named tool
    return "auto"         # conversational responses genuinely acceptable


# ---------------------------------------------------------------------------
# Step 2: a minimal schema-shape enforcer, modeling what tool_use guarantees
# ---------------------------------------------------------------------------

class SchemaViolation(Exception):
    pass


def enforce_shape(payload: dict, required_fields: list, field_types: dict) -> dict:
    """Models what tool_use with a JSON schema guarantees: correct
    shape/types/required-field presence. This is the SYNTAX guarantee --
    it says nothing about whether the VALUES are semantically correct.
    """
    for field in required_fields:
        if field not in payload:
            raise SchemaViolation(f"missing required field: {field}")
    for field, expected_type in field_types.items():
        if field in payload and payload[field] is not None and not isinstance(payload[field], expected_type):
            raise SchemaViolation(f"field {field} has wrong type")
    return payload  # shape is valid -- values may still be wrong/fabricated


# ---------------------------------------------------------------------------
# Step 3: required-fields schema forces fabrication; nullable schema doesn't
# ---------------------------------------------------------------------------

SOURCE_DOCUMENT = {
    "vendor": "Acme Corp",
    "amount": 500.00,
    # NOTE: no department field anywhere in the source document
}


def extract_with_required_schema(document: dict) -> dict:
    """Models a badly-designed schema where 'department' is required.
    Since tool_use forces the model to fill every required field, and
    the field is genuinely absent from the source, the only way to
    satisfy the schema is to fabricate a plausible-looking value.
    """
    result = {
        "vendor": document.get("vendor"),
        "amount": document.get("amount"),
        # required field not present in source -> model fabricates one
        "department": document.get("department", "Operations"),  # FABRICATED
    }
    enforce_shape(result, required_fields=["vendor", "amount", "department"],
                  field_types={"vendor": str, "amount": float, "department": str})
    return result


def extract_with_nullable_schema(document: dict) -> dict:
    """Models the recommended schema design: 'department' is nullable.
    The model can honestly report null instead of inventing a value.
    """
    result = {
        "vendor": document.get("vendor"),
        "amount": document.get("amount"),
        "department": document.get("department"),  # None if genuinely absent -- honest
    }
    enforce_shape(result, required_fields=["vendor", "amount"],
                  field_types={"vendor": str, "amount": float, "department": (str, type(None))})
    return result


# ---------------------------------------------------------------------------
# Step 4: "unclear" enum + "other"+detail pattern for ambiguous categorization
# ---------------------------------------------------------------------------

CATEGORY_ENUM = {"invoice", "receipt", "contract", "other", "unclear"}


@dataclass
class Categorization:
    category: str
    other_detail: Optional[str] = None


def categorize_document(text: str) -> Categorization:
    """Demonstrates the 'unclear' + 'other'+detail pattern: genuinely
    ambiguous input gets 'unclear' instead of a forced, possibly wrong,
    category; recognizable-but-uncovered input gets 'other' plus a
    freeform detail string instead of being silently misclassified.
    """
    if "purchase order" in text.lower():
        return Categorization(category="other", other_detail="purchase order")
    if "invoice" in text.lower():
        return Categorization(category="invoice")
    return Categorization(category="unclear")


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def main():
    print("=== Step 1: tool_choice selection ===")
    print("Unknown doc type, multiple schemas ->", pick_tool_choice(False, True))
    print("Known doc type, single schema       ->", pick_tool_choice(True, False))
    print("Conversational response acceptable  ->", pick_tool_choice(False, False))

    print("\n=== Step 2: schema enforces shape, not semantics ===")
    bad_semantics = {"vendor": "Acme Corp", "amount": 500.00, "line_items_sum": 450.00}
    enforce_shape(bad_semantics, required_fields=["vendor", "amount"],
                  field_types={"vendor": str, "amount": float})
    print("Shape valid despite amount (500.00) != line_items_sum (450.00):", bad_semantics)

    print("\n=== Step 3: required vs nullable fields and fabrication ===")
    required_result = extract_with_required_schema(SOURCE_DOCUMENT)
    nullable_result = extract_with_nullable_schema(SOURCE_DOCUMENT)
    print("Required-field schema (fabricates department):", required_result)
    print("Nullable-field schema (honest null):           ", nullable_result)

    print("\n=== Step 4: unclear / other+detail categorization ===")
    for text in ["Invoice #123 for services rendered", "This is a purchase order, not an invoice",
                 "Please see attached."]:
        print(f"  {text!r:55} -> {categorize_document(text)}")


if __name__ == "__main__":
    main()
