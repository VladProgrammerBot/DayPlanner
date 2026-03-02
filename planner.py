#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List

TIME_FMT = "%H:%M"


@dataclass(order=True)
class Activity:
    start: datetime
    end: datetime
    name: str
    kind: str

    @property
    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


def parse_time(base_date: datetime, value: str) -> datetime:
    t = datetime.strptime(value, TIME_FMT)
    return base_date.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)


def split_free_slots(range_start: datetime, range_end: datetime, fixed: List[Activity]) -> List[tuple[datetime, datetime]]:
    slots: List[tuple[datetime, datetime]] = []
    cursor = range_start
    for act in sorted(fixed, key=lambda a: a.start):
        if act.start > cursor:
            slots.append((cursor, act.start))
        cursor = max(cursor, act.end)
    if cursor < range_end:
        slots.append((cursor, range_end))
    return slots


def allocate_spontaneous(
    slots: List[tuple[datetime, datetime]], spontaneous_minutes: int
) -> tuple[List[Activity], List[tuple[datetime, datetime]]]:
    if spontaneous_minutes <= 0 or not slots:
        return [], slots

    total_free = sum(int((end - start).total_seconds() // 60) for start, end in slots)
    if total_free == 0:
        return [], slots

    spontaneous_minutes = min(spontaneous_minutes, total_free)

    allocations = []
    assigned = 0
    for i, (start, end) in enumerate(slots):
        slot_minutes = int((end - start).total_seconds() // 60)
        if i == len(slots) - 1:
            minutes = spontaneous_minutes - assigned
        else:
            minutes = round(spontaneous_minutes * slot_minutes / total_free)
            minutes = min(minutes, spontaneous_minutes - assigned)
        assigned += minutes
        allocations.append(minutes)

    spontaneous_acts: List[Activity] = []
    remaining_slots: List[tuple[datetime, datetime]] = []
    for (start, end), reserve in zip(slots, allocations):
        if reserve > 0:
            reserve_end = start + timedelta(minutes=reserve)
            spontaneous_acts.append(
                Activity(start=start, end=reserve_end, name="Спонтанний час / буфер", kind="spontaneous")
            )
            if reserve_end < end:
                remaining_slots.append((reserve_end, end))
        else:
            remaining_slots.append((start, end))

    return spontaneous_acts, remaining_slots


def allocate_flexible(
    slots: List[tuple[datetime, datetime]], flexible_tasks: list[dict]
) -> tuple[List[Activity], list[dict]]:
    tasks = sorted(
        flexible_tasks,
        key=lambda t: (-int(t.get("priority", 0)), -int(t.get("duration_minutes", 0))),
    )

    planned: List[Activity] = []
    unplanned: list[dict] = []

    mutable_slots = list(slots)
    for task in tasks:
        needed = int(task["duration_minutes"])
        name = str(task["name"])
        task_plans: List[Activity] = []

        for i, (slot_start, slot_end) in enumerate(mutable_slots):
            if needed <= 0:
                break
            slot_minutes = int((slot_end - slot_start).total_seconds() // 60)
            if slot_minutes <= 0:
                continue

            chunk = min(needed, slot_minutes)
            chunk_end = slot_start + timedelta(minutes=chunk)
            task_plans.append(Activity(start=slot_start, end=chunk_end, name=name, kind="flexible"))

            mutable_slots[i] = (chunk_end, slot_end)
            needed -= chunk

        mutable_slots = [(s, e) for s, e in mutable_slots if s < e]

        if needed == 0:
            planned.extend(task_plans)
        else:
            unplanned.append({**task, "missing_minutes": needed})

    return planned, unplanned


def build_plan(data: dict) -> tuple[List[Activity], list[dict]]:
    base_date = datetime.now()
    plan_start = parse_time(base_date, data["planning_range"]["start"])
    plan_end = parse_time(base_date, data["planning_range"]["end"])

    fixed_activities = [
        Activity(
            start=parse_time(base_date, item["start"]),
            end=parse_time(base_date, item["end"]),
            name=item["name"],
            kind="fixed",
        )
        for item in data.get("fixed_activities", [])
    ]

    free_slots = split_free_slots(plan_start, plan_end, fixed_activities)
    spontaneous, slots_after_spontaneous = allocate_spontaneous(
        free_slots, int(data.get("spontaneous_minutes", 0))
    )
    flexible_plans, unplanned = allocate_flexible(slots_after_spontaneous, data.get("flexible_activities", []))

    full_plan = sorted(fixed_activities + spontaneous + flexible_plans, key=lambda a: a.start)
    return full_plan, unplanned


def print_plan(activities: List[Activity], unplanned: list[dict]) -> None:
    print("\nДетальний план дня:")
    print("-" * 72)
    for act in activities:
        print(
            f"{act.start.strftime(TIME_FMT)}-{act.end.strftime(TIME_FMT)} | "
            f"{act.duration_minutes:>3} хв | {act.kind:<11} | {act.name}"
        )
    print("-" * 72)

    if unplanned:
        print("\nНе вдалося повністю запланувати:")
        for task in unplanned:
            print(
                f"- {task['name']} (пріоритет {task.get('priority', 0)}): "
                f"бракує {task['missing_minutes']} хв"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Генератор детального плану дня")
    parser.add_argument("--input", required=True, help="Шлях до JSON з вхідними даними")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    plan, unplanned = build_plan(data)
    print_plan(plan, unplanned)


if __name__ == "__main__":
    main()
