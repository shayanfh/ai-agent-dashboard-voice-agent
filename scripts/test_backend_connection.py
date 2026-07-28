import asyncio

from app.backend.client import DashboardBackendClient
from app.core.config import get_settings


async def main() -> None:
    async with DashboardBackendClient(get_settings()) as backend:
        if not await backend.health():
            raise SystemExit("Dashboard Backend health check failed")
    print("Dashboard Backend is reachable")


if __name__ == "__main__":
    asyncio.run(main())

