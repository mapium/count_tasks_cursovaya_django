from datetime import date, datetime

from django import template

register = template.Library()

MONTHS_RU = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}


def _parse_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value:
        return None

    raw = str(value).strip()
    if not raw:
        return None
    if "T" in raw:
        raw = raw.split("T", 1)[0]
    elif " " in raw:
        raw = raw.split(" ", 1)[0]
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


@register.filter
def ru_date(value):
    parsed = _parse_date(value)
    if parsed is None:
        return value or ""
    return f"{parsed.day} {MONTHS_RU.get(parsed.month, '')} {parsed.year}".strip()
