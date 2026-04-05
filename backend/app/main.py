from typing import Optional, Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func

from .db import engine, SessionLocal
from .models import Base, User, TrackedGroup, Subscription
from .clients.ruz_client import RuzClient
from .services.checker import run_checker_once
from .settings import settings

app = FastAPI(title="Timetable Notifier API")
ruz_client = RuzClient()

STUDY_FORM_MAP = {
    "common": "Очная",
    "distance": "Заочная",
    "evening": "Очно-заочная",
}

DEGREE_MAP = {
    0: "Бакалавр",
    1: "Магистр",
    2: "Специалист",
}
MAX_SUBSCRIPTIONS_PER_USER = 2


class SubscriptionCreate(BaseModel):
    telegram_id: int
    group: dict[str, Any]
    faculty_name: Optional[str] = None


def enrich_group(group: dict) -> dict:
    item = dict(group)
    raw_type = item.get("type")
    raw_kind = item.get("kind")

    item["study_form"] = STUDY_FORM_MAP.get(raw_type, raw_type)
    item["degree"] = DEGREE_MAP.get(raw_kind, f"kind_{raw_kind}")

    return item


def tracked_group_to_dict(group: TrackedGroup) -> dict:
    return {
        "id": group.ruz_group_id,
        "ruz_group_id": group.ruz_group_id,
        "name": group.name,
        "faculty": {
            "id": group.faculty_id,
            "name": group.faculty_name,
        },
        "faculty_id": group.faculty_id,
        "faculty_name": group.faculty_name,
        "study_form": group.study_form,
        "degree": group.degree,
        "level": group.level,
        "kind": group.kind,
        "year": group.year,
    }


async def ensure_user(session, telegram_id: int) -> User:
    existing = (
        await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
    ).scalar_one_or_none()

    if existing:
        return existing

    user = User(telegram_id=telegram_id)
    session.add(user)
    await session.flush()
    return user


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/users/{telegram_id}")
async def upsert_user(telegram_id: int):
    async with SessionLocal() as session:
        user = await ensure_user(session, telegram_id)
        await session.commit()
        await session.refresh(user)
        return {"id": user.id, "telegram_id": user.telegram_id}


@app.get("/faculties")
async def get_faculties():
    try:
        faculties = await ruz_client.get_faculties()
        return {"faculties": faculties}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"RUZ API error: {str(e)}")


@app.get("/faculties/{faculty_id}/groups")
async def get_groups_by_faculty(faculty_id: int):
    try:
        groups = await ruz_client.get_groups_by_faculty(faculty_id)
        enriched = [enrich_group(group) for group in groups]
        enriched.sort(key=lambda g: (g.get("level", 999), g.get("name", "")))
        return {"groups": enriched}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"RUZ API error: {str(e)}")


@app.get("/faculties/{faculty_id}/groups/filtered")
async def get_filtered_groups(
    faculty_id: int,
    study_form: Optional[str] = None,
    degree: Optional[str] = None,
    level: Optional[int] = None,
    q: Optional[str] = None,
):
    try:
        groups = await ruz_client.get_groups_by_faculty(faculty_id)
        enriched = [enrich_group(group) for group in groups]

        if study_form:
            sf = study_form.strip().lower()
            enriched = [
                g for g in enriched
                if str(g.get("type", "")).lower() == sf
                or str(g.get("study_form", "")).lower() == sf
            ]

        if degree:
            deg = degree.strip().lower()
            enriched = [
                g for g in enriched
                if str(g.get("degree", "")).lower() == deg
            ]

        if level is not None:
            enriched = [
                g for g in enriched
                if g.get("level") == level
            ]

        if q:
            needle = q.strip().lower()
            enriched = [
                g for g in enriched
                if needle in str(g.get("name", "")).lower()
            ]

        enriched.sort(key=lambda g: (g.get("level", 999), g.get("name", "")))
        return {"count": len(enriched), "groups": enriched}

    except Exception as e:
        raise HTTPException(status_code=502, detail=f"RUZ API error: {str(e)}")


@app.get("/groups/search")
async def search_groups(q: str):
    try:
        query = q.strip()
        if not query:
            return {"groups": []}

        groups = await ruz_client.search_groups(query)
        enriched = [enrich_group(group) for group in groups]
        enriched.sort(key=lambda g: (g.get("level", 999), g.get("name", "")))
        return {"groups": enriched}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"RUZ API error: {str(e)}")


@app.get("/groups/{group_id}/schedule")
async def get_group_schedule(group_id: int, date: Optional[str] = None):
    try:
        schedule = await ruz_client.get_group_schedule(group_id, date=date)
        return schedule
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"RUZ API error: {str(e)}")


@app.post("/subscriptions")
async def create_subscription(payload: SubscriptionCreate):
    async with SessionLocal() as session:
        try:
            user = await ensure_user(session, payload.telegram_id)

            group_data = payload.group or {}
            ruz_group_id = group_data.get("id")
            group_name = group_data.get("name")

            if not ruz_group_id or not group_name:
                raise HTTPException(status_code=400, detail="group.id and group.name are required")

            faculty = group_data.get("faculty") or {}
            faculty_id = faculty.get("id") or group_data.get("faculty_id")
            faculty_name = faculty.get("name") or group_data.get("faculty_name") or payload.faculty_name

            tracked_group = (
                await session.execute(
                    select(TrackedGroup).where(TrackedGroup.ruz_group_id == ruz_group_id)
                )
            ).scalar_one_or_none()

            if not tracked_group:
                tracked_group = TrackedGroup(
                    ruz_group_id=ruz_group_id,
                    name=group_name,
                    faculty_id=faculty_id,
                    faculty_name=faculty_name,
                    study_form=group_data.get("study_form"),
                    degree=group_data.get("degree"),
                    level=group_data.get("level"),
                    kind=group_data.get("kind"),
                    year=group_data.get("year"),
                )
                session.add(tracked_group)
                await session.flush()
            else:
                tracked_group.name = group_name
                tracked_group.faculty_id = faculty_id
                tracked_group.faculty_name = faculty_name
                tracked_group.study_form = group_data.get("study_form")
                tracked_group.degree = group_data.get("degree")
                tracked_group.level = group_data.get("level")
                tracked_group.kind = group_data.get("kind")
                tracked_group.year = group_data.get("year")

            existing_subscription = (
                await session.execute(
                    select(Subscription).where(
                        Subscription.user_id == user.id,
                        Subscription.tracked_group_id == tracked_group.id,
                    )
                )
            ).scalar_one_or_none()

            active_count = (
                await session.execute(
                    select(func.count(Subscription.id)).where(
                        Subscription.user_id == user.id,
                        Subscription.is_active.is_(True),
                    )
                )
            ).scalar_one()

            if existing_subscription is None and active_count >= MAX_SUBSCRIPTIONS_PER_USER:
                raise HTTPException(
                    status_code=400,
                    detail=f"У вас уже максимальное число подписок: {MAX_SUBSCRIPTIONS_PER_USER}",
                )

            if (
                existing_subscription is not None
                and not existing_subscription.is_active
                and active_count >= MAX_SUBSCRIPTIONS_PER_USER
            ):
                raise HTTPException(
                    status_code=400,
                    detail=f"У вас уже максимальное число подписок: {MAX_SUBSCRIPTIONS_PER_USER}",
                )

            created = False

            if existing_subscription:
                existing_subscription.is_active = True
                subscription = existing_subscription
            else:
                subscription = Subscription(
                    user_id=user.id,
                    tracked_group_id=tracked_group.id,
                    is_active=True,
                )
                session.add(subscription)
                await session.flush()
                created = True

            await session.commit()
            await session.refresh(subscription)

            return {
                "subscription_id": subscription.id,
                "created": created,
                "group": tracked_group_to_dict(tracked_group),
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@app.get("/users/{telegram_id}/subscriptions")
async def get_user_subscriptions(telegram_id: int):
    async with SessionLocal() as session:
        try:
            user = (
                await session.execute(
                    select(User).where(User.telegram_id == telegram_id)
                )
            ).scalar_one_or_none()

            if not user:
                return {"subscriptions": []}

            rows = await session.execute(
                select(Subscription, TrackedGroup)
                .join(TrackedGroup, Subscription.tracked_group_id == TrackedGroup.id)
                .where(
                    Subscription.user_id == user.id,
                    Subscription.is_active.is_(True),
                )
                .order_by(TrackedGroup.name)
            )

            items = []
            for subscription, tracked_group in rows.all():
                items.append(
                    {
                        "subscription_id": subscription.id,
                        "group": tracked_group_to_dict(tracked_group),
                    }
                )

            return {"subscriptions": items}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@app.delete("/users/{telegram_id}/subscriptions/by-group/{ruz_group_id}")
async def remove_subscription_by_group(telegram_id: int, ruz_group_id: int):
    async with SessionLocal() as session:
        try:
            user = (
                await session.execute(
                    select(User).where(User.telegram_id == telegram_id)
                )
            ).scalar_one_or_none()

            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            row = await session.execute(
                select(Subscription, TrackedGroup)
                .join(TrackedGroup, Subscription.tracked_group_id == TrackedGroup.id)
                .where(
                    Subscription.user_id == user.id,
                    Subscription.is_active.is_(True),
                    TrackedGroup.ruz_group_id == ruz_group_id,
                )
            )

            result = row.first()
            if not result:
                raise HTTPException(status_code=404, detail="Active subscription not found")

            subscription, _tracked_group = result
            subscription.is_active = False

            await session.commit()

            return {"ok": True}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@app.delete("/subscriptions/{subscription_id}")
async def remove_subscription(subscription_id: int):
    async with SessionLocal() as session:
        try:
            subscription = (
                await session.execute(
                    select(Subscription).where(Subscription.id == subscription_id)
                )
            ).scalar_one_or_none()

            if not subscription:
                raise HTTPException(status_code=404, detail="Subscription not found")

            subscription.is_active = False
            await session.commit()

            return {"ok": True}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@app.post("/checker/run-once")
async def checker_run_once(
    demo_change: bool = False,
    target_date: Optional[str] = None,
):
    async with SessionLocal() as session:
        try:
            result = await run_checker_once(
                session=session,
                ruz_client=ruz_client,
                bot_token=settings.bot_token,
                target_date=target_date,
                demo_change=demo_change,
            )
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))