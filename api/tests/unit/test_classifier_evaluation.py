from unittest.mock import Mock, patch

import pytest

from api.classifier_evaluation.evaluation import (
    create_recommendation,
    get_all_labeled_data,
    get_evaluation_metrics,
    get_evaluation_results,
)
from api.classifier_evaluation.models import EvaluationDate, EvaluationMetrics


class TestGetEvaluationMetrics:
    """Test cases for get_evaluation_metrics function with confusion matrix validation."""

    def test_perfect_classification(self):
        """Test with perfect predictions (all correct)."""
        y_true = [1, 0, 1, 0, 1, 1, 0, 0]
        y_pred = [1, 0, 1, 0, 1, 1, 0, 0]

        metrics = get_evaluation_metrics(y_true, y_pred)

        assert metrics.accuracy == 1.0
        assert metrics.precision == 1.0
        assert metrics.recall == 1.0
        assert metrics.f1_score == 1.0
        # Confusion matrix: 4 positives, 4 negatives, all correct
        assert metrics.true_positives == 4
        assert metrics.true_negatives == 4
        assert metrics.false_positives == 0
        assert metrics.false_negatives == 0

    def test_completely_wrong_classification(self):
        """Test with completely wrong predictions (all incorrect)."""
        y_true = [1, 1, 1, 1, 0, 0, 0, 0]
        y_pred = [0, 0, 0, 0, 1, 1, 1, 1]

        metrics = get_evaluation_metrics(y_true, y_pred)

        assert metrics.accuracy == 0.0
        # All positives predicted as negative, all negatives as positive
        assert metrics.precision == 0.0  # No true positives, only false positives
        assert metrics.recall == 0.0  # No true positives, only false negatives
        assert metrics.f1_score == 0.0
        assert metrics.true_positives == 0
        assert metrics.true_negatives == 0
        assert metrics.false_positives == 4
        assert metrics.false_negatives == 4

    def test_all_positive_predictions(self):
        """Test when model predicts all positives."""
        y_true = [1, 0, 1, 0, 1, 0]
        y_pred = [1, 1, 1, 1, 1, 1]

        metrics = get_evaluation_metrics(y_true, y_pred)

        assert metrics.accuracy == 0.5  # 3 correct out of 6
        assert metrics.precision == 0.5  # 3 TP / (3 TP + 3 FP)
        assert metrics.recall == 1.0  # 3 TP / (3 TP + 0 FN), all positives caught
        assert metrics.f1_score == pytest.approx(2 * 0.5 * 1.0 / (0.5 + 1.0), rel=1e-5)
        assert metrics.true_positives == 3
        assert metrics.true_negatives == 0
        assert metrics.false_positives == 3
        assert metrics.false_negatives == 0

    def test_all_negative_predictions(self):
        """Test when model predicts all negatives."""
        y_true = [1, 0, 1, 0, 1, 0]
        y_pred = [0, 0, 0, 0, 0, 0]

        metrics = get_evaluation_metrics(y_true, y_pred)

        assert metrics.accuracy == 0.5  # 3 correct out of 6
        assert metrics.precision == 0.0  # 0 TP / (0 TP + 0 FP), zero_division=0
        assert metrics.recall == 0.0  # 0 TP / (0 TP + 3 FN), all positives missed
        assert metrics.f1_score == 0.0
        assert metrics.true_positives == 0
        assert metrics.true_negatives == 3
        assert metrics.false_positives == 0
        assert metrics.false_negatives == 3

    def test_balanced_data(self):
        """Test with balanced classes (50-50 split)."""
        y_true = [1, 1, 1, 1, 0, 0, 0, 0]
        y_pred = [1, 1, 0, 0, 0, 0, 1, 1]

        metrics = get_evaluation_metrics(y_true, y_pred)

        assert metrics.accuracy == 0.5  # 4 correct out of 8
        assert metrics.precision == 0.5  # 2 TP / (2 TP + 2 FP)
        assert metrics.recall == 0.5  # 2 TP / (2 TP + 2 FN)
        assert metrics.f1_score == 0.5
        assert metrics.true_positives == 2
        assert metrics.true_negatives == 2
        assert metrics.false_positives == 2
        assert metrics.false_negatives == 2

    def test_imbalanced_data_mostly_positive(self):
        """Test with imbalanced classes (mostly positive)."""
        y_true = [1, 1, 1, 1, 1, 1, 1, 0, 0]
        y_pred = [1, 1, 1, 1, 1, 0, 0, 0, 0]

        metrics = get_evaluation_metrics(y_true, y_pred)

        # 7 correct out of 9
        assert metrics.accuracy == pytest.approx(7 / 9, rel=1e-5)
        assert 0.0 <= metrics.precision <= 1.0
        assert 0.0 <= metrics.recall <= 1.0
        assert 0.0 <= metrics.f1_score <= 1.0

    def test_imbalanced_data_mostly_negative(self):
        """Test with imbalanced classes (mostly negative)."""
        y_true = [0, 0, 0, 0, 0, 0, 0, 1, 1]
        y_pred = [0, 0, 0, 0, 0, 1, 1, 1, 1]

        metrics = get_evaluation_metrics(y_true, y_pred)

        # 7 correct out of 9
        assert metrics.accuracy == pytest.approx(7 / 9, rel=1e-5)
        assert 0.0 <= metrics.precision <= 1.0
        assert 0.0 <= metrics.recall <= 1.0
        assert 0.0 <= metrics.f1_score <= 1.0

    def test_single_sample(self):
        """Test with single sample (edge case)."""
        # Correct prediction
        metrics = get_evaluation_metrics([1], [1])
        assert metrics.accuracy == 1.0

        # Wrong prediction
        metrics = get_evaluation_metrics([1], [0])
        assert metrics.accuracy == 0.0

    def test_two_samples(self):
        """Test with minimal two samples."""
        # Both correct
        metrics = get_evaluation_metrics([1, 0], [1, 0])
        assert metrics.accuracy == 1.0

        # Both wrong
        metrics = get_evaluation_metrics([1, 0], [0, 1])
        assert metrics.accuracy == 0.0

        # One correct
        metrics = get_evaluation_metrics([1, 0], [1, 1])
        assert metrics.accuracy == 0.5

    def test_all_zeros_true_labels(self):
        """Test when all true labels are 0."""
        y_true = [0, 0, 0, 0, 0]
        y_pred = [0, 0, 1, 0, 1]

        metrics = get_evaluation_metrics(y_true, y_pred)

        assert metrics.accuracy == 0.6  # 3 correct out of 5
        # When no positive samples exist in y_true, recall for class 1 is undefined
        # but weighted average handles this
        assert 0.0 <= metrics.precision <= 1.0
        assert 0.0 <= metrics.recall <= 1.0
        assert 0.0 <= metrics.f1_score <= 1.0

    def test_all_ones_true_labels(self):
        """Test when all true labels are 1."""
        y_true = [1, 1, 1, 1, 1]
        y_pred = [1, 1, 0, 1, 0]

        metrics = get_evaluation_metrics(y_true, y_pred)

        assert metrics.accuracy == 0.6  # 3 correct out of 5
        assert 0.0 <= metrics.precision <= 1.0
        assert 0.0 <= metrics.recall <= 1.0
        assert 0.0 <= metrics.f1_score <= 1.0

    def test_zero_division_handling(self):
        """Test that zero_division parameter prevents errors."""
        # When all predictions are 0 and all true labels are 1
        y_true = [1, 1, 1]
        y_pred = [0, 0, 0]

        # Should not raise ZeroDivisionError
        metrics = get_evaluation_metrics(y_true, y_pred)

        assert metrics.accuracy == 0.0
        assert isinstance(metrics.precision, float)
        assert isinstance(metrics.recall, float)
        assert isinstance(metrics.f1_score, float)

    def test_return_type_float(self):
        """Test that all metrics are returned as floats."""
        y_true = [1, 0, 1, 0]
        y_pred = [1, 0, 0, 1]

        metrics = get_evaluation_metrics(y_true, y_pred)

        assert isinstance(metrics.accuracy, float)
        assert isinstance(metrics.precision, float)
        assert isinstance(metrics.recall, float)
        assert isinstance(metrics.f1_score, float)

    def test_metrics_structure(self):
        """Test that returned object is EvaluationMetrics model with all fields."""
        y_true = [1, 0, 1, 0]
        y_pred = [1, 0, 1, 0]

        metrics = get_evaluation_metrics(y_true, y_pred)

        assert isinstance(metrics, EvaluationMetrics)
        assert hasattr(metrics, "accuracy")
        assert hasattr(metrics, "precision")
        assert hasattr(metrics, "recall")
        assert hasattr(metrics, "f1_score")
        assert hasattr(metrics, "true_positives")
        assert hasattr(metrics, "true_negatives")
        assert hasattr(metrics, "false_positives")
        assert hasattr(metrics, "false_negatives")
        # Validate confusion matrix adds up
        total = (
            metrics.true_positives
            + metrics.true_negatives
            + metrics.false_positives
            + metrics.false_negatives
        )
        assert total == len(y_true)


class TestCreateRecommendation:
    """Test cases for create_recommendation function with confusion matrix-based logic."""

    def test_critically_insufficient_data(self):
        """Test when either class has < 20 samples - should show critical warning."""
        metrics = EvaluationMetrics(
            accuracy=0.0,
            precision=0.0,
            recall=0.0,
            f1_score=0.0,
            true_positives=0,
            false_negatives=2,  # 2 positive class samples
            true_negatives=0,
            false_positives=1,  # 1 negative class sample
        )

        recommendation = create_recommendation(3, metrics)

        assert "⚠️ WARNING" in recommendation.sample_assessment
        assert "Very few labeled samples detected" in recommendation.sample_assessment
        assert "2 positive class samples" in recommendation.sample_assessment
        assert "1 negative class samples" in recommendation.sample_assessment
        assert "NOT RELIABLE" in recommendation.sample_assessment
        assert (
            "should NOT be used for decision-making" in recommendation.sample_assessment
        )

    def test_insufficient_positive_class_data(self):
        """Test when positive class has < 100 samples."""
        metrics = EvaluationMetrics(
            accuracy=0.7,
            precision=0.65,
            recall=0.68,
            f1_score=0.66,
            true_positives=40,
            false_negatives=30,  # 70 positive class samples
            true_negatives=80,
            false_positives=20,  # 100 negative class samples
        )

        recommendation = create_recommendation(200, metrics)

        assert "rule of thumb" in recommendation.sample_assessment.lower()
        assert "at least 100" in recommendation.sample_assessment.lower()
        assert "70 positive class samples" in recommendation.sample_assessment
        assert "100 negative class samples" in recommendation.sample_assessment
        assert "more data" in recommendation.sample_assessment.lower()

    def test_insufficient_negative_class_data(self):
        """Test when negative class has < 100 samples."""
        metrics = EvaluationMetrics(
            accuracy=0.75,
            precision=0.8,
            recall=0.7,
            f1_score=0.75,
            true_positives=80,
            false_negatives=30,  # 110 positive class samples
            true_negatives=40,
            false_positives=30,  # 70 negative class samples
        )

        recommendation = create_recommendation(180, metrics)

        assert "rule of thumb" in recommendation.sample_assessment.lower()
        assert "at least 100" in recommendation.sample_assessment.lower()
        assert "110 positive class samples" in recommendation.sample_assessment
        assert "70 negative class samples" in recommendation.sample_assessment

    def test_insufficient_both_classes(self):
        """Test when both classes have < 100 samples."""
        metrics = EvaluationMetrics(
            accuracy=0.7,
            precision=0.65,
            recall=0.68,
            f1_score=0.66,
            true_positives=40,
            false_negatives=30,  # 70 positive
            true_negatives=40,
            false_positives=30,  # 70 negative
        )

        recommendation = create_recommendation(140, metrics)

        assert "rule of thumb" in recommendation.sample_assessment.lower()
        assert "70 positive class samples" in recommendation.sample_assessment
        assert "70 negative class samples" in recommendation.sample_assessment

    def test_sufficient_data_both_classes(self):
        """Test when both classes have >= 100 samples."""
        metrics = EvaluationMetrics(
            accuracy=0.8,
            precision=0.75,
            recall=0.78,
            f1_score=0.76,
            true_positives=90,
            false_negatives=20,  # 110 positive
            true_negatives=100,
            false_positives=10,  # 110 negative
        )

        recommendation = create_recommendation(220, metrics)

        assert "seems reasonable" in recommendation.sample_assessment.lower()
        assert "110 positive class samples" in recommendation.sample_assessment
        assert "110 negative class samples" in recommendation.sample_assessment
        assert "more data" in recommendation.sample_assessment.lower()  # General note

    def test_low_precision_high_false_positives(self):
        """Test interpretation when precision < 0.5 (many false positives)."""
        metrics = EvaluationMetrics(
            accuracy=0.55,
            precision=0.4,
            recall=0.7,
            f1_score=0.51,
            true_positives=70,
            false_negatives=30,
            true_negatives=40,
            false_positives=105,  # High FP
        )

        recommendation = create_recommendation(245, metrics)

        assert "precision is low" in recommendation.metrics_interpretation.lower()
        assert (
            "0.40" in recommendation.metrics_interpretation
            or "0.4" in recommendation.metrics_interpretation
        )
        assert "many false positives" in recommendation.metrics_interpretation.lower()
        assert "105" in recommendation.metrics_interpretation
        assert "incorrectly classifies" in recommendation.metrics_interpretation.lower()

    def test_moderate_precision(self):
        """Test interpretation when 0.5 <= precision < 0.7."""
        metrics = EvaluationMetrics(
            accuracy=0.7,
            precision=0.6,
            recall=0.75,
            f1_score=0.67,
            true_positives=75,
            false_negatives=25,
            true_negatives=70,
            false_positives=50,
        )

        recommendation = create_recommendation(220, metrics)

        assert "precision is moderate" in recommendation.metrics_interpretation.lower()
        assert (
            "0.60" in recommendation.metrics_interpretation
            or "0.6" in recommendation.metrics_interpretation
        )
        assert "some false positives" in recommendation.metrics_interpretation.lower()

    def test_good_precision_low_false_positives(self):
        """Test interpretation when precision >= 0.7 (few false positives)."""
        metrics = EvaluationMetrics(
            accuracy=0.85,
            precision=0.8,
            recall=0.75,
            f1_score=0.77,
            true_positives=90,
            false_negatives=30,
            true_negatives=110,
            false_positives=20,
        )

        recommendation = create_recommendation(250, metrics)

        assert "precision is good" in recommendation.metrics_interpretation.lower()
        assert (
            "0.80" in recommendation.metrics_interpretation
            or "0.8" in recommendation.metrics_interpretation
        )
        assert "few false positives" in recommendation.metrics_interpretation.lower()

    def test_low_recall_high_false_negatives(self):
        """Test interpretation when recall < 0.5 (many false negatives)."""
        metrics = EvaluationMetrics(
            accuracy=0.6,
            precision=0.7,
            recall=0.4,
            f1_score=0.51,
            true_positives=40,
            false_negatives=60,  # High FN
            true_negatives=110,
            false_positives=17,
        )

        recommendation = create_recommendation(227, metrics)

        assert "recall is low" in recommendation.metrics_interpretation.lower()
        assert (
            "0.40" in recommendation.metrics_interpretation
            or "0.4" in recommendation.metrics_interpretation
        )
        assert "many false negatives" in recommendation.metrics_interpretation.lower()
        assert "60" in recommendation.metrics_interpretation
        assert (
            "misses many positive cases"
            in recommendation.metrics_interpretation.lower()
        )

    def test_moderate_recall(self):
        """Test interpretation when 0.5 <= recall < 0.7."""
        metrics = EvaluationMetrics(
            accuracy=0.72,
            precision=0.75,
            recall=0.6,
            f1_score=0.67,
            true_positives=60,
            false_negatives=40,
            true_negatives=110,
            false_positives=20,
        )

        recommendation = create_recommendation(230, metrics)

        assert "recall is moderate" in recommendation.metrics_interpretation.lower()
        assert "some false negatives" in recommendation.metrics_interpretation.lower()

    def test_good_recall_low_false_negatives(self):
        """Test interpretation when recall >= 0.7 (few false negatives)."""
        metrics = EvaluationMetrics(
            accuracy=0.85,
            precision=0.75,
            recall=0.8,
            f1_score=0.77,
            true_positives=96,
            false_negatives=24,
            true_negatives=110,
            false_positives=32,
        )

        recommendation = create_recommendation(262, metrics)

        assert "recall is good" in recommendation.metrics_interpretation.lower()
        assert "few false negatives" in recommendation.metrics_interpretation.lower()

    def test_confusion_matrix_in_output(self):
        """Test that confusion matrix counts are included in metrics interpretation."""
        metrics = EvaluationMetrics(
            accuracy=0.8,
            precision=0.75,
            recall=0.78,
            f1_score=0.76,
            true_positives=85,
            false_negatives=25,
            true_negatives=115,
            false_positives=25,
        )

        recommendation = create_recommendation(250, metrics)

        # Check confusion matrix is mentioned
        assert "confusion matrix" in recommendation.metrics_interpretation.lower()
        assert "tp=85" in recommendation.metrics_interpretation.lower()
        assert "tn=115" in recommendation.metrics_interpretation.lower()
        assert "fp=25" in recommendation.metrics_interpretation.lower()
        assert "fn=25" in recommendation.metrics_interpretation.lower()

    def test_retraining_recommendation_low_metrics(self):
        """Test retraining recommendation when precision or recall < 0.5."""
        metrics = EvaluationMetrics(
            accuracy=0.5,
            precision=0.45,
            recall=0.48,
            f1_score=0.46,
            true_positives=48,
            false_negatives=52,
            true_negatives=80,
            false_positives=59,
        )

        recommendation = create_recommendation(239, metrics)

        assert (
            "retraining" in recommendation.metrics_interpretation.lower()
            or "adjusting" in recommendation.metrics_interpretation.lower()
        )

    def test_return_structure(self):
        """Test that returned object has correct structure."""
        metrics = EvaluationMetrics(
            accuracy=0.7,
            precision=0.65,
            recall=0.68,
            f1_score=0.66,
            true_positives=68,
            false_negatives=32,
            true_negatives=85,
            false_positives=40,
        )

        recommendation = create_recommendation(225, metrics)

        assert hasattr(recommendation, "sample_assessment")
        assert hasattr(recommendation, "metrics_interpretation")
        assert isinstance(recommendation.sample_assessment, str)
        assert isinstance(recommendation.metrics_interpretation, str)
        # Both should be non-empty
        assert len(recommendation.sample_assessment) > 0
        assert len(recommendation.metrics_interpretation) > 0


class TestGetAllLabeledData:
    """Test cases for get_all_labeled_data function."""

    def _create_mock_labeled_data(
        self, message_id: str, label_classifier, label_manual
    ):
        """Helper to create a mock labeled data object."""
        labeled = Mock()
        labeled.message_id = message_id
        labeled.label_classifier = label_classifier
        labeled.label_manual = label_manual
        return labeled

    async def _create_async_iterator(self, items):
        """Helper to create async iterator from list."""
        for item in items:
            yield item

    @pytest.mark.asyncio
    async def test_all_complete_records(self):
        """Test with all records having both labels."""
        with patch("api.classifier_evaluation.evaluation.Database") as mock_db_class:
            mock_db = Mock()
            mock_db_class.return_value = mock_db

            labeled_data = [
                self._create_mock_labeled_data("msg1", 1, 1),
                self._create_mock_labeled_data("msg2", 0, 1),
                self._create_mock_labeled_data("msg3", 1, 0),
                self._create_mock_labeled_data("msg4", 0, 0),
            ]
            mock_db.labeled_data.find.return_value = self._create_async_iterator(
                labeled_data
            )

            result = await get_all_labeled_data()

            assert len(result) == 4
            assert all(isinstance(item, EvaluationDate) for item in result)
            assert result[0].message_id == "msg1"
            assert result[0].label_classifier == 1
            assert result[0].label_manual == 1

    @pytest.mark.asyncio
    async def test_filters_missing_classifier_label(self, caplog):
        """Test that records without classifier label are filtered out."""
        with patch("api.classifier_evaluation.evaluation.Database") as mock_db_class:
            mock_db = Mock()
            mock_db_class.return_value = mock_db

            labeled_data = [
                self._create_mock_labeled_data("msg1", 1, 1),
                self._create_mock_labeled_data("msg2", None, 1),  # Missing classifier
                self._create_mock_labeled_data("msg3", 0, 0),
            ]
            mock_db.labeled_data.find.return_value = self._create_async_iterator(
                labeled_data
            )

            result = await get_all_labeled_data()

            assert len(result) == 2
            assert result[0].message_id == "msg1"
            assert result[1].message_id == "msg3"

            # Check warning was logged
            assert "1 record(s) skipped" in caplog.text

    @pytest.mark.asyncio
    async def test_filters_missing_manual_label(self, caplog):
        """Test that records without manual label are filtered out."""
        with patch("api.classifier_evaluation.evaluation.Database") as mock_db_class:
            mock_db = Mock()
            mock_db_class.return_value = mock_db

            labeled_data = [
                self._create_mock_labeled_data("msg1", 1, 1),
                self._create_mock_labeled_data("msg2", 1, None),  # Missing manual
                self._create_mock_labeled_data("msg3", 0, 0),
            ]
            mock_db.labeled_data.find.return_value = self._create_async_iterator(
                labeled_data
            )

            result = await get_all_labeled_data()

            assert len(result) == 2
            assert result[0].message_id == "msg1"
            assert result[1].message_id == "msg3"

            # Check warning was logged
            assert "1 record(s) skipped" in caplog.text

    @pytest.mark.asyncio
    async def test_filters_both_labels_missing(self, caplog):
        """Test that records without both labels are filtered out."""
        with patch("api.classifier_evaluation.evaluation.Database") as mock_db_class:
            mock_db = Mock()
            mock_db_class.return_value = mock_db

            labeled_data = [
                self._create_mock_labeled_data("msg1", 1, 1),
                self._create_mock_labeled_data("msg2", None, None),  # Both missing
                self._create_mock_labeled_data("msg3", 0, 0),
            ]
            mock_db.labeled_data.find.return_value = self._create_async_iterator(
                labeled_data
            )

            result = await get_all_labeled_data()

            assert len(result) == 2
            assert "1 record(s) skipped" in caplog.text

    @pytest.mark.asyncio
    async def test_multiple_incomplete_records(self, caplog):
        """Test with multiple incomplete records."""
        with patch("api.classifier_evaluation.evaluation.Database") as mock_db_class:
            mock_db = Mock()
            mock_db_class.return_value = mock_db

            labeled_data = [
                self._create_mock_labeled_data("msg1", 1, 1),
                self._create_mock_labeled_data("msg2", None, 1),
                self._create_mock_labeled_data("msg3", 1, None),
                self._create_mock_labeled_data("msg4", None, None),
                self._create_mock_labeled_data("msg5", 0, 0),
            ]
            mock_db.labeled_data.find.return_value = self._create_async_iterator(
                labeled_data
            )

            result = await get_all_labeled_data()

            assert len(result) == 2  # Only msg1 and msg5 are complete
            assert "3 record(s) skipped" in caplog.text

    @pytest.mark.asyncio
    async def test_empty_database(self, caplog):
        """Test with no labeled data in database."""
        with patch("api.classifier_evaluation.evaluation.Database") as mock_db_class:
            mock_db = Mock()
            mock_db_class.return_value = mock_db

            mock_db.labeled_data.find.return_value = self._create_async_iterator([])

            result = await get_all_labeled_data()

            assert len(result) == 0
            assert result == []

            # No warning should be logged when no data
            assert "skipped" not in caplog.text

    @pytest.mark.asyncio
    async def test_all_incomplete_records(self, caplog):
        """Test when all records are incomplete."""
        with patch("api.classifier_evaluation.evaluation.Database") as mock_db_class:
            mock_db = Mock()
            mock_db_class.return_value = mock_db

            labeled_data = [
                self._create_mock_labeled_data("msg1", None, 1),
                self._create_mock_labeled_data("msg2", 1, None),
                self._create_mock_labeled_data("msg3", None, None),
            ]
            mock_db.labeled_data.find.return_value = self._create_async_iterator(
                labeled_data
            )

            await get_all_labeled_data()

            assert "3 record(s) skipped" in caplog.text
            assert "Total records: 3, Usable: 0" in caplog.text

    @pytest.mark.asyncio
    async def test_warning_message_format(self, caplog):
        """Test that warning message has correct format."""
        with patch("api.classifier_evaluation.evaluation.Database") as mock_db_class:
            mock_db = Mock()
            mock_db_class.return_value = mock_db

            labeled_data = [
                self._create_mock_labeled_data("msg1", 1, 1),
                self._create_mock_labeled_data("msg2", None, 1),
            ]
            mock_db.labeled_data.find.return_value = self._create_async_iterator(
                labeled_data
            )

            await get_all_labeled_data()

            assert "Total records: 2" in caplog.text
            assert "Usable: 1" in caplog.text

    @pytest.mark.asyncio
    async def test_no_warning_when_all_complete(self, caplog):
        """Test that no warning is logged when all records are complete."""
        with patch("api.classifier_evaluation.evaluation.Database") as mock_db_class:
            mock_db = Mock()
            mock_db_class.return_value = mock_db

            labeled_data = [
                self._create_mock_labeled_data("msg1", 1, 1),
                self._create_mock_labeled_data("msg2", 0, 0),
            ]
            mock_db.labeled_data.find.return_value = self._create_async_iterator(
                labeled_data
            )

            result = await get_all_labeled_data()

            assert len(result) == 2
            assert "skipped" not in caplog.text

    @pytest.mark.asyncio
    async def test_label_values_preserved(self):
        """Test that label values are correctly preserved in output."""
        with patch("api.classifier_evaluation.evaluation.Database") as mock_db_class:
            mock_db = Mock()
            mock_db_class.return_value = mock_db

            labeled_data = [
                self._create_mock_labeled_data("msg1", 1, 0),
                self._create_mock_labeled_data("msg2", 0, 1),
            ]
            mock_db.labeled_data.find.return_value = self._create_async_iterator(
                labeled_data
            )

            result = await get_all_labeled_data()

            assert result[0].label_classifier == 1
            assert result[0].label_manual == 0
            assert result[1].label_classifier == 0
            assert result[1].label_manual == 1


class TestGetEvaluationResults:
    """Test cases for get_evaluation_results function."""

    def _create_evaluation_data(self, classifier_labels, manual_labels):
        """Helper to create EvaluationDate objects."""
        return [
            EvaluationDate(
                message_id=f"msg{i}",
                label_classifier=c_label,
                label_manual=m_label,
            )
            for i, (c_label, m_label) in enumerate(
                zip(classifier_labels, manual_labels)
            )
        ]

    @pytest.mark.asyncio
    async def test_valid_evaluation_data(self):
        """Test with valid evaluation data."""
        data = self._create_evaluation_data(
            classifier_labels=[1, 0, 1, 0], manual_labels=[1, 0, 0, 0]
        )

        result = await get_evaluation_results(data)

        assert result.num_labeled_data == 4
        assert isinstance(result.metrics, EvaluationMetrics)
        assert result.recommendation is not None
        assert result.metrics.accuracy == 0.75  # 3 correct out of 4

    @pytest.mark.asyncio
    async def test_perfect_predictions(self):
        """Test when all predictions are correct."""
        data = self._create_evaluation_data(
            classifier_labels=[1, 0, 1, 0, 1], manual_labels=[1, 0, 1, 0, 1]
        )

        result = await get_evaluation_results(data)

        assert result.num_labeled_data == 5
        assert result.metrics.accuracy == 1.0
        assert result.metrics.precision == 1.0
        assert result.metrics.recall == 1.0
        assert result.metrics.f1_score == 1.0

    @pytest.mark.asyncio
    async def test_completely_wrong_predictions(self):
        """Test when all predictions are wrong."""
        data = self._create_evaluation_data(
            classifier_labels=[1, 1, 1, 1], manual_labels=[0, 0, 0, 0]
        )

        result = await get_evaluation_results(data)

        assert result.num_labeled_data == 4
        assert result.metrics.accuracy == 0.0

    @pytest.mark.asyncio
    async def test_single_data_point(self):
        """Test with single data point (edge case)."""
        data = self._create_evaluation_data(classifier_labels=[1], manual_labels=[1])

        result = await get_evaluation_results(data)

        assert result.num_labeled_data == 1
        assert result.metrics.accuracy == 1.0

    @pytest.mark.asyncio
    async def test_two_data_points(self):
        """Test with minimal two data points."""
        data = self._create_evaluation_data(
            classifier_labels=[1, 0], manual_labels=[1, 0]
        )

        result = await get_evaluation_results(data)

        assert result.num_labeled_data == 2
        assert result.metrics.accuracy == 1.0

    @pytest.mark.asyncio
    async def test_empty_data_raises_error(self):
        """Test that empty data raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            await get_evaluation_results([])

        assert "No data provided for evaluation" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_recommendation_included(self):
        """Test that recommendation is included in result."""
        data = self._create_evaluation_data(
            classifier_labels=[1, 0, 1, 0] * 30,  # 120 samples (60 per class)
            manual_labels=[1, 0, 1, 0] * 30,
        )

        result = await get_evaluation_results(data)

        assert result.recommendation is not None
        assert hasattr(result.recommendation, "sample_assessment")
        assert hasattr(result.recommendation, "metrics_interpretation")
        # With 60 per class (< 100), should suggest more data
        assert "rule of thumb" in result.recommendation.sample_assessment.lower()

    @pytest.mark.asyncio
    async def test_large_dataset(self):
        """Test with large dataset."""
        # Create 1000 samples
        data = self._create_evaluation_data(
            classifier_labels=[1, 0] * 500, manual_labels=[1, 0] * 500
        )

        result = await get_evaluation_results(data)

        assert result.num_labeled_data == 1000
        assert result.metrics.accuracy == 1.0

    @pytest.mark.asyncio
    async def test_balanced_classes(self):
        """Test with balanced class distribution."""
        data = self._create_evaluation_data(
            classifier_labels=[1, 1, 1, 1, 0, 0, 0, 0],
            manual_labels=[1, 1, 0, 0, 0, 0, 1, 1],
        )

        result = await get_evaluation_results(data)

        assert result.num_labeled_data == 8
        assert result.metrics.accuracy == 0.5  # 4 correct out of 8

    @pytest.mark.asyncio
    async def test_imbalanced_classes(self):
        """Test with imbalanced class distribution."""
        data = self._create_evaluation_data(
            classifier_labels=[1, 1, 1, 1, 1, 1, 1, 0, 0],
            manual_labels=[1, 1, 1, 1, 1, 0, 0, 0, 0],
        )

        result = await get_evaluation_results(data)

        assert result.num_labeled_data == 9
        # 7 correct out of 9
        assert result.metrics.accuracy == pytest.approx(7 / 9, rel=1e-5)

    @pytest.mark.asyncio
    async def test_result_structure(self):
        """Test that result has correct structure."""
        data = self._create_evaluation_data(
            classifier_labels=[1, 0, 1], manual_labels=[1, 0, 0]
        )

        result = await get_evaluation_results(data)

        assert hasattr(result, "num_labeled_data")
        assert hasattr(result, "metrics")
        assert hasattr(result, "recommendation")
        assert isinstance(result.num_labeled_data, int)
        assert isinstance(result.metrics, EvaluationMetrics)

    @pytest.mark.asyncio
    async def test_metrics_integration_with_recommendation(self):
        """Test that metrics correctly influence recommendation."""
        # Poor performance with insufficient data (< 20 samples triggers critical warning)
        poor_data = self._create_evaluation_data(
            classifier_labels=[1, 1, 1, 1, 1],  # All positive
            manual_labels=[0, 0, 0, 0, 0],  # All negative (all wrong)
        )

        result = await get_evaluation_results(poor_data)

        assert result.num_labeled_data == 5
        assert result.metrics.accuracy == 0.0
        assert result.recommendation is not None
        # With only 5 samples, should get critical warning instead of "rule of thumb"
        assert "⚠️ WARNING" in result.recommendation.sample_assessment
        assert "NOT RELIABLE" in result.recommendation.sample_assessment
        # Should mention precision/recall issues (could be "low" or edge case like "undefined" or "everything as positive")
        metrics_text = result.recommendation.metrics_interpretation.lower()
        assert (
            "low" in metrics_text
            or "undefined" in metrics_text
            or "everything as positive" in metrics_text
            or "never predicted" in metrics_text
        )
        assert (
            "retraining" in result.recommendation.metrics_interpretation.lower()
            or "adjusting" in result.recommendation.metrics_interpretation.lower()
        )

    @pytest.mark.asyncio
    async def test_labels_extracted_correctly(self):
        """Test that labels are extracted correctly from EvaluationDate objects."""
        data = [
            EvaluationDate(message_id="msg1", label_classifier=1, label_manual=0),
            EvaluationDate(message_id="msg2", label_classifier=0, label_manual=1),
            EvaluationDate(message_id="msg3", label_classifier=1, label_manual=1),
        ]

        result = await get_evaluation_results(data)

        # Should use label_manual as ground truth and label_classifier as predictions
        # Predictions: [1, 0, 1], True: [0, 1, 1] -> 1 correct (only msg3)
        assert result.num_labeled_data == 3
        assert result.metrics.accuracy == pytest.approx(1 / 3, rel=1e-5)
