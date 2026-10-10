"""Dramatiq broker entry point for webhook delivery actors."""

import atexit

from operations.platform.config import Settings
from operations.platform.logging import configure_logging
from operations.webhook_worker import register

configure_logging()
settings = Settings()  # type: ignore[call-arg]
broker = register(settings)
atexit.register(broker.close)
atexit.register(broker.client.close)
