from enum import Enum


class ScrapingMode(str, Enum):
    HISTORY = "history"
    LIVE = "live"
