from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Iterable, List
import re

TIME_BUCKETS = ("morning", "afternoon", "night")


def normalize_bucket(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip().lower()
    if text in {"morning", "am", "breakfast", "before breakfast", "after breakfast"}:
        return "morning"
    if text in {"afternoon", "noon", "lunch", "before lunch", "after lunch"}:
        return "afternoon"
    if text in {"night", "evening", "bedtime", "before dinner", "after dinner", "pm"}:
        return "night"
    return None


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def is_prescription_active(data: Dict[str, Any], on_date: date) -> bool:
    status = (data.get("status") or "active").lower()
    if status != "active":
        return False

    start = parse_iso_date(data.get("start_date"))
    duration_days = data.get("duration_days")

    if start and isinstance(duration_days, int) and duration_days > 0:
        end = start + timedelta(days=duration_days - 1)
        if not (start <= on_date <= end):
            return False

    expiry = parse_iso_date(data.get("expiry_date"))
    if expiry and on_date > expiry:
        return False

    return True


def infer_buckets_from_medicine(med: Dict[str, Any]) -> List[str]:
    buckets: List[str] = []

    times = med.get("times")
    if isinstance(times, list):
        for t in times:
            b = normalize_bucket(str(t))
            if b and b not in buckets:
                buckets.append(b)
        if buckets:
            return buckets

    raw_timing = str(med.get("timing", "") or med.get("time", "")).lower()
    timing_tokens = re.split(r"[,/;| ]+", raw_timing)
    for token in timing_tokens:
        b = normalize_bucket(token)
        if b and b not in buckets:
            buckets.append(b)

    if buckets:
        return buckets

    dosage = str(med.get("dosage", "")).strip()
    # Common pattern like 1-0-1, 1-1-1
    if re.match(r"^\d-\d-\d$", dosage):
        m, a, n = [int(x) for x in dosage.split("-")]
        if m > 0:
            buckets.append("morning")
        if a > 0:
            buckets.append("afternoon")
        if n > 0:
            buckets.append("night")
        if buckets:
            return buckets

    frequency = str(med.get("frequency", "")).lower()
    if "thrice" in frequency or "three" in frequency or "3" in frequency:
        return ["morning", "afternoon", "night"]
    if "twice" in frequency or "two" in frequency or "2" in frequency:
        return ["morning", "night"]

    return ["morning"]


def medicine_label(med: Dict[str, Any]) -> str:
    name = str(med.get("name", "")).strip()
    dosage = str(med.get("dosage", "")).strip()
    if dosage:
        return f"{name} {dosage}".strip()
    return name or "Medicine"


def expected_schedule_from_prescription(data: Dict[str, Any], on_date: date) -> Dict[str, List[str]]:
    expected = {"morning": [], "afternoon": [], "night": []}
    if not is_prescription_active(data, on_date):
        return expected

    meds = data.get("medicines", [])
    if not isinstance(meds, list):
        return expected

    for med in meds:
        if not isinstance(med, dict):
            continue
        label = medicine_label(med)
        for bucket in infer_buckets_from_medicine(med):
            expected[bucket].append(label)

    return expected


def aggregate_expected_schedule(prescriptions: Iterable[Dict[str, Any]], on_date: date) -> Dict[str, List[str]]:
    combined = {"morning": [], "afternoon": [], "night": []}
    for p in prescriptions:
        item = expected_schedule_from_prescription(p, on_date)
        for bucket in TIME_BUCKETS:
            combined[bucket].extend(item[bucket])
    return combined

