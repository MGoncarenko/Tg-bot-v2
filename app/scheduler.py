"""Планувальник фонових задач (APScheduler, async, таймзона Київ)."""
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from . import settings
from .services.reports import ReportService


def setup_scheduler(reports: ReportService) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=ZoneInfo(settings.TIMEZONE))
    # розсилка підписок — щохвилини (перевіряє, кому настав час)
    scheduler.add_job(reports.send_subscriptions, CronTrigger(minute="*"))
    # очистка таблиці ТТН — щодня о 00:00 за Києвом
    scheduler.add_job(reports.clear_ttn, CronTrigger(hour=0, minute=0))
    # переконект до Google Sheets + оновлення кешів — щогодини
    scheduler.add_job(reports.reconnect, CronTrigger(minute=0))
    return scheduler
