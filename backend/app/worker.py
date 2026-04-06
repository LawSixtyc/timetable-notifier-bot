import asyncio
from datetime import date, timedelta

from .clients.ruz_client import RuzClient
from .db import SessionLocal, engine
from .models import Base
from .services.checker import run_checker_once
from .settings import settings


def start_of_week(d: date) -> date:
    return d - timedelta(days=d.weekday())


async def prepare_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def run_cycle(ruz_client: RuzClient):
    today = date.today()
    current_target = today
    next_week_target = start_of_week(today) + timedelta(days=7)

    print(
        f"[worker] cycle_start current_target={current_target.isoformat()} "
        f"next_week_target={next_week_target.isoformat()}",
        flush=True,
    )

    async with SessionLocal() as session:
        current_result = await run_checker_once(
            session=session,
            ruz_client=ruz_client,
            bot_token=settings.bot_token,
            target_date=current_target.isoformat(),
            demo_change=False,
        )

    async with SessionLocal() as session:
        next_result = await run_checker_once(
            session=session,
            ruz_client=ruz_client,
            bot_token=settings.bot_token,
            target_date=next_week_target.isoformat(),
            demo_change=False,
        )

    print(
        "[worker] cycle_done "
        f"current_checked={current_result.get('checked_groups', 0)} "
        f"current_initialized={current_result.get('initialized_groups', 0)} "
        f"current_changed={current_result.get('changed_groups', 0)} "
        f"next_checked={next_result.get('checked_groups', 0)} "
        f"next_initialized={next_result.get('initialized_groups', 0)} "
        f"next_changed={next_result.get('changed_groups', 0)} "
        f"notifications_total={current_result.get('notifications_sent', 0) + next_result.get('notifications_sent', 0)}",
        flush=True,
    )


async def main():
    await prepare_db()
    ruz_client = RuzClient()

    print(f"[worker] started interval={settings.checker_interval_seconds}s", flush=True)

    while True:
        try:
            await run_cycle(ruz_client)
        except Exception as e:
            print(f"[worker] cycle_error error={e}", flush=True)

        await asyncio.sleep(settings.checker_interval_seconds)


if __name__ == "__main__":
    asyncio.run(main())