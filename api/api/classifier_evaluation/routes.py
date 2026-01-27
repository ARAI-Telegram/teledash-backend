from fastapi import APIRouter, Depends, HTTPException, status

from api.accounts.auth import Account, get_current_active_verified_user
from api.classifier_evaluation.evaluation import (
    get_all_labeled_data,
    get_evaluation_results,
)
from api.classifier_evaluation.models import EvaluationResult


def get_evaluation_router():
    router = APIRouter()
    current_active_verified_user = get_current_active_verified_user()

    @router.get(
        "/evaluation",
        tags=["evaluation"],
        description="Return classification evaluation results",
        response_model=EvaluationResult,
        response_model_exclude_none=True,
    )
    async def evaluate(
        account: Account = Depends(current_active_verified_user),
    ) -> EvaluationResult:
        """
        Evaluate classification model performance using labeled data.

        Fetches all labeled data from the labeled_data index and calculates
        evaluation metrics (accuracy, precision, recall, f1_score) along with
        recommendations based on data quantity and model performance.

        Returns:
            EvaluationResult with metrics, sample assessment, and recommendations

        Raises:
            400: No labeled data available for evaluation
        """
        # Fetch all labeled data
        labeled_data = await get_all_labeled_data()

        if not labeled_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No labeled data available for evaluation. Please label some messages first using the /labeling endpoint.",
            )

        # Calculate evaluation metrics
        evaluation_result = await get_evaluation_results(labeled_data)
        return evaluation_result

    return router
