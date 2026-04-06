from copy import deepcopy

from app.services.checker import (
    normalize_schedule,
    compute_schedule_hash,
    apply_demo_change,
    compare_normalized_schedules,
)


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


def test_normalize_schedule_returns_expected_shape():
    raw = sample_raw_schedule()

    normalized = normalize_schedule(raw)

    assert normalized["group"]["id"] == 42676
    assert normalized["group"]["name"] == "5130904/50002"
    assert normalized["week"]["date_start"] == "2026.03.30"
    assert normalized["week"]["date_end"] == "2026.04.05"
    assert normalized["week"]["is_odd"] is True
    assert len(normalized["days"]) == 1
    assert normalized["days"][0]["weekday"] == 1
    assert normalized["days"][0]["date"] == "2026-03-30"
    assert len(normalized["days"][0]["lessons"]) == 1

    lesson = normalized["days"][0]["lessons"][0]
    assert lesson["subject"] == "Структуры данных"
    assert lesson["type_abbr"] == "Лаб"
    assert lesson["teachers"] == ["Александрова Ольга Всеволодовна"]
    assert lesson["auditories"][0]["building"] == "3 к."
    assert lesson["auditories"][0]["room"] == "103"


def test_compute_schedule_hash_same_input_is_stable():
    raw = sample_raw_schedule()

    normalized_1 = normalize_schedule(raw)
    normalized_2 = normalize_schedule(raw)

    hash_1 = compute_schedule_hash(normalized_1)
    hash_2 = compute_schedule_hash(normalized_2)

    assert hash_1 == hash_2


def test_compute_schedule_hash_changes_when_schedule_changes():
    raw = sample_raw_schedule()

    normalized_1 = normalize_schedule(raw)

    changed_raw = deepcopy(raw)
    changed_raw["days"][0]["lessons"][0]["additional_info"] = "5130904/50002 п/г 2"

    normalized_2 = normalize_schedule(changed_raw)

    hash_1 = compute_schedule_hash(normalized_1)
    hash_2 = compute_schedule_hash(normalized_2)

    assert hash_1 != hash_2


def test_apply_demo_change_actually_modifies_payload():
    raw = sample_raw_schedule()
    normalized = normalize_schedule(raw)

    demo_changed = apply_demo_change(normalized)

    assert demo_changed != normalized

    original_room = normalized["days"][0]["lessons"][0]["auditories"][0]["room"]
    changed_room = demo_changed["days"][0]["lessons"][0]["auditories"][0]["room"]

    assert original_room != changed_room
    assert changed_room == "999 DEMO"


def test_compare_normalized_schedules_detects_room_change():
    raw = sample_raw_schedule()

    old_payload = normalize_schedule(raw)

    new_raw = deepcopy(raw)
    new_raw["days"][0]["lessons"][0]["auditories"][0]["name"] = "205"

    new_payload = normalize_schedule(new_raw)

    old_hash = compute_schedule_hash(old_payload)
    new_hash = compute_schedule_hash(new_payload)
    diff_lines = compare_normalized_schedules(old_payload, new_payload)

    assert old_hash != new_hash
    assert len(diff_lines) > 0


def test_compare_normalized_schedules_detects_added_lesson():
    raw = sample_raw_schedule()

    old_payload = normalize_schedule(raw)

    new_raw = deepcopy(raw)
    new_raw["days"][0]["lessons"].append(
        {
            "subject": "Практикум по программированию",
            "subject_short": "Практикум по программированию",
            "time_start": "10:00",
            "time_end": "11:40",
            "additional_info": "",
            "typeObj": {
                "name": "Практика",
                "abbr": "Пр",
            },
            "teachers": [{"full_name": "Шемякин Илья Александрович"}],
            "auditories": [
                {
                    "name": "104",
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
            "lms_url": "",
        }
    )

    new_payload = normalize_schedule(new_raw)

    old_hash = compute_schedule_hash(old_payload)
    new_hash = compute_schedule_hash(new_payload)
    diff_lines = compare_normalized_schedules(old_payload, new_payload)

    assert old_hash != new_hash
    assert len(diff_lines) > 0