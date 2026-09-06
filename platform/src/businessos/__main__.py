"""Development server entry point using Uvicorn as the ASGI server."""

import uvicorn

from businessos.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "businessos.asgi:application",
        host=settings.host,
        port=settings.port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
