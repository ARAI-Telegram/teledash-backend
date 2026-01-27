from typing import Literal, Optional

from pydantic import BaseModel


class EvaluationDate(BaseModel):
    message_id: str
    label_classifier: Literal[0, 1]
    label_manual: Literal[0, 1]


class EvaluationMetrics(BaseModel):
    """Evaluation metrics for the positive class (class 1) only."""

    accuracy: float
    precision: float  # Precision for positive class (class 1)
    recall: float  # Recall for positive class (class 1)
    f1_score: float  # F1-score for positive class (class 1)
    # Confusion matrix counts
    true_positives: int
    true_negatives: int
    false_positives: int
    false_negatives: int


class Recommendation(BaseModel):
    sample_assessment: str
    metrics_interpretation: str


class EvaluationResult(BaseModel):
    num_labeled_data: int
    metrics: EvaluationMetrics
    recommendation: Optional[Recommendation] = None
