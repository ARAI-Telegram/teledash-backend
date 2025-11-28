"""High-level services orchestrating scraping operations.

This package contains service classes that coordinate managers to implement
complete business workflows:

- ScrapingService: Orchestrates client preparation, chat preparation, and
  index management for scraping tasks
- ChatService: Coordinates chat information updates and recommendations
- AttachmentService: Orchestrates attachment downloads and file management

Services coordinate multiple managers and implement the main scraping logic
used by Celery tasks.
"""
