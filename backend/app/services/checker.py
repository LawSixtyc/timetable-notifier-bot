import hashlib
import json
from datetime import date, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ChangeEvent, ScheduleSnapshot, Subscription, TrackedGroup, User


DAY_NAMES = {
    1: "Понедельник",
    2: "Вторник",
    3: "Среда",
    4: "Четверг",
    5: "Пятница",
    6: "Суббота",
    7: "Воскресенье",
}


def normalize_schedule(raw_schedule: dict[str, Any]) -> dict[str, Any]:
    group = raw_schedule.get("group") or {}
    week = raw_schedule.get("week") or {}

    normalized_days = []

    for day in raw_schedule.get("days") or []:
        normalized_lessons = []

        for lesson in day.get("lessons") or []:
            teachers = []
            for teacher in lesson.get("teachers") or []:
                full_name = teacher.get("full_name") or ""
                if full_name:
                    teachers.append(full_name)

            auditories = []
            for aud in lesson.get("auditories") or []:
                building = aud.get("building") or {}
                auditories.append(
                    {
                        "building": building.get("abbr") or building.get("name") or "",
                        "room": aud.get("name") or "",
                    }
                )

            lesson_groups = []
            for g in lesson.get("groups") or []:
                lesson_groups.append(
                    {
                        "id": g.get("id"),
                        "name": g.get("name"),
                    }
                )

            normalized_lessons.append(
                {
                    "subject": lesson.get("subject") or "",
                    "subject_short": lesson.get("subject_short") or "",
                    "time_start": lesson.get("time_start") or "",
                    "time_end": lesson.get("time_end") or "",
                    "additional_info": lesson.get("additional_info") or "",
                    "type_name": ((lesson.get("typeObj") or {}).get("name")) or "",
                    "type_abbr": ((lesson.get("typeObj") or {}).get("abbr")) or "",
                    "teachers": teachers,
                    "auditories": auditories,
                    "groups": lesson_groups,
                    "webinar_url": lesson.get("webinar_url") or "",
                    "lms_url": lesson.get("lms_url") or "",
                }
            )

        normalized_days.append(
            {
                "weekday": day.get("weekday"),
                "date": day.get("date"),
                "lessons": normalized_lessons,
            }
        )

    return {
        "group": {
            "id": group.get("id"),
            "name": group.get("name"),
        },
        "week": {
            "date_start": week.get("date_start"),
            "date_end": week.get("date_end"),
            "is_odd": week.get("is_odd"),
        },
        "days": normalized_days,
    }


def compute_schedule_hash(normalized_schedule: dict[str, Any]) -> str:
    payload = json.dumps(
        normalized_schedule,
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def apply_demo_change(normalized_schedule: dict[str, Any]) -> dict[str, Any]:
    clone = json.loads(json.dumps(normalized_schedule, ensure_ascii=False))

    for day in clone.get("days", []):
        lessons = day.get("lessons", [])
        if lessons:
            first_lesson = lessons[0]
            current_info = first_lesson.get("additional_info", "")
            first_lesson["additional_info"] = (current_info + " [DEMO CHANGE]").strip()

            auditories = first_lesson.get("auditories", [])
            if auditories:
                auditories[0]["room"] = "999 DEMO"

            return clone

    clone["demo_marker"] = "changed"
    return clone


def fmt_date(date_str: str) -> str:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%d.%m")
    except Exception:
        return date_str


def teachers_to_text(teachers: list[str]) -> str:
    return ", ".join(teachers) if teachers else "—"


def auditories_to_text(auditories: list[dict[str, str]]) -> str:
    if not auditories:
        return "—"

    parts = []
    for aud in auditories:
        building = aud.get("building", "")
        room = aud.get("room", "")
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


def lesson_key(day_date: str, lesson: dict[str, Any]) -> tuple:
    return (
        day_date,
        lesson.get("time_start", ""),
        lesson.get("time_end", ""),
        lesson.get("subject", ""),
        lesson.get("additional_info", ""),
    )


def lesson_label(day_date: str, weekday: int, lesson: dict[str, Any]) -> str:
    day_name = DAY_NAMES.get(weekday, str(weekday))
    return (
        f"{day_name}, {fmt_date(day_date)} "
        f"{lesson.get('time_start', '')}-{lesson.get('time_end', '')} "
        f"{lesson.get('subject', '')}"
    )


def flatten_schedule(normalized_schedule: dict[str, Any]) -> dict[tuple, dict[str, Any]]:
    flat: dict[tuple, dict[str, Any]] = {}
    for day in normalized_schedule.get("days", []):
        day_date = day.get("date", "")
        weekday = day.get("weekday")
        for lesson in day.get("lessons", []):
            item = dict(lesson)
            item["_day_date"] = day_date
            item["_weekday"] = weekday
            flat[lesson_key(day_date, lesson)] = item
    return flat


def compare_normalized_schedules(old_payload: dict[str, Any], new_payload: dict[str, Any]) -> list[str]:
    old_flat = flatten_schedule(old_payload)
    new_flat = flatten_schedule(new_payload)

    all_keys = sorted(set(old_flat.keys()) | set(new_flat.keys()))
    lines: list[str] = []

    for key in all_keys:
        old_item = old_flat.get(key)
        new_item = new_flat.get(key)

        reference = new_item or old_item
        label = lesson_label(
            reference.get("_day_date", ""),
            reference.get("_weekday"),
            reference,
        )

        if old_item is None and new_item is not None:
            lines.append(f"• {label} — добавлено занятие")
            continue

        if old_item is not None and new_item is None:
            lines.append(f"• {label} — занятие удалено")
            continue

        changes = []

        if old_item.get("type_abbr") != new_item.get("type_abbr"):
            changes.append(f"вид: {old_item.get('type_abbr', '—')} → {new_item.get('type_abbr', '—')}")

        if old_item.get("teachers") != new_item.get("teachers"):
            changes.append(
                f"преподаватель: {teachers_to_text(old_item.get('teachers', []))} → "
                f"{teachers_to_text(new_item.get('teachers', []))}"
            )

        if old_item.get("auditories") != new_item.get("auditories"):
            changes.append(
                f"аудитория: {auditories_to_text(old_item.get('auditories', []))} → "
                f"{auditories_to_text(new_item.get('auditories', []))}"
            )

        if old_item.get("additional_info") != new_item.get("additional_info"):
            changes.append(
                f"инфо: {old_item.get('additional_info', '—')} → {new_item.get('additional_info', '—')}"
            )

        if old_item.get("time_start") != new_item.get("time_start") or old_item.get("time_end") != new_item.get("time_end"):
            changes.append(
                f"время: {old_item.get('time_start', '')}-{old_item.get('time_end', '')} → "
                f"{new_item.get('time_start', '')}-{new_item.get('time_end', '')}"
            )

        if changes:
            lines.append(f"• {label} — " + "; ".join(changes))

    return lines


async def send_telegram_message(bot_token: str, chat_id: int, text: str) -> None:
    if not bot_token:
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
            },
        )
        response.raise_for_status()


def build_change_message(
    group_name: str,
    week_start: str,
    week_end: str,
    is_demo: bool,
    diff_lines: list[str],
) -> str:
    prefix = "🧪 DEMO: " if is_demo else "🔔 "
    lines = [
        f"{prefix}Изменения в расписании группы {group_name}",
        f"Неделя: {week_start} — {week_end}",
        "",
    ]

    if diff_lines:
        lines.append("Что изменилось:")
        lines.extend(diff_lines[:8])
        if len(diff_lines) > 8:
            lines.append(f"• ... и ещё {len(diff_lines) - 8}")
    else:
        lines.append("Обнаружены изменения в расписании.")

    lines.extend(
        [
            "",
            "Открой «Моё расписание» или «Мои подписки», чтобы посмотреть актуальную версию.",
        ]
    )
    return "\n".join(lines)


async def run_checker_once(
    session: AsyncSession,
    ruz_client,
    bot_token: str | None,
    target_date: str | None = None,
    demo_change: bool = False,
) -> dict[str, Any]:
    target_date = target_date or date.today().isoformat()

    rows = await session.execute(
        select(Subscription, TrackedGroup, User)
        .join(TrackedGroup, Subscription.tracked_group_id == TrackedGroup.id)
        .join(User, Subscription.user_id == User.id)
        .where(Subscription.is_active.is_(True))
    )

    subscriptions = rows.all()

    grouped: dict[int, dict[str, Any]] = {}
    for subscription, tracked_group, user in subscriptions:
        if tracked_group.id not in grouped:
            grouped[tracked_group.id] = {
                "tracked_group": tracked_group,
                "users": [],
            }
        grouped[tracked_group.id]["users"].append(user)

    results: list[dict[str, Any]] = []
    initialized_groups = 0
    changed_groups = 0
    notifications_sent = 0

    for index, item in enumerate(grouped.values()):
        tracked_group: TrackedGroup = item["tracked_group"]
        users: list[User] = item["users"]

        try:
            raw_schedule = await ruz_client.get_group_schedule(
                tracked_group.ruz_group_id,
                date=target_date,
            )

            normalized = normalize_schedule(raw_schedule)
            use_demo_change = demo_change and index == 0
            normalized_for_compare = apply_demo_change(normalized) if use_demo_change else normalized
            new_hash = compute_schedule_hash(normalized_for_compare)

            week = normalized_for_compare.get("week") or {}
            week_start_raw = week.get("date_start")
            week_end_raw = week.get("date_end")

            week_start = datetime.strptime(week_start_raw, "%Y.%m.%d").date()
            week_end = datetime.strptime(week_end_raw, "%Y.%m.%d").date()

            latest_real_snapshot = (
                await session.execute(
                    select(ScheduleSnapshot)
                    .where(
                        ScheduleSnapshot.tracked_group_id == tracked_group.id,
                        ScheduleSnapshot.is_demo.is_(False),
                    )
                    .order_by(ScheduleSnapshot.created_at.desc())
                )
            ).scalars().first()

            if latest_real_snapshot is None:
                baseline_payload = normalized
                baseline_hash = compute_schedule_hash(baseline_payload)

                baseline_snapshot = ScheduleSnapshot(
                    tracked_group_id=tracked_group.id,
                    week_start=week_start,
                    week_end=week_end,
                    hash=baseline_hash,
                    payload_json=baseline_payload,
                    is_demo=False,
                )
                session.add(baseline_snapshot)
                initialized_groups += 1

                print(
                    f"[checker] group={tracked_group.name} status=initialized "
                    f"hash={baseline_hash[:8]}"
                )

                results.append(
                    {
                        "group": tracked_group.name,
                        "status": "initialized",
                        "week": f"{week_start_raw} — {week_end_raw}",
                    }
                )
                continue

            if latest_real_snapshot.hash == new_hash:
                print(f"[checker] group={tracked_group.name} status=no_change hash={new_hash[:8]}")
                results.append(
                    {
                        "group": tracked_group.name,
                        "status": "no_change",
                        "week": f"{week_start_raw} — {week_end_raw}",
                    }
                )
                continue

            old_payload = latest_real_snapshot.payload_json or {}
            diff_lines = compare_normalized_schedules(old_payload, normalized_for_compare)

            message = build_change_message(
                group_name=tracked_group.name,
                week_start=week_start_raw,
                week_end=week_end_raw,
                is_demo=use_demo_change,
                diff_lines=diff_lines,
            )

            snapshot = ScheduleSnapshot(
                tracked_group_id=tracked_group.id,
                week_start=week_start,
                week_end=week_end,
                hash=new_hash,
                payload_json=normalized_for_compare,
                is_demo=use_demo_change,
            )
            session.add(snapshot)

            event = ChangeEvent(
                tracked_group_id=tracked_group.id,
                old_hash=latest_real_snapshot.hash,
                new_hash=new_hash,
                message=message,
                is_demo=use_demo_change,
            )
            session.add(event)

            seen_user_ids = set()
            sent_for_group = 0

            for user in users:
                if user.telegram_id in seen_user_ids:
                    continue
                seen_user_ids.add(user.telegram_id)

                await send_telegram_message(
                    bot_token=bot_token or "",
                    chat_id=user.telegram_id,
                    text=message,
                )
                notifications_sent += 1
                sent_for_group += 1

            log_status = "demo_changed" if use_demo_change else "changed"
            print(
                f"[checker] group={tracked_group.name} status={log_status} "
                f"old={latest_real_snapshot.hash[:8]} new={new_hash[:8]} "
                f"diffs={len(diff_lines)} notifications={sent_for_group}"
            )

            changed_groups += 1
            results.append(
                {
                    "group": tracked_group.name,
                    "status": "changed",
                    "week": f"{week_start_raw} — {week_end_raw}",
                    "demo": use_demo_change,
                    "diff_count": len(diff_lines),
                }
            )

        except Exception as e:
            print(f"[checker] group={tracked_group.name} status=error error={e}")
            results.append(
                {
                    "group": tracked_group.name,
                    "status": "error",
                    "detail": str(e),
                }
            )

    await session.commit()

    return {
        "ok": True,
        "demo_change": demo_change,
        "target_date": target_date,
        "checked_groups": len(grouped),
        "initialized_groups": initialized_groups,
        "changed_groups": changed_groups,
        "notifications_sent": notifications_sent,
        "results": results,
    }