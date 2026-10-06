"""Dramatiq entry point: dramatiq operations.automation_worker:broker."""

import atexit

from operations.platform.config import Settings
from operations.worker import register_actor

runtime = register_actor(Settings())  # type: ignore[call-arg]
consume_delivery = runtime.actor
broker = runtime.broker
atexit.register(runtime.close)
