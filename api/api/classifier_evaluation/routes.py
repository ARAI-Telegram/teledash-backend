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
        description="Return classification evaluation results",
        tags=["evaluation"],
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
            EvaluationResult with metrics, data count, and recommendations

        Raises:
            404: No labeled data found
            500: Error during evaluation
        """
        try:
            # Fetch all labeled data
            labeled_data = await get_all_labeled_data()

            if not labeled_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No labeled data found with both manual and classifier labels",
                )

            # Calculate evaluation metrics
            evaluation_result = await get_evaluation_results(labeled_data)
            return evaluation_result

        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error during evaluation: {str(e)}",
            )

    return router
