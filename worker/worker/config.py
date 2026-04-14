from datetime import timedelta

from celery.schedules import crontab

from common.settings import settings

broker_url = "redis://redis:6379/0"
result_backend = "redis://redis:6379/0"
imports = ["worker.tasks"]

# Set the expiration time for task results to 3 days (259200 seconds)
result_expires = 259200

# careful: maps task names set in @task decorator
task_routes = {
    # History related tasks - concurrency > 1 only useful with multiple clients
    "scraping.init_scrapers": {"queue": "history"},
    "scraping.scrape_chats_history": {"queue": "history"},
    # Chat updates - parallelizable, but not necessary
    "scraping.update_chats": {"queue": "chat-updates"},
    "scraping.scrape_chat_members": {"queue": "chat-updates"},
    # Live message handling
    "live.*": {"queue": "live"},  # concurrency must be >= number of clients
    "live_processing.*": {"queue": "live-msg-process"},
    # Files
    "files_purge.*": {"queue": "files-purge"},
    "files_process.*": {"queue": "files-process"},
}

# Send task-related events so that tasks can be monitored using tools like flower.
worker_send_task_events = True

# scheduled tasks
beat_schedule = {
    "scrape-chats": {
        "task": "scraping.init_scrapers",
        "schedule": timedelta(minutes=settings.scrape_chats_interval_minutes),
        "options": {"expires": settings.scrape_chats_interval_minutes * 60},
    },
    "update-chats": {
        "task": "scraping.update_chats",
        "schedule": timedelta(minutes=60),
    },
}

if settings.keep_attachment_files_days > 0:
    beat_schedule["purge-attachment-files"] = {
        "task": "files_purge.purge_message_attachments",
        "schedule": crontab(hour=4, minute=0),  # execute daily
    }

if settings.scrape_users:
    beat_schedule["scrape-chat-members"] = {
        "task": "scraping.scrape_chat_members",
        "schedule": crontab(hour=3, minute=0),  # execute daily
    }
