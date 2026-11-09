"""Request-local public events. Never emit planning prompts or reasoning."""
from contextvars import ContextVar

sink = ContextVar('agent_public_event_sink', default=None)


def emit(event_type, payload):
    callback = sink.get()
    if callback is not None:
        callback(event_type, payload)
