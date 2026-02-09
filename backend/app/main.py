from fastapi import FastAPI
from sqlalchemy import select
from .db import engine, SessionLocal
from .models import Base, User

app = FastAPI(title="Timetable Notifier API")

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
        existing = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()
        if existing:
            return {"id": existing.id, "telegram_id": existing.telegram_id}

        u = User(telegram_id=telegram_id)
        session.add(u)
        await session.commit()
        await session.refresh(u)
        return {"id": u.id, "telegram_id": u.telegram_id}
