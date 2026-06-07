"""Programmatic uvicorn entry point.

Lets you boot the backend with the settings-resolved host / port without
having to remember the `--port` flag:

    python -m pa_guard.api

reads `PAG_API_HOST` / `PAG_API_PORT` from the environment via
`Settings`, and falls back to the v1.0.4 defaults (`127.0.0.1:8088`) when
nothing is set.

The Dockerfile and docker-compose still pass `--port 8088` explicitly so
the container doesn't rely on this entry point — but anything that runs
the package directly (CI, ops shells, an IDE run-config) inherits the
configured port for free.
"""
from __future__ import annotations

import uvicorn

from ..core.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "pa_guard.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
