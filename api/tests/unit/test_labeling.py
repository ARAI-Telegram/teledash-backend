from unittest.mock import AsyncMock, Mock, patch

import pytest

from api.labeling.labeling import (
    TARGET_RATIO_CLASS_0,
    get_class_by_distribution,
    get_message_for_labeling,
    score_to_label,
)
from api.labeling.models import MessageForLabeling


class TestScoreToLabel:
    """Test cases for score_to_label function."""

    def test_score_above_default_threshold(self):
        """Test score above default threshold (0.5) returns 1."""
        assert score_to_label(0.6) == 1
        assert score_to_label(0.75) == 1
        assert score_to_label(0.9) == 1
        assert score_to_label(1.0) == 1

    def test_score_below_default_threshold(self):
        """Test score below default threshold (0.5) returns 0."""
        assert score_to_label(0.4) == 0
        assert score_to_label(0.25) == 0
        assert score_to_label(0.1) == 0
        assert score_to_label(0.0) == 0

    def test_score_equal_to_default_threshold(self):
        """Test score equal to default threshold (0.5) returns 1."""
        assert score_to_label(0.5) == 1

    def test_custom_threshold_higher(self):
        """Test with custom threshold higher than default."""
        assert score_to_label(0.6, threshold=0.7) == 0
        assert score_to_label(0.7, threshold=0.7) == 1
        assert score_to_label(0.8, threshold=0.7) == 1

    def test_custom_threshold_lower(self):
        """Test with custom threshold lower than default."""
        assert score_to_label(0.2, threshold=0.3) == 0
        assert score_to_label(0.3, threshold=0.3) == 1
        assert score_to_label(0.4, threshold=0.3) == 1

    def test_extreme_thresholds(self):
        """Test with extreme threshold values."""
        # Threshold at 0 - everything should be positive
        assert score_to_label(0.0, threshold=0.0) == 1
        assert score_to_label(0.5, threshold=0.0) == 1

        # Threshold at 1 - only score of 1 should be positive
        assert score_to_label(0.99, threshold=1.0) == 0
        assert score_to_label(1.0, threshold=1.0) == 1

    def test_score_boundaries(self):
        """Test boundary values for scores."""
        # Minimum score
        assert score_to_label(0.0, threshold=0.5) == 0
        assert score_to_label(0.0, threshold=0.0) == 1

        # Maximum score
        assert score_to_label(1.0, threshold=0.5) == 1
        assert score_to_label(1.0, threshold=1.0) == 1

    def test_return_type(self):
        """Test that return type is correct literal (0 or 1)."""
        result_positive = score_to_label(0.8)
        result_negative = score_to_label(0.2)

        assert result_positive == 1
        assert result_negative == 0
        assert isinstance(result_positive, int)
        assert isinstance(result_negative, int)


class TestGetClassByDistribution:
    """Test cases for get_class_by_distribution function."""

    def test_no_samples_returns_based_on_ratio(self):
        """Test that with no samples, returns based on target ratio probabilistically."""
        with patch("api.labeling.labeling.random.random") as mock_random:
            # Mock random to return < 0.7 -> should return 0 (class 0)
            mock_random.return_value = 0.5
            assert get_class_by_distribution(0, 0) == 0

            # Mock random to return >= 0.7 -> should return 1 (class 1)
            mock_random.return_value = 0.8
            assert get_class_by_distribution(0, 0) == 1

    def test_needs_more_class_0(self):
        """Test when current ratio of class 0 is below target."""
        # Current: 50% class 0, target: 70% -> need more class 0
        assert get_class_by_distribution(50, 50) == 0
        # Current: 60% class 0, target: 70% -> need more class 0
        assert get_class_by_distribution(60, 40) == 0

    def test_needs_more_class_1(self):
        """Test when current ratio of class 0 is above target."""
        # Current: 80% class 0, target: 70% -> need more class 1
        assert get_class_by_distribution(80, 20) == 1
        # Current: 90% class 0, target: 70% -> need more class 1
        assert get_class_by_distribution(90, 10) == 1

    def test_at_target_ratio(self):
        """Test when exactly at target ratio."""
        # Current: 70% class 0, target: 70% -> should return 1 (>=)
        assert get_class_by_distribution(70, 30) == 1
        assert get_class_by_distribution(7, 3) == 1

    def test_extreme_imbalance_needs_class_0(self):
        """Test with extreme imbalance needing class 0."""
        # All class 1 -> need class 0
        assert get_class_by_distribution(0, 100) == 0
        # Very few class 0 -> need class 0
        assert get_class_by_distribution(10, 90) == 0

    def test_extreme_imbalance_needs_class_1(self):
        """Test with extreme imbalance needing class 1."""
        # All class 0 -> need class 1
        assert get_class_by_distribution(100, 0) == 1
        # Very few class 1 -> need class 1
        assert get_class_by_distribution(95, 5) == 1

    def test_single_sample_scenarios(self):
        """Test with single sample."""
        # 1 class 0, 0 class 1 -> 100% class 0 > 70%, need class 1
        assert get_class_by_distribution(1, 0) == 1
        # 0 class 0, 1 class 1 -> 0% class 0 < 70%, need class 0
        assert get_class_by_distribution(0, 1) == 0

    def test_default_target_ratio(self):
        """Test that default target ratio is 0.7."""
        assert TARGET_RATIO_CLASS_0 == 0.7


class TestGetMessageForLabeling:
    """Test cases for get_message_for_labeling function."""

    def _create_mock_message(
        self,
        msg_id: str,
        text: str | None = None,
        caption: str | None = None,
        score: float | None = None,
    ):
        """Helper to create a mock message object."""
        msg = Mock()
        msg.id = msg_id
        msg.text = text
        msg.caption = caption
        if score is not None:
            msg.classification_score_pos = score
        return msg

    def _create_mock_labeled_data(self, message_id: str, label: int = 0):
        """Helper to create a mock labeled data object."""
        labeled = Mock()
        labeled.message_id = message_id
        labeled.label_classifier = label
        return labeled

    async def _create_async_iterator(self, items):
        """Helper to create async iterator from list."""
        for item in items:
            yield item

    def _create_labeled_data_list(self, count_class_0: int, count_class_1: int):
        """Helper to create labeled data list with given class distribution."""
        items = []
        for i in range(count_class_0):
            items.append(self._create_mock_labeled_data(f"labeled_0_{i}", label=0))
        for i in range(count_class_1):
            items.append(self._create_mock_labeled_data(f"labeled_1_{i}", label=1))
        return items

    @pytest.mark.asyncio
    async def test_basic_functionality(self):
        """Test basic functionality with valid message."""
        with patch("api.labeling.labeling.Database") as mock_db_class:
            mock_db = Mock()
            mock_db_class.return_value = mock_db

            # Mock labeled_data.find() to return 70:30 distribution
            labeled_data = self._create_labeled_data_list(70, 30)
            mock_db.labeled_data.find.return_value = self._create_async_iterator(
                labeled_data
            )

            message = self._create_mock_message("msg1", text="Hello world", score=0.8)
            mock_db.messages.find_random = AsyncMock(return_value=[message])

            result = await get_message_for_labeling()

            assert result is not None
            assert result.id == "msg1"
            assert result.text == "Hello world"
            assert result.label_classifier == 1  # score 0.8 >= 0.5

    @pytest.mark.asyncio
    async def test_returns_single_message(self):
        """Test that function returns a single MessageForLabeling, not a list."""
        with patch("api.labeling.labeling.Database") as mock_db_class:
            mock_db = Mock()
            mock_db_class.return_value = mock_db

            labeled_data = self._create_labeled_data_list(70, 30)
            mock_db.labeled_data.find.return_value = self._create_async_iterator(
                labeled_data
            )

            message = self._create_mock_message("msg1", text="Test", score=0.6)
            mock_db.messages.find_random = AsyncMock(return_value=[message])

            result = await get_message_for_labeling()

            assert isinstance(result, MessageForLabeling)
            assert not isinstance(result, list)

    @pytest.mark.asyncio
    async def test_no_messages_available_returns_none(self):
        """Test when no messages are available for labeling."""
        with patch("api.labeling.labeling.Database") as mock_db_class:
            mock_db = Mock()
            mock_db_class.return_value = mock_db

            mock_db.labeled_data.find.return_value = self._create_async_iterator([])
            # Both target class and fallback return empty
            mock_db.messages.find_random = AsyncMock(return_value=[])

            result = await get_message_for_labeling()

            assert result is None

    @pytest.mark.asyncio
    async def test_fallback_to_other_class(self):
        """Test that if target class has no messages, it falls back to other class."""
        with patch("api.labeling.labeling.Database") as mock_db_class:
            mock_db = Mock()
            mock_db_class.return_value = mock_db

            # Need more class 0 (negative): 50:50 distribution
            labeled_data = self._create_labeled_data_list(50, 50)
            mock_db.labeled_data.find.return_value = self._create_async_iterator(
                labeled_data
            )

            # First call (target class 0) returns empty, second call (class 1) returns message
            message_class_1 = self._create_mock_message(
                "msg1", text="Positive message", score=0.8
            )
            mock_db.messages.find_random = AsyncMock(
                side_effect=[[], [message_class_1]]
            )

            result = await get_message_for_labeling()

            assert result is not None
            assert result.id == "msg1"
            assert mock_db.messages.find_random.call_count == 2

    @pytest.mark.asyncio
    async def test_filters_already_labeled_messages(self):
        """Test that already labeled messages are excluded via filter."""
        with patch("api.labeling.labeling.Database") as mock_db_class:
            mock_db = Mock()
            mock_db_class.return_value = mock_db

            # Include a labeled message - it should be excluded from results
            labeled_data = self._create_labeled_data_list(70, 30)
            mock_db.labeled_data.find.return_value = self._create_async_iterator(
                labeled_data
            )

            message = self._create_mock_message(
                "msg2", text="Not labeled yet", score=0.6
            )
            mock_db.messages.find_random = AsyncMock(return_value=[message])

            result = await get_message_for_labeling()

            assert result is not None
            assert result.id == "msg2"

    @pytest.mark.asyncio
    async def test_uses_caption_when_no_text(self):
        """Test that caption is used when text is None."""
        with patch("api.labeling.labeling.Database") as mock_db_class:
            mock_db = Mock()
            mock_db_class.return_value = mock_db

            labeled_data = self._create_labeled_data_list(70, 30)
            mock_db.labeled_data.find.return_value = self._create_async_iterator(
                labeled_data
            )

            message = self._create_mock_message(
                "msg1", text=None, caption="Only caption", score=0.7
            )
            mock_db.messages.find_random = AsyncMock(return_value=[message])

            result = await get_message_for_labeling()

            assert result is not None
            assert result.text == "Only caption"

    @pytest.mark.asyncio
    async def test_empty_text_and_caption(self):
        """Test handling of messages with both text and caption as None."""
        with patch("api.labeling.labeling.Database") as mock_db_class:
            mock_db = Mock()
            mock_db_class.return_value = mock_db

            labeled_data = self._create_labeled_data_list(70, 30)
            mock_db.labeled_data.find.return_value = self._create_async_iterator(
                labeled_data
            )

            message = self._create_mock_message(
                "msg1", text=None, caption=None, score=0.7
            )
            mock_db.messages.find_random = AsyncMock(return_value=[message])

            result = await get_message_for_labeling()

            assert result is not None
            assert result.text == ""

    @pytest.mark.asyncio
    async def test_seed_parameter_passed(self):
        """Test that seed parameter is passed to find_random."""
        with patch("api.labeling.labeling.Database") as mock_db_class:
            mock_db = Mock()
            mock_db_class.return_value = mock_db

            labeled_data = self._create_labeled_data_list(70, 30)
            mock_db.labeled_data.find.return_value = self._create_async_iterator(
                labeled_data
            )

            message = self._create_mock_message("msg1", text="Test", score=0.5)
            mock_db.messages.find_random = AsyncMock(return_value=[message])

            await get_message_for_labeling(seed=42)

            call_kwargs = mock_db.messages.find_random.call_args[1]
            assert call_kwargs["seed"] == 42

    @pytest.mark.asyncio
    async def test_requests_single_message(self):
        """Test that find_random is called with size=1."""
        with patch("api.labeling.labeling.Database") as mock_db_class:
            mock_db = Mock()
            mock_db_class.return_value = mock_db

            labeled_data = self._create_labeled_data_list(70, 30)
            mock_db.labeled_data.find.return_value = self._create_async_iterator(
                labeled_data
            )

            message = self._create_mock_message("msg1", text="Test", score=0.5)
            mock_db.messages.find_random = AsyncMock(return_value=[message])

            await get_message_for_labeling()

            call_kwargs = mock_db.messages.find_random.call_args[1]
            assert call_kwargs["size"] == 1

    @pytest.mark.asyncio
    async def test_distribution_influences_class_selection(self):
        """Test that class distribution influences which class is sampled."""
        with patch("api.labeling.labeling.Database") as mock_db_class:
            mock_db = Mock()
            mock_db_class.return_value = mock_db

            # Set distribution to need more class 1 (80% class 0 > 70% target)
            labeled_data = self._create_labeled_data_list(80, 20)
            mock_db.labeled_data.find.return_value = self._create_async_iterator(
                labeled_data
            )

            # Return a class 1 message (score >= 0.5)
            message = self._create_mock_message("msg1", text="Positive", score=0.8)
            mock_db.messages.find_random = AsyncMock(return_value=[message])

            result = await get_message_for_labeling()

            assert result is not None
            assert result.label_classifier == 1
            # First call should be for class 1 (score >= 0.5)
            mock_db.messages.find_random.assert_called_once()

    @pytest.mark.asyncio
    async def test_model_output_structure(self):
        """Test that returned object matches MessageForLabeling model."""
        with patch("api.labeling.labeling.Database") as mock_db_class:
            mock_db = Mock()
            mock_db_class.return_value = mock_db

            labeled_data = self._create_labeled_data_list(70, 30)
            mock_db.labeled_data.find.return_value = self._create_async_iterator(
                labeled_data
            )

            message = self._create_mock_message("msg1", text="Test message", score=0.8)
            mock_db.messages.find_random = AsyncMock(return_value=[message])

            result = await get_message_for_labeling()

            assert result is not None
            assert isinstance(result, MessageForLabeling)
            assert hasattr(result, "id")
            assert hasattr(result, "text")
            assert hasattr(result, "label_classifier")

    @pytest.mark.asyncio
    async def test_score_boundary_values(self):
        """Test messages with boundary score values."""
        with patch("api.labeling.labeling.Database") as mock_db_class:
            mock_db = Mock()
            mock_db_class.return_value = mock_db

            labeled_data = self._create_labeled_data_list(70, 30)
            mock_db.labeled_data.find.return_value = self._create_async_iterator(
                labeled_data
            )

            # Test score = 0.5 (threshold)
            message = self._create_mock_message(
                "msg1", text="Threshold score", score=0.5
            )
            mock_db.messages.find_random = AsyncMock(return_value=[message])

            result = await get_message_for_labeling()

            assert result is not None
            assert result.label_classifier == 1  # 0.5 >= 0.5
