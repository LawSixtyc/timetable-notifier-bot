import asyncio
import httpx
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    bot_token: str
    backend_base_url: str = "http://backend:8000"

settings = Settings()

bot = Bot(token=settings.bot_token)
dp = Dispatcher()

@dp.message(Command("start"))
async def start(m: Message):
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(f"{settings.backend_base_url}/users/{m.from_user.id}")
    await m.answer("✅ Hello! I will notify you about timetable changes (MVP).")

@dp.message(Command("health"))
async def health(m: Message):
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{settings.backend_base_url}/health")
    await m.answer(f"Backend health: {r.json()}")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
