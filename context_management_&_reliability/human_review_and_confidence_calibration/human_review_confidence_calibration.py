"""
Human Review & Confidence Calibration
========================================

Demonstrates the exam's reviewer-capacity allocation strategy with real,
deterministic code (no LLM API call):

  1. THE AGGREGATE METRICS TRAP
     A single overall accuracy number hides catastrophic per-segment
     failures because it is volume-weighted. Disaggregating by document
     type reveals segments needing human review that the aggregate
     number would let through.

  2. CONFIDENCE CALIBRATION AGAINST A LABELED SET
     Raw confidence scores are shown to have different true-accuracy
     meanings depending on field type/document type. A calibration
     curve is built from a labeled validation set and used to derive
     per-segment thresholds, instead of trusting a single global cutoff.

  3. STRATIFIED SAMPLING INCLUDING HIGH-CONFIDENCE ITEMS
     A sampling strategy that only reviews low-confidence items is
     shown to miss a systematic error injected into high-confidence
     predictions; stratified sampling across confidence bands catches it.

  4. DYNAMIC REVIEWER PRIORITIZATION
     Reviewer capacity is allocated by uncertainty (lowest confidence
     first) rather than evenly or chronologically, and the two
     strategies are compared on the same queue.
"""

import random
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Step 1: the aggregate metrics trap
# ---------------------------------------------------------------------------

@dataclass
class Segment:
    doc_type: str
    volume: int
    accuracy: float  # ground-truth per-segment accuracy


SEGMENTS = [
    Segment("standard_invoice", volume=9500, accuracy=0.995),
    Segment("handwritten_receipt", volume=300, accuracy=0.601),
    Segment("international_format", volume=200, accuracy=0.452),
]


def aggregate_accuracy(segments: list) -> float:
    total_volume = sum(s.volume for s in segments)
    weighted_correct = sum(s.volume * s.accuracy for s in segments)
    return weighted_correct / total_volume


def segments_needing_review(segments: list, threshold: float = 0.9) -> list:
    return [s for s in segments if s.accuracy < threshold]


# ---------------------------------------------------------------------------
# Step 2: confidence calibration against a labeled validation set
# ---------------------------------------------------------------------------

@dataclass
class LabeledExtraction:
    field_type: str
    raw_confidence: float
    actually_correct: bool


def build_calibration_curve(labeled_set: list, field_type: str, bucket_size: float = 0.1) -> dict:
    """Buckets a labeled validation set by raw confidence and computes
    the ACTUAL accuracy per bucket for one field type -- the calibration
    curve. Two different field types can map the same raw confidence to
    different actual accuracy, which is exactly why calibration must be
    field-type-specific.
    """
    relevant = [e for e in labeled_set if e.field_type == field_type]
    buckets: dict = {}
    for e in relevant:
        bucket = round(round(e.raw_confidence / bucket_size) * bucket_size, 2)
        buckets.setdefault(bucket, []).append(e.actually_correct)
    return {b: sum(v) / len(v) for b, v in buckets.items()}


def calibrated_threshold_for(curve: dict, target_accuracy: float = 0.9) -> float:
    """Finds the lowest raw-confidence bucket whose ACTUAL accuracy meets
    the target -- this becomes the automation threshold for this field
    type, instead of trusting raw confidence directly.
    """
    qualifying = [b for b, acc in curve.items() if acc >= target_accuracy]
    return min(qualifying) if qualifying else 1.0  # nothing qualifies -> always human review


LABELED_SET = (
    [LabeledExtraction("date", 0.9, True) for _ in range(94)]
    + [LabeledExtraction("date", 0.9, False) for _ in range(6)]
    + [LabeledExtraction("amount", 0.9, True) for _ in range(82)]
    + [LabeledExtraction("amount", 0.9, False) for _ in range(18)]
)


# ---------------------------------------------------------------------------
# Step 3: stratified sampling including high-confidence items
# ---------------------------------------------------------------------------

@dataclass
class Extraction:
    id: str
    confidence: float
    is_actually_correct: bool


def build_extraction_batch(n: int, systematic_error_rate_high_conf: float = 0.15, seed: int = 42) -> list:
    """Models a batch where most predictions are fine, but a systematic
    error has crept into a slice of HIGH-confidence predictions (e.g. a
    bug in a currency-parsing path that the model is nonetheless
    confident about).
    """
    rng = random.Random(seed)
    batch = []
    for i in range(n):
        confidence = rng.uniform(0.85, 0.99)  # everything looks high-confidence
        is_correct = rng.random() > systematic_error_rate_high_conf
        batch.append(Extraction(f"e{i}", confidence, is_correct))
    return batch


def sample_low_confidence_only(batch: list, fraction: float = 0.1) -> list:
    sorted_batch = sorted(batch, key=lambda e: e.confidence)
    return sorted_batch[: int(len(batch) * fraction)]


def sample_stratified(batch: list, fraction: float = 0.1) -> list:
    """Samples proportionally across confidence bands, INCLUDING
    high-confidence items -- the only way to catch a systematic error
    that lives entirely inside the automated (high-confidence) slice.
    """
    bands = {"low": [], "mid": [], "high": []}
    for e in batch:
        if e.confidence < 0.5:
            bands["low"].append(e)
        elif e.confidence < 0.85:
            bands["mid"].append(e)
        else:
            bands["high"].append(e)
    sample = []
    for band_items in bands.values():
        take = max(1, int(len(band_items) * fraction)) if band_items else 0
        sample.extend(band_items[:take])
    return sample


def detected_error_rate(sample: list) -> float:
    if not sample:
        return 0.0
    return 1 - (sum(1 for e in sample if e.is_actually_correct) / len(sample))


# ---------------------------------------------------------------------------
# Step 4: dynamic reviewer prioritization
# ---------------------------------------------------------------------------

def prioritize_by_uncertainty(batch: list) -> list:
    return sorted(batch, key=lambda e: e.confidence)  # lowest confidence first


def prioritize_chronologically(batch: list) -> list:
    return list(batch)  # arrival order, ignoring uncertainty


def reviewer_catches_in_first_k(prioritized: list, k: int) -> int:
    """How many actually-incorrect extractions get reviewed within the
    first k reviewer slots under a given prioritization strategy.
    """
    return sum(1 for e in prioritized[:k] if not e.is_actually_correct)


def build_review_queue_with_uncertainty_correlation(n: int, seed: int = 7) -> list:
    """Models a realistic queue where lower model confidence genuinely
    correlates with a higher chance of being wrong (the normal case --
    Step 3 above modeled the EXCEPTION, a systematic high-confidence
    error, precisely because it's the case stratified sampling exists
    to catch). Confidence is randomized independent of arrival order,
    so 'chronological' order carries no useful signal.
    """
    rng = random.Random(seed)
    queue = []
    for i in range(n):
        confidence = rng.uniform(0.3, 0.99)
        error_probability = 1 - confidence  # lower confidence -> more likely wrong
        is_correct = rng.random() > error_probability
        queue.append(Extraction(f"q{i}", confidence, is_correct))
    rng.shuffle(queue)  # arrival order is unrelated to confidence
    return queue


def main():
    print("=== Step 1: The aggregate metrics trap ===")
    agg = aggregate_accuracy(SEGMENTS)
    print(f"  Aggregate (volume-weighted) accuracy: {agg:.3f}")
    print("  Per-segment accuracy:")
    for s in SEGMENTS:
        print(f"    {s.doc_type:22} volume={s.volume:5}  accuracy={s.accuracy:.3f}")
    flagged = segments_needing_review(SEGMENTS)
    print(f"  Segments needing human review (below 0.9): {[s.doc_type for s in flagged]}")

    print("\n=== Step 2: Field-type-specific calibration ===")
    date_curve = build_calibration_curve(LABELED_SET, "date")
    amount_curve = build_calibration_curve(LABELED_SET, "amount")
    print(f"  date curve:   {date_curve}  -> threshold={calibrated_threshold_for(date_curve)}")
    print(f"  amount curve: {amount_curve}  -> threshold={calibrated_threshold_for(amount_curve)}")
    print("  Same raw confidence (0.9) means different actual accuracy per field type.")

    print("\n=== Step 3: Stratified sampling catches systematic high-confidence errors ===")
    batch = build_extraction_batch(500)
    low_only = sample_low_confidence_only(batch)
    stratified = sample_stratified(batch)
    print(f"  Low-confidence-only sample error rate detected: {detected_error_rate(low_only):.3f}")
    print(f"  Stratified sample error rate detected:          {detected_error_rate(stratified):.3f}")
    print(f"  True injected error rate in high-confidence slice: 0.150")

    print("\n=== Step 4: Dynamic prioritization by uncertainty ===")
    review_queue = build_review_queue_with_uncertainty_correlation(1000)
    by_uncertainty = prioritize_by_uncertainty(review_queue)
    by_chronology = prioritize_chronologically(review_queue)
    k = 100
    print(f"  Errors caught in first {k} reviews (by uncertainty):  {reviewer_catches_in_first_k(by_uncertainty, k)}")
    print(f"  Errors caught in first {k} reviews (chronological):   {reviewer_catches_in_first_k(by_chronology, k)}")


if __name__ == "__main__":
    main()
