"""Logging configuration for the service.

Two requirements drove this off a naive logging.basicConfig():

1. basicConfig is a NO-OP if the root logger already has handlers. Under
   Gunicorn/Uvicorn workers or pytest's capture, something configures logging
   first, so the access lines silently vanish in exactly the environment that
   matters. dictConfig with an explicit logger entry is not subject to that.

2. The access middleware emits logger.info(json.dumps(record)). Through the
   default formatter that lands as `INFO:bazaar_api.access:{...}` — which is
   NOT valid per-line JSON, so a log shipper parsing JSON per line drops it.
   The access logger therefore gets a passthrough formatter that emits the
   message (already-serialised JSON) verbatim.

configure_logging() is called at import time in main.py, so importing
bazaar_api.main reconfigures process logging (including the root logger). That
is deliberate for a service: dictConfig is idempotent, and import-time means it
also runs under ASGITransport in tests. It is defined as a function (rather
than a module-level dictConfig call) so other modules import the symbol
without triggering the reconfiguration as a side effect of importing THIS
module — the call happens once, explicitly, in main.py.
"""

import logging.config


def configure_logging() -> None:
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                # Access lines are already JSON-serialised by the middleware;
                # emit them untouched so each stdout line is valid JSON.
                "json_passthrough": {"format": "%(message)s"},
                "standard": {"format": "%(levelname)s:%(name)s:%(message)s"},
            },
            "handlers": {
                "access": {
                    "class": "logging.StreamHandler",
                    "formatter": "json_passthrough",
                    # Structured access logs go to stdout, not stderr (the
                    # StreamHandler default) — otherwise they interleave with
                    # tracebacks and a shipper parsing stdout-as-JSON gets nothing.
                    "stream": "ext://sys.stdout",
                },
                "default": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                },
            },
            "loggers": {
                # Structured per-request access lines; not propagated so they
                # don't also go through the root/default formatter.
                "bazaar_api.access": {
                    "handlers": ["access"],
                    "level": "INFO",
                    "propagate": False,
                }
            },
            "root": {"handlers": ["default"], "level": "INFO"},
        }
    )
