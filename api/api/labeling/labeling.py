import random
from typing import List, Literal, Optional

from elasticsearch.dsl import Q

from api.database.database import Database
from api.labeling.models import MessageForLabeling

CLASS_THRESHOLD = 0.5  # Probability threshold for positive classification
TARGET_RATIO_CLASS_0 = 0.7  # Target: 70% negative (class 0), 30% positive (class 1)


def score_to_label(score: float, threshold: float = CLASS_THRESHOLD) -> Literal[0, 1]:
    """
    Convert classification score to binary label.

    Args:
        score: Classification score between 0.0 and 1.0
        threshold: Threshold for positive classification

    Returns:
        1 if score >= threshold, 0 otherwise
    """
    return 1 if score >= threshold else 0


def get_class_by_distribution(
    count_class_0: int,
    count_class_1: int,
    target_ratio_class_0: float = TARGET_RATIO_CLASS_0,
) -> Literal[0, 1]:
    """
    Determine which class to sample next to achieve the target distribution.

    Goal: Achieve approximately 70% class 0 (negative) and 30% class 1 (positive).

    Args:
        count_class_0: Current count of class 0 (negative) samples
        count_class_1: Current count of class 1 (positive) samples
        target_ratio_class_0: Target ratio for class 0 (default: 0.7 = 70%)

    Returns:
        0 if we need more negative samples, 1 if we need more positive samples
    """
    total = count_class_0 + count_class_1

    # If no samples yet, randomly pick based on target ratio
    if total == 0:
        return 0 if random.random() < target_ratio_class_0 else 1

    # Calculate current ratio of class 0
    current_ratio_class_0 = count_class_0 / total

    # If current ratio of class 0 is below target, sample more class 0 (negative)
    # If current ratio of class 0 is above target, sample more class 1 (positive)
    if current_ratio_class_0 < target_ratio_class_0:
        return 0
    else:
        return 1


def _build_class_filter(target_class: Literal[0, 1]):
    """Build a filter query for the given target class based on classification score."""
    if target_class == 0:
        return Q("range", **{"classification.score_pos": {"lt": CLASS_THRESHOLD}})
    else:
        return Q("range", **{"classification.score_pos": {"gte": CLASS_THRESHOLD}})


async def get_message_for_labeling(
    seed: Optional[int] = None,
) -> Optional[MessageForLabeling]:
    """
    Get a random message for manual labeling using Elasticsearch random sampling.

    The message is selected based on the target class distribution (70% negative, 30% positive)
    to ensure balanced labeling data.

    Criteria:
    - Message must have classification_score_pos (already classified by model)
    - Message must not exist in labeled_data index
    - Message class is selected to maintain target 70:30 distribution

    Args:
        seed: Optional seed for reproducible random sampling. If None, uses random seed.

    Returns:
        MessageForLabeling object ready for labeling, or None if no unlabeled messages available
    """
    db = Database()

    # Get already labeled message IDs and class counts
    labeled_message_ids: set[str] = set()
    count_class_0 = 0
    count_class_1 = 0

    async for doc in db.labeled_data.find(size=10000):
        labeled_message_ids.add(doc.message_id)
        if doc.label_classifier == 0:
            count_class_0 += 1
        else:
            count_class_1 += 1

    target_class = get_class_by_distribution(count_class_0, count_class_1)

    # Build base filter: must have classification score and not already labeled
    base_filter = Q("exists", field="classification.score_pos")
    if labeled_message_ids:
        base_filter = base_filter & ~Q("ids", values=list(labeled_message_ids))

    # Try target class first, then fallback to other class
    other_class: Literal[0, 1] = 1 if target_class == 0 else 0
    classes_to_try: List[Literal[0, 1]] = [target_class, other_class]

    for cls in classes_to_try:
        messages = await db.messages.find_random(
            size=1,
            filter=base_filter & _build_class_filter(cls),
            seed=seed,
        )
        if messages:
            msg = messages[0]
            return MessageForLabeling(
                id=msg.id,
                text=msg.text or msg.caption or "",
                label_classifier=score_to_label(
                    msg.classification_score_pos  # type: ignore[arg-type] # field is guaranteed to exist due to filter
                ),
            )

    return None
