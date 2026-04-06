from sqlalchemy import delete, func, select
import pytest

from app.db import SessionLocal, engine
from app.models import (
    Base,
    ChangeEvent,
    ScheduleSnapshot,
    Subscription,
    TrackedGroup,
    User,
)
from app.services.checker import run_checker_once


def sample_raw_schedule():
    return {
        "week": {
            "date_start": "2026.03.30",
            "date_end": "2026.04.05",
            "is_odd": True,
        },
        "group": {
            "id": 42676,
            "name": "5130904/50002",
        },
        "days": [
            {
                "weekday": 1,
                "date": "2026-03-30",
                "lessons": [
                    {
                        "subject": "Структуры данных",
                        "subject_short": "Структуры данных",
                        "time_start": "08:00",
                        "time_end": "09:40",
                        "additional_info": "5130904/50002 п/г 1",
                        "typeObj": {
                            "name": "Лабораторные",
                            "abbr": "Лаб",
                        },
                        "teachers": [
                            {"full_name": "Александрова Ольга Всеволодовна"}
                        ],
                        "auditories": [
                            {
                                "name": "103",
                                "building": {
                                    "abbr": "3 к.",
                                    "name": "3-й учебный корпус",
                                },
                            }
                        ],
                        "groups": [
                            {
                                "id": 42676,
                                "name": "5130904/50002",
                            }
                        ],
                        "webinar_url": "",
                        "lms_url": "https://dl.spbstu.ru/course/view.php?id=7752",
                    }
                ],
            }
        ],
    }


class FakeRuzClient:
    async def get_group_schedule(self, group_id: int, date: str | None = None):
        return sample_raw_schedule()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_checker_creates_baseline_and_demo_change_event(monkeypatch):
    # Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Clean test-related tables in correct order
    async with SessionLocal() as session:
        await session.execute(delete(ChangeEvent))
        await session.execute(delete(ScheduleSnapshot))
        await session.execute(delete(Subscription))
        await session.execute(delete(TrackedGroup))
        await session.execute(delete(User))
        await session.commit()

    # Create one user + one tracked group + one active subscription
    async with SessionLocal() as session:
        user = User(telegram_id=111111111)
        session.add(user)
        await session.flush()

        group = TrackedGroup(
            ruz_group_id=42676,
            name="5130904/50002",
            faculty_id=125,
            faculty_name="Институт компьютерных наук и кибербезопасности",
            study_form="Очная",
            degree="Бакалавр",
            level=1,
            kind=0,
            year=2025,
        )
        session.add(group)
        await session.flush()

        subscription = Subscription(
            user_id=user.id,
            tracked_group_id=group.id,
            is_active=True,
        )
        session.add(subscription)
        await session.commit()

    # Capture "sent notifications" instead of calling real Telegram
    sent_messages = []

    async def fake_send_telegram_message(bot_token: str, chat_id: int, text: str):
        sent_messages.append(
            {
                "bot_token": bot_token,
                "chat_id": chat_id,
                "text": text,
            }
        )

    monkeypatch.setattr(
        "app.services.checker.send_telegram_message",
        fake_send_telegram_message,
    )

    fake_ruz_client = FakeRuzClient()

    # First run: baseline snapshot should be created
    async with SessionLocal() as session:
        result_1 = await run_checker_once(
            session=session,
            ruz_client=fake_ruz_client,
            bot_token="fake-token",
            target_date="2026-03-30",
            demo_change=False,
        )

    # Second run with demo change: should create change event + notification
    async with SessionLocal() as session:
        result_2 = await run_checker_once(
            session=session,
            ruz_client=fake_ruz_client,
            bot_token="fake-token",
            target_date="2026-03-30",
            demo_change=True,
        )

    # Check results returned by checker
    assert result_1["initialized_groups"] == 1
    assert result_1["changed_groups"] == 0

    assert result_2["initialized_groups"] == 0
    assert result_2["changed_groups"] == 1
    assert result_2["notifications_sent"] == 1

    # Check DB state
    async with SessionLocal() as session:
        snapshot_count = (
            await session.execute(select(func.count(ScheduleSnapshot.id)))
        ).scalar_one()

        event_count = (
            await session.execute(select(func.count(ChangeEvent.id)))
        ).scalar_one()

    assert snapshot_count >= 2
    assert event_count == 1

    # Check that one notification was "sent"
    assert len(sent_messages) == 1
    assert sent_messages[0]["chat_id"] == 111111111
    assert "Изменения в расписании" in sent_messages[0]["text"] or "DEMO" in sent_messages[0]["text"]