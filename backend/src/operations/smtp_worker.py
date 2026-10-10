"""Dramatiq entry point: dramatiq operations.smtp_worker:broker."""

from operations.email_worker import register

broker = register()
