import logging
from typing import List

from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score

from api.classifier_evaluation.models import (
    EvaluationDate,
    EvaluationMetrics,
    EvaluationResult,
    Recommendation,
)
from api.database.database import Database

logger = logging.getLogger(__name__)


async def get_all_labeled_data() -> List[EvaluationDate]:
    """Get all labeled data from database and convert to EvaluationDate objects.

    Returns:
        List of EvaluationDate objects with both labels present
    """
    db = Database()
    labeled_data_out = [doc async for doc in db.labeled_data.find()]

    # Convert to EvaluationDate, filtering out records without both labels
    evaluation_data = []
    incomplete_records = 0

    for item in labeled_data_out:
        if item.label_classifier is not None and item.label_manual is not None:
            evaluation_data.append(
                EvaluationDate(
                    message_id=item.message_id,  # never used i think?
                    label_classifier=item.label_classifier,
                    label_manual=item.label_manual,
                )
            )
        else:
            incomplete_records += 1

    if incomplete_records > 0:
        logger.warning(
            f"{incomplete_records} record(s) skipped due to missing labels. "
            f"Total records: {len(labeled_data_out)}, Usable: {len(evaluation_data)}"
        )

    return evaluation_data


def get_evaluation_metrics(y_true: List[int], y_pred: List[int]) -> EvaluationMetrics:
    """Calculate evaluation metrics for binary classification.

    All metrics (precision, recall, f1_score) are calculated for the positive class (class 1) only.

    Args:
        y_true: List of true labels (0 or 1)
        y_pred: List of predicted labels (0 or 1)

    Returns:
        EvaluationMetrics object containing:
        - accuracy: Overall accuracy (correct predictions / total predictions)
        - precision: Positive class precision (TP / (TP + FP)) - how many predicted positives are correct
        - recall: Positive class recall (TP / (TP + FN)) - how many actual positives are found
        - f1_score: Positive class F1-score (harmonic mean of precision and recall)
        - true_positives: Count of correctly predicted positive cases
        - true_negatives: Count of correctly predicted negative cases
        - false_positives: Count of negative cases incorrectly predicted as positive
        - false_negatives: Count of positive cases incorrectly predicted as negative
    """
    # Overall accuracy
    accuracy = accuracy_score(y_true, y_pred)

    # Positive class (class 1) specific metrics using average='binary'
    precision = precision_score(y_true, y_pred, average="binary", zero_division=0)
    recall = recall_score(y_true, y_pred, average="binary", zero_division=0)
    f1 = f1_score(y_true, y_pred, average="binary", zero_division=0)

    # Calculate confusion matrix counts
    tp = sum(1 for true, pred in zip(y_true, y_pred) if true == 1 and pred == 1)
    tn = sum(1 for true, pred in zip(y_true, y_pred) if true == 0 and pred == 0)
    fp = sum(1 for true, pred in zip(y_true, y_pred) if true == 0 and pred == 1)
    fn = sum(1 for true, pred in zip(y_true, y_pred) if true == 1 and pred == 0)

    return EvaluationMetrics(
        accuracy=float(accuracy),
        precision=float(precision),
        recall=float(recall),
        f1_score=float(f1),
        true_positives=tp,
        true_negatives=tn,
        false_positives=fp,
        false_negatives=fn,
    )


def create_recommendation(
    num_labeled_data: int, evaluation_metrics: EvaluationMetrics
) -> Recommendation:
    """Create recommendations based on labeled sample distribution and evaluation metrics.

    Args:
        num_labeled_data: Number of labeled data points available
        evaluation_metrics: Calculated evaluation metrics (accuracy, precision, recall, f1)

    Returns:
        Recommendation object with data assessment and metrics interpretation suggestions
    """
    # Check per-class sample size
    num_class_1 = evaluation_metrics.true_positives + evaluation_metrics.false_negatives
    num_class_0 = evaluation_metrics.true_negatives + evaluation_metrics.false_positives

    # Sample assessment recommendations
    sample_parts = []

    # Check if either class has critically insufficient data (< 30 samples)
    if num_class_1 < 30 or num_class_0 < 30:
        sample_parts.append(
            "⚠️ WARNING: Very few labeled samples detected! "
            f"Current distribution: {num_class_1} positive class samples, {num_class_0} negative class samples. "
            "The metrics above are NOT RELIABLE and should NOT be used for decision-making. "
            "Please label significantly more data before drawing conclusions."
        )
    # Check if either class has insufficient data (< 100 samples)
    elif num_class_1 < 100 or num_class_0 < 100:
        sample_parts.append(
            "As a rule of thumb, it is generally recommended to have at least 100 labeled samples for each class. "
            "Otherwise, the metrics shown above and their interpretation should be treated with caution, as small sample sizes lead to unreliable estimates."
        )
        sample_parts.append(
            f"Current distribution: {num_class_1} positive class samples, {num_class_0} negative class samples."
        )
    else:
        # Both classes have sufficient data
        sample_parts.append(
            f"Sample size and class distribution seems reasonable: {num_class_1} positive class samples, {num_class_0} negative class samples."
        )

    # General note about data quantity
    sample_parts.append(
        "Please note: the more data you have, the more reliable the evaluation results will be."
    )

    # Use precision and recall (already for positive class only)
    precision = evaluation_metrics.precision
    recall = evaluation_metrics.recall

    metrics_parts = []

    # Interpret precision (false positive rate)
    # Check if model never predicted positive class (TP + FP = 0)
    total_predicted_positive = (
        evaluation_metrics.true_positives + evaluation_metrics.false_positives
    )
    total_predicted_negative = (
        evaluation_metrics.true_negatives + evaluation_metrics.false_negatives
    )
    if total_predicted_positive == 0:
        metrics_parts.append(
            f"Precision is undefined (0.00): the model never predicted the positive class. "
            f"All {total_predicted_negative} predictions were negative."
        )
    elif total_predicted_negative == 0:
        metrics_parts.append(
            f"Precision is {precision:.2f}: the model predicted everything as positive. "
            f"All {total_predicted_positive} predictions were positive (FP={evaluation_metrics.false_positives})."
        )
    elif precision < 0.5:
        metrics_parts.append(
            f"Precision is low ({precision:.2f}): many false positives ({evaluation_metrics.false_positives}). The model incorrectly classifies too many negatives as positive."
        )
    elif precision < 0.7:
        metrics_parts.append(
            f"Precision is moderate ({precision:.2f}): some false positives ({evaluation_metrics.false_positives})."
        )
    else:
        metrics_parts.append(
            f"Precision is good ({precision:.2f}): few false positives ({evaluation_metrics.false_positives})."
        )

    # Interpret recall (false negative rate)
    # Check if there are no actual positive cases (TP + FN = 0)
    total_actual_positive = (
        evaluation_metrics.true_positives + evaluation_metrics.false_negatives
    )
    if total_actual_positive == 0:
        metrics_parts.append(
            f"Recall is undefined (0.00): there are no actual positive cases in the data. "
            f"All {evaluation_metrics.true_negatives + evaluation_metrics.false_positives} samples are negative class."
        )
    elif recall < 0.5:
        metrics_parts.append(
            f"Recall is low ({recall:.2f}): many false negatives ({evaluation_metrics.false_negatives}). The model misses many positive cases."
        )
    elif recall < 0.7:
        metrics_parts.append(
            f"Recall is moderate ({recall:.2f}): some false negatives ({evaluation_metrics.false_negatives})."
        )
    else:
        metrics_parts.append(
            f"Recall is good ({recall:.2f}): few false negatives ({evaluation_metrics.false_negatives})."
        )

    # Add confusion matrix summary, might be removed and presented differently
    metrics_parts.append(
        f"Confusion matrix: TP={evaluation_metrics.true_positives}, TN={evaluation_metrics.true_negatives}, FP={evaluation_metrics.false_positives}, FN={evaluation_metrics.false_negatives}."
    )

    # Overall recommendation
    if precision < 0.5 or recall < 0.5:
        metrics_parts.append(
            "Consider model retraining or adjusting the classification threshold."
        )

    metrics_interpretation = " ".join(metrics_parts)

    return Recommendation(
        sample_assessment=" ".join(sample_parts),
        metrics_interpretation=metrics_interpretation,
    )


async def get_evaluation_results(
    data: List[EvaluationDate],
) -> EvaluationResult:
    """Evaluate classification model and generate comprehensive results.

    Args:
        data: List of EvaluationDate objects containing manual and classifier labels

    Returns:
        EvaluationResult object with metrics, data count, and recommendations

    Raises:
        ValueError: If no data is provided for evaluation
    """
    if not data:
        raise ValueError("No data provided for evaluation")
    y_true = [item.label_manual for item in data]  # list of true labels (0 or 1)
    y_pred = [
        item.label_classifier for item in data
    ]  # list of predicted labels (0 or 1)

    metrics: EvaluationMetrics = get_evaluation_metrics(y_true, y_pred)

    recommendation = create_recommendation(
        num_labeled_data=len(y_true), evaluation_metrics=metrics
    )

    return EvaluationResult(
        num_labeled_data=len(y_true),
        metrics=metrics,
        recommendation=recommendation,
    )
