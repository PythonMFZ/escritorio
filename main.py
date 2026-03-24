"""main.py

Wrapper ASGI module to make deployments resilient across platforms.

Many PaaS default to `uvicorn main:app`. This module imports the real FastAPI `app`
from the module defined by APP_MODULE (default: "app").
"""

from __future__ import annotations

import importlib
import os


def _load_app():
    module_name = os.getenv("APP_MODULE", "app")
    mod = importlib.import_module(module_name)
    try:
        return getattr(mod, "app")
    except AttributeError as exc:
        raise RuntimeError(f'Module "{module_name}" does not expose variable "app".') from exc


app = _load_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )
