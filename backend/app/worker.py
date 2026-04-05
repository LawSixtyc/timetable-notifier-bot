import asyncio

from .clients.ruz_client import RuzClient
from .db import SessionLocal, engine
from .models import Base
from .services.checker import run_checker_once
from .settings import settings


async def prepare_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def main():
    await prepare_db()
    ruz_client = RuzClient()

    print(f"[worker] started interval={settings.checker_interval_seconds}s", flush=True)

    while True:
        try:
            async with SessionLocal() as session:
                result = await run_checker_once(
                    session=session,
                    ruz_client=ruz_client,
                    bot_token=settings.bot_token,
                    target_date=None,
                    demo_change=False,
                )

            print(
                "[worker] cycle_done "
                f"checked_groups={result.get('checked_groups', 0)} "
                f"initialized_groups={result.get('initialized_groups', 0)} "
                f"changed_groups={result.get('changed_groups', 0)} "
                f"notifications_sent={result.get('notifications_sent', 0)}",
                flush=True,
            )
        except Exception as e:
            print(f"[worker] cycle_error error={e}", flush=True)

        await asyncio.sleep(settings.checker_interval_seconds)


if __name__ == "__main__":
    asyncio.run(main())