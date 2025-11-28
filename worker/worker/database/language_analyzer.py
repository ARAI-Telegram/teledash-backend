from enum import Enum


class LanguageAnalyzer(Enum):
    """
    Enum to represent supported languages and their corresponding analyzers for text processing.

    Each language is mapped to a tuple containing:
    - lang_codes: A list of ISO 639-1 language codes (e.g., ['he', 'iw'] for Hebrew).
    - analyzer: The name of the language-specific analyzer to be used for text processing (e.g., 'hebrew').

    Note: Not all languages are supported by Elasticsearch by default.
    To enable support for additional languages, the corresponding plugins must be installed
    in the Elasticsearch container. For example, for Hebrew:

    1. In Dockerfile.elasticsearch, add:
       RUN bin/elasticsearch-plugin install analysis-hebrew

    2. Rebuild the Elasticsearch container:
       docker-compose build elasticsearch

    3. Restart the container:
       docker-compose up -d elasticsearch

    Available language plugins include:
    - analysis-hebrew (Hebrew)
    - analysis-ukrainian (Ukrainian)

    4. Add it here in the list accordingly.
    """

    ARABIC = (["ar"], "arabic")
    ENGLISH = (["en"], "english")
    FRENCH = (["fr"], "french")
    GERMAN = (["de"], "german")
    ITALIAN = (["it"], "italian")
    RUSSIAN = (["ru"], "russian")
    SPANISH = (["es"], "spanish")
    TURKISH = (["tr"], "turkish")
    UKRAINIAN = (
        ["uk"],
        "russian",
    )  # Using Russian analyzer due to linguistic similarity for Ukrainian as a placeholder if not extra plugin is installed

    def __init__(self, lang_codes: list, analyzer: str) -> None:
        """Initialize LanguageAnalyzer with language codes and analyzer name.

        Args:
            lang_codes: List of language codes (e.g., ['en', 'eng']).
            analyzer: Name of the Elasticsearch analyzer.
        """
        self.lang_codes = lang_codes
        self.analyzer = analyzer

    @staticmethod
    def from_lang_code(lang_code: str) -> str:
        """
        Returns the corresponding analyzer for the given language code.
        Returns:
            str: The name of the language-specific analyzer, or "standard" if not found.
        """
        for lang in LanguageAnalyzer:
            if lang_code in lang.lang_codes:
                return lang.analyzer
        return "standard"  # Default analyzer if no match is found
