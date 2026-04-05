import asyncio
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    bot_token: str
    backend_base_url: str = "http://backend:8000"


settings = Settings()

bot = Bot(token=settings.bot_token)
dp = Dispatcher()

USER_STATE: dict[int, dict[str, Any]] = {}

STUDY_FORM_LABELS = {
    "common": "Очная",
    "distance": "Заочная",
    "evening": "Очно-заочная",
}

DEGREE_LABELS = {
    0: "Бакалавр",
    1: "Магистр",
    2: "Специалист",
}

DAY_NAMES = {
    1: "Понедельник",
    2: "Вторник",
    3: "Среда",
    4: "Четверг",
    5: "Пятница",
    6: "Суббота",
    7: "Воскресенье",
}


def get_state(user_id: int) -> dict[str, Any]:
    if user_id not in USER_STATE:
        USER_STATE[user_id] = {
            "stage": None,
            "faculties": {},
            "faculty_id": None,
            "faculty_name": None,
            "study_form_raw": None,
            "study_form_label": None,
            "degree_code": None,
            "degree_label": None,
            "group_candidates": {},
            "selected_group": None,
            "anchor_date": None,
        }
    return USER_STATE[user_id]


async def backend_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{settings.backend_base_url}{path}"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()


async def backend_post(path: str) -> dict[str, Any]:
    url = f"{settings.backend_base_url}{path}"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url)
        response.raise_for_status()
        return response.json()


async def backend_post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{settings.backend_base_url}{path}"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


async def backend_delete(path: str) -> dict[str, Any]:
    url = f"{settings.backend_base_url}{path}"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.delete(url)
        response.raise_for_status()
        return response.json()


async def fetch_subscriptions(user_id: int) -> list[dict[str, Any]]:
    data = await backend_get(f"/users/{user_id}/subscriptions")
    return data.get("subscriptions", [])


async def is_group_subscribed(user_id: int, ruz_group_id: int) -> bool:
    subscriptions = await fetch_subscriptions(user_id)
    return any((item.get("group") or {}).get("id") == ruz_group_id for item in subscriptions)


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Выбрать группу")],
            [KeyboardButton(text="Моё расписание"), KeyboardButton(text="Помощь")],
            [KeyboardButton(text="Мои подписки")],
        ],
        resize_keyboard=True,
    )


def faculties_keyboard(faculties: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows = []
    faculties_sorted = sorted(faculties, key=lambda x: x.get("name", ""))
    for faculty in faculties_sorted:
        text = f'{faculty.get("abbr", "")} — {faculty.get("name", "")}'
        rows.append(
            [InlineKeyboardButton(text=text, callback_data=f'faculty:{faculty["id"]}')]
        )
    rows.append([InlineKeyboardButton(text="В главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def study_form_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Очная", callback_data="study_form:common"),
                InlineKeyboardButton(text="Очно-заочная", callback_data="study_form:evening"),
            ],
            [
                InlineKeyboardButton(text="Заочная", callback_data="study_form:distance"),
            ],
            [
                InlineKeyboardButton(text="В главное меню", callback_data="menu:main"),
            ],
        ]
    )


def degree_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Бакалавр", callback_data="degree:0"),
                InlineKeyboardButton(text="Магистр", callback_data="degree:1"),
            ],
            [
                InlineKeyboardButton(text="Специалист", callback_data="degree:2"),
            ],
            [
                InlineKeyboardButton(text="В главное меню", callback_data="menu:main"),
            ],
        ]
    )


def groups_keyboard(groups: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows = []
    for group in groups[:10]:
        text = group.get("name", "")
        rows.append(
            [InlineKeyboardButton(text=text, callback_data=f'group:{group["id"]}')]
        )

    rows.append([InlineKeyboardButton(text="Искать заново", callback_data="group:retry")])
    rows.append([InlineKeyboardButton(text="В главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def schedule_keyboard(subscribed: bool) -> InlineKeyboardMarkup:
    sub_text = "❌ Убрать из подписок" if subscribed else "🔔 Отслеживать изменения"
    sub_cb = "sub:remove" if subscribed else "sub:add"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Эта неделя", callback_data="schedule:current"),
                InlineKeyboardButton(text="◀ Предыдущая", callback_data="schedule:prev"),
                InlineKeyboardButton(text="Следующая ▶", callback_data="schedule:next"),
            ],
            [
                InlineKeyboardButton(text=sub_text, callback_data=sub_cb),
            ],
            [
                InlineKeyboardButton(text="📚 Мои подписки", callback_data="subs:list"),
            ],
            [
                InlineKeyboardButton(text="Выбрать другую группу", callback_data="group:retry"),
            ],
            [
                InlineKeyboardButton(text="В главное меню", callback_data="menu:main"),
            ],
        ]
    )


def subscriptions_keyboard(items: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows = []
    for item in items:
        sub_id = item["subscription_id"]
        group = item["group"]
        group_id = group["id"]
        group_name = group["name"]

        rows.append(
            [
                InlineKeyboardButton(text=group_name, callback_data=f"subs:open:{group_id}"),
                InlineKeyboardButton(text="❌", callback_data=f"subs:del:{sub_id}"),
            ]
        )

    rows.append([InlineKeyboardButton(text="В главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def parse_week_start(week: dict[str, Any]) -> date | None:
    raw = week.get("date_start")
    if not raw:
        return None
    return datetime.strptime(raw, "%Y.%m.%d").date()


def format_date_ru(date_str: str) -> str:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%d.%m.%Y")
    except Exception:
        return date_str


def format_teacher_names(teachers: Any) -> str:
    if not teachers:
        return "—"
    names = [t.get("full_name", "").strip() for t in teachers if t.get("full_name")]
    return ", ".join(names) if names else "—"


def format_auditories(auditories: Any) -> str:
    if not auditories:
        return "—"

    parts = []
    for aud in auditories:
        room = aud.get("name", "")
        building = (aud.get("building") or {}).get("abbr") or (aud.get("building") or {}).get("name", "")
        if building and room:
            if room.lower() == "дистанционно":
                parts.append(f"{building}, {room}")
            else:
                parts.append(f"{building}, ауд. {room}")
        elif room:
            parts.append(room)
        elif building:
            parts.append(building)

    return "; ".join(parts) if parts else "—"


def format_lesson(lesson: dict[str, Any]) -> str:
    subject = lesson.get("subject", "Без названия")
    lesson_type = (lesson.get("typeObj") or {}).get("abbr", "")
    start = lesson.get("time_start", "")
    end = lesson.get("time_end", "")
    teacher = format_teacher_names(lesson.get("teachers"))
    room = format_auditories(lesson.get("auditories"))
    info = (lesson.get("additional_info") or "").strip()

    text = f"{start}-{end} — {subject}"
    if lesson_type:
        text += f"\nВид: {lesson_type}"
    if info:
        text += f"\nИнфо: {info}"
    text += f"\nПреподаватель: {teacher}"
    text += f"\nАудитория: {room}"

    return text


def format_day(day: dict[str, Any]) -> str:
    weekday = DAY_NAMES.get(day.get("weekday"), f'День {day.get("weekday")}')
    date_ru = format_date_ru(day.get("date", ""))
    lessons = day.get("lessons") or []

    if not lessons:
        return f"{weekday}, {date_ru}\nПар нет."

    blocks = [f"{weekday}, {date_ru}"]
    for idx, lesson in enumerate(lessons, start=1):
        blocks.append(f"{idx}. {format_lesson(lesson)}")

    return "\n\n".join(blocks)

def format_checker_summary(data: dict[str, Any]) -> str:
    title = "🧪 DEMO-проверка завершена" if data.get("demo_change") else "✅ Проверка завершена"

    lines = [
        title,
        f"Проверено групп: {data.get('checked_groups', 0)}",
        f"Инициализировано: {data.get('initialized_groups', 0)}",
        f"Изменений найдено: {data.get('changed_groups', 0)}",
        f"Уведомлений отправлено: {data.get('notifications_sent', 0)}",
    ]

    results = data.get("results", [])[:10]
    status_map = {
        "initialized": "baseline saved",
        "no_change": "без изменений",
        "changed": "изменение найдено",
        "error": "ошибка",
    }

    if results:
        lines.append("")
        lines.append("Детали:")
        for item in results:
            status_text = status_map.get(item.get("status"), item.get("status"))
            lines.append(f"- {item.get('group')}: {status_text}")

    return "\n".join(lines)

async def show_faculty_selection(message: Message):
    state = get_state(message.from_user.id)
    state["stage"] = "faculty"

    try:
        data = await backend_get("/faculties")
        faculties = data.get("faculties", [])
        state["faculties"] = {str(f["id"]): f for f in faculties}

        await message.answer(
            "Выбери институт:",
            reply_markup=faculties_keyboard(faculties),
        )
    except Exception as e:
        await message.answer(f"Не удалось загрузить институты.\nОшибка: {e}")


async def show_subscriptions(chat_id: int, user_id: int):
    try:
        items = await fetch_subscriptions(user_id)
    except Exception as e:
        await bot.send_message(chat_id, f"Не удалось загрузить подписки.\nОшибка: {e}")
        return

    if not items:
        await bot.send_message(chat_id, "Подписок пока нет.")
        return

    lines = ["Твои подписки:"]
    for item in items:
        group = item["group"]
        lines.append(
            f"- {group['name']} | {group.get('study_form', '—')} | {group.get('degree', '—')}"
        )

    await bot.send_message(
        chat_id,
        "\n".join(lines),
        reply_markup=subscriptions_keyboard(items),
    )


async def show_schedule(chat_id: int, user_id: int, target_date: date):
    state = get_state(user_id)
    group = state.get("selected_group")

    if not group:
        await bot.send_message(chat_id, "Сначала выбери группу.")
        return

    group_id = group["id"]

    try:
        data = await backend_get(
            f"/groups/{group_id}/schedule",
            params={"date": target_date.isoformat()},
        )
    except Exception as e:
        await bot.send_message(chat_id, f"Не удалось загрузить расписание.\nОшибка: {e}")
        return

    week = data.get("week", {})
    days = data.get("days", [])
    group_info = data.get("group") or group

    week_start = week.get("date_start", "")
    week_end = week.get("date_end", "")
    odd_text = "нечётная" if week.get("is_odd") else "чётная"

    parsed_start = parse_week_start(week)
    if parsed_start:
        state["anchor_date"] = parsed_start.isoformat()

    faculty_name = ((group_info.get("faculty") or {}).get("name")) or state.get("faculty_name") or "—"
    study_form = group.get("study_form") or state.get("study_form_label") or "—"
    degree = group.get("degree") or state.get("degree_label") or "—"

    subscribed = await is_group_subscribed(user_id, group_id)

    header = (
        f"Группа: {group_info.get('name', '—')}\n"
        f"Институт: {faculty_name}\n"
        f"Форма: {study_form}\n"
        f"Ступень: {degree}\n"
        f"Неделя: {week_start} — {week_end} ({odd_text})"
    )

    await bot.send_message(chat_id, header, reply_markup=schedule_keyboard(subscribed))

    if not days:
        await bot.send_message(chat_id, "На эту неделю занятий не найдено.")
        return

    for day in days:
        await bot.send_message(chat_id, format_day(day))


@dp.message(CommandStart())
async def start_handler(message: Message):
    try:
        await backend_post(f"/users/{message.from_user.id}")
    except Exception:
        pass

    get_state(message.from_user.id)
    await message.answer(
        "Привет. Я помогу выбрать группу и показать расписание.",
        reply_markup=main_menu_keyboard(),
    )


@dp.message(Command("health"))
async def health_handler(message: Message):
    try:
        data = await backend_get("/health")
        await message.answer(f"Backend health: {data}")
    except Exception as e:
        await message.answer(f"Backend error: {e}")


@dp.message(Command("check_once"))
async def check_once_handler(message: Message):
    try:
        data = await backend_post("/checker/run-once")
        await message.answer(format_checker_summary(data))
    except httpx.HTTPStatusError as e:
        detail = "Не удалось запустить проверку."
        try:
            payload = e.response.json()
            if isinstance(payload, dict) and payload.get("detail"):
                detail = payload["detail"]
        except Exception:
            pass
        await message.answer(detail)
    except Exception as e:
        await message.answer(f"Не удалось запустить проверку.\nОшибка: {e}")


@dp.message(Command("check_demo"))
async def check_demo_handler(message: Message):
    try:
        data = await backend_post("/checker/run-once?demo_change=true")
        await message.answer(format_checker_summary(data))
    except httpx.HTTPStatusError as e:
        detail = "Не удалось запустить DEMO-проверку."
        try:
            payload = e.response.json()
            if isinstance(payload, dict) and payload.get("detail"):
                detail = payload["detail"]
        except Exception:
            pass
        await message.answer(detail)
    except Exception as e:
        await message.answer(f"Не удалось запустить DEMO-проверку.\nОшибка: {e}")


@dp.message(F.text == "Выбрать группу")
async def choose_group_menu(message: Message):
    await show_faculty_selection(message)


@dp.message(F.text == "Моё расписание")
async def my_schedule(message: Message):
    state = get_state(message.from_user.id)
    if not state.get("selected_group"):
        subscriptions = await fetch_subscriptions(message.from_user.id)
        if subscriptions:
            await show_subscriptions(message.chat.id, message.from_user.id)
            return

        await message.answer("Сначала выбери группу через кнопку «Выбрать группу».")
        return

    base_date = state.get("anchor_date")
    if base_date:
        target = date.fromisoformat(base_date)
    else:
        target = date.today()

    await show_schedule(message.chat.id, message.from_user.id, target)


@dp.message(F.text == "Мои подписки")
async def subscriptions_handler(message: Message):
    await show_subscriptions(message.chat.id, message.from_user.id)


@dp.message(F.text == "Помощь")
async def help_handler(message: Message):
    await message.answer(
        "Как пользоваться ботом:\n"
        "1) Нажми «Выбрать группу»\n"
        "2) Выбери институт\n"
        "3) Выбери форму обучения\n"
        "4) Выбери ступень\n"
        "5) Введи номер группы, например: 5130904/50002\n"
        "6) Нажми на найденную группу\n"
        "7) Смотри расписание на неделю\n"
        "8) Если хочешь сохранить группу — нажми «Отслеживать изменения»\n"
    )

'''
old messages 
"8) Если хочешь сохранить группу — нажми «Отслеживать изменения»\n\n"
        "Команды для демонстрации проверки:\n"
        "/check_once — реальная однократная проверка\n"
        "/check_demo — DEMO-изменение и уведомление"
'''

@dp.callback_query(F.data == "menu:main")
async def menu_main(callback: CallbackQuery):
    state = get_state(callback.from_user.id)
    state["stage"] = None
    await callback.answer()
    await callback.message.answer("Главное меню.", reply_markup=main_menu_keyboard())


@dp.callback_query(F.data.startswith("faculty:"))
async def faculty_selected(callback: CallbackQuery):
    state = get_state(callback.from_user.id)
    faculty_id = callback.data.split(":", 1)[1]
    faculty = state.get("faculties", {}).get(faculty_id)

    state["faculty_id"] = int(faculty_id)
    state["faculty_name"] = faculty.get("name") if faculty else None
    state["stage"] = "study_form"

    await callback.answer()
    await callback.message.answer(
        f"Выбран институт:\n{state['faculty_name']}\n\nТеперь выбери форму обучения:",
        reply_markup=study_form_keyboard(),
    )


@dp.callback_query(F.data.startswith("study_form:"))
async def study_form_selected(callback: CallbackQuery):
    state = get_state(callback.from_user.id)
    raw_value = callback.data.split(":", 1)[1]

    state["study_form_raw"] = raw_value
    state["study_form_label"] = STUDY_FORM_LABELS.get(raw_value, raw_value)
    state["stage"] = "degree"

    await callback.answer()
    await callback.message.answer(
        f"Форма обучения: {state['study_form_label']}\n\nТеперь выбери ступень:",
        reply_markup=degree_keyboard(),
    )


@dp.callback_query(F.data.startswith("degree:"))
async def degree_selected(callback: CallbackQuery):
    state = get_state(callback.from_user.id)
    degree_code = int(callback.data.split(":", 1)[1])

    state["degree_code"] = degree_code
    state["degree_label"] = DEGREE_LABELS.get(degree_code, str(degree_code))
    state["stage"] = "group_query"

    await callback.answer()
    await callback.message.answer(
        "Теперь введи группу вручную.\n"
        "Например: 5130904/50002"
    )


@dp.message()
async def text_router(message: Message):
    state = get_state(message.from_user.id)

    if state.get("stage") != "group_query":
        return

    query = (message.text or "").strip()
    if not query:
        await message.answer("Введи номер группы текстом.")
        return

    faculty_id = state.get("faculty_id")
    study_form_raw = state.get("study_form_raw")
    degree_label = state.get("degree_label")

    if not faculty_id or not study_form_raw or not degree_label:
        await message.answer("Сначала заново выбери институт, форму обучения и ступень.")
        return

    try:
        data = await backend_get(
            f"/faculties/{faculty_id}/groups/filtered",
            params={
                "study_form": study_form_raw,
                "degree": degree_label,
                "q": query,
            },
        )
    except Exception as e:
        await message.answer(f"Ошибка поиска группы: {e}")
        return

    groups = data.get("groups", [])
    count = data.get("count", 0)

    if not groups:
        await message.answer(
            "Ничего не найдено.\n"
            "Попробуй ввести группу точнее.\n"
            "Например: 5130904/50002"
        )
        return

    state["group_candidates"] = {str(g["id"]): g for g in groups[:10]}
    state["stage"] = "group_pick"

    await message.answer(
        f"Найдено групп: {count}\nВыбери нужную:",
        reply_markup=groups_keyboard(groups),
    )


@dp.callback_query(F.data == "group:retry")
async def retry_group_selection(callback: CallbackQuery):
    state = get_state(callback.from_user.id)
    state["stage"] = "group_query"
    await callback.answer()
    await callback.message.answer(
        "Введи номер группы ещё раз.\n"
        "Например: 5130904/50002"
    )


@dp.callback_query(F.data.startswith("group:"))
async def group_selected(callback: CallbackQuery):
    _, group_id = callback.data.split(":", 1)

    if group_id == "retry":
        return

    state = get_state(callback.from_user.id)
    group = state.get("group_candidates", {}).get(group_id)

    if not group:
        await callback.answer("Группа не найдена в текущем списке.", show_alert=True)
        return

    state["selected_group"] = group
    state["stage"] = None
    state["anchor_date"] = date.today().isoformat()

    await callback.answer()
    await callback.message.answer(
        f"Выбрана группа: {group['name']}\n"
        f"Курс: {group.get('level')}\n"
        f"Форма: {group.get('study_form')}\n"
        f"Ступень: {group.get('degree')}"
    )

    await show_schedule(callback.message.chat.id, callback.from_user.id, date.today())


@dp.callback_query(F.data.startswith("schedule:"))
async def schedule_navigation(callback: CallbackQuery):
    state = get_state(callback.from_user.id)
    selected_group = state.get("selected_group")

    if not selected_group:
        await callback.answer("Сначала выбери группу.", show_alert=True)
        return

    action = callback.data.split(":", 1)[1]

    base_iso = state.get("anchor_date")
    base_date = date.fromisoformat(base_iso) if base_iso else date.today()

    if action == "current":
        target = date.today()
    elif action == "prev":
        target = base_date - timedelta(days=7)
    elif action == "next":
        target = base_date + timedelta(days=7)
    else:
        target = date.today()

    await callback.answer()
    await show_schedule(callback.message.chat.id, callback.from_user.id, target)


@dp.callback_query(F.data == "sub:add")
async def add_subscription(callback: CallbackQuery):
    state = get_state(callback.from_user.id)
    group = state.get("selected_group")

    if not group:
        await callback.answer("Сначала выбери группу.", show_alert=True)
        return

    try:
        await backend_post_json(
            "/subscriptions",
            {
                "telegram_id": callback.from_user.id,
                "group": group,
                "faculty_name": state.get("faculty_name"),
            },
        )
        await callback.answer("Подписка сохранена")
        await callback.message.answer("Группа добавлена в подписки.")
    except httpx.HTTPStatusError as e:
        detail = "Не удалось сохранить подписку."
        try:
            data = e.response.json()
            if isinstance(data, dict) and data.get("detail"):
                detail = data["detail"]
        except Exception:
            pass

        await callback.answer("Ошибка", show_alert=True)
        await callback.message.answer(detail)
    except Exception as e:
        await callback.answer("Ошибка", show_alert=True)
        await callback.message.answer(f"Не удалось сохранить подписку.\nОшибка: {e}")

@dp.callback_query(F.data == "sub:remove")
async def remove_current_subscription(callback: CallbackQuery):
    state = get_state(callback.from_user.id)
    group = state.get("selected_group")

    if not group:
        await callback.answer("Сначала выбери группу.", show_alert=True)
        return

    try:
        await backend_delete(
            f"/users/{callback.from_user.id}/subscriptions/by-group/{group['id']}"
        )
        await callback.answer("Подписка удалена")
        await callback.message.answer("Группа удалена из подписок.")
    except Exception as e:
        await callback.answer("Ошибка", show_alert=True)
        await callback.message.answer(f"Не удалось удалить подписку.\nОшибка: {e}")


@dp.callback_query(F.data == "subs:list")
async def subscriptions_list_callback(callback: CallbackQuery):
    await callback.answer()
    await show_subscriptions(callback.message.chat.id, callback.from_user.id)


@dp.callback_query(F.data.startswith("subs:open:"))
async def open_subscription_group(callback: CallbackQuery):
    group_id = int(callback.data.split(":", 2)[2])

    try:
        items = await fetch_subscriptions(callback.from_user.id)
    except Exception as e:
        await callback.answer("Ошибка", show_alert=True)
        await callback.message.answer(f"Не удалось загрузить подписки.\nОшибка: {e}")
        return

    found = None
    for item in items:
        group = item.get("group") or {}
        if group.get("id") == group_id:
            found = group
            break

    if not found:
        await callback.answer("Подписка не найдена.", show_alert=True)
        return

    state = get_state(callback.from_user.id)
    state["selected_group"] = found
    state["faculty_id"] = found.get("faculty_id")
    state["faculty_name"] = found.get("faculty_name")
    state["study_form_label"] = found.get("study_form")
    state["degree_label"] = found.get("degree")
    state["anchor_date"] = date.today().isoformat()
    state["stage"] = None

    await callback.answer()
    await show_schedule(callback.message.chat.id, callback.from_user.id, date.today())


@dp.callback_query(F.data.startswith("subs:del:"))
async def delete_subscription_callback(callback: CallbackQuery):
    subscription_id = int(callback.data.split(":", 2)[2])

    try:
        await backend_delete(f"/subscriptions/{subscription_id}")
        await callback.answer("Подписка удалена")
        await callback.message.answer("Подписка удалена.")
        await show_subscriptions(callback.message.chat.id, callback.from_user.id)
    except Exception as e:
        await callback.answer("Ошибка", show_alert=True)
        await callback.message.answer(f"Не удалось удалить подписку.\nОшибка: {e}")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())