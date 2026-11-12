"""Deterministic, timezone-aware date/time parsing for calendar requests (Phase 5).

Rules:
- "now" is injected (tests freeze it); all arithmetic happens in the event's IANA zone;
- nothing ambiguous is guessed: "3 baje" (AM or PM?), "10/11" (10 Nov or 11 Oct?), a missing
  date, time or duration, a time that has already passed or a wall time skipped by a DST
  change all produce a clarification instead of an event;
- assumptions that ARE made (e.g. "kal" read as tomorrow, a repeated DST hour) are listed so
  the approval dialog shows them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ_ALIASES = {
    "ist": "Asia/Kolkata", "india time": "Asia/Kolkata", "pst": "America/Los_Angeles", "pdt": "America/Los_Angeles",
    "pacific time": "America/Los_Angeles", "est": "America/New_York", "edt": "America/New_York",
    "eastern time": "America/New_York", "cst": "America/Chicago", "cdt": "America/Chicago", "gmt": "Europe/London",
    "bst": "Europe/London", "london time": "Europe/London", "utc": "UTC", "cet": "Europe/Berlin", "cest": "Europe/Berlin",
    "jst": "Asia/Tokyo", "sgt": "Asia/Singapore", "aest": "Australia/Sydney", "gst": "Asia/Dubai", "dubai time": "Asia/Dubai",
}
_TZ_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(TZ_ALIASES, key=len, reverse=True)) + r")\b", re.IGNORECASE)
_IANA_RE = re.compile(r"\b([A-Z][a-z]+(?:_[A-Z][a-z]+)?/[A-Z][A-Za-z_]+)\b")
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
            "somvar": 0, "mangalvar": 1, "budhvar": 2, "guruvar": 3, "shukravar": 4, "shanivar": 5, "ravivar": 6}
_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_DAY_MON = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MON}\b(?:,?\s+(\d{{4}}))?", re.IGNORECASE)
_MON_DAY = re.compile(rf"\b{_MON}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}}))?", re.IGNORECASE)
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_NUMERIC = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b")
_REL = re.compile(r"\b(day after tomorrow|parso|tomorrow|today|tonight|aaj|kal)\b", re.IGNORECASE)
_WEEKDAY = re.compile(r"\b(next\s+|this\s+|coming\s+)?(" + "|".join(WEEKDAYS) + r")\b", re.IGNORECASE)

_AMPM = r"(a\.?m\.?|p\.?m\.?)"
_RANGE = re.compile(
    rf"\b(?:from\s+)?(\d{{1,2}})(?::(\d{{2}}))?\s*{_AMPM}?\s*(?:-|–|to|till|until)\s*(\d{{1,2}})(?::(\d{{2}}))?\s*{_AMPM}?(?![\w/])",
    re.IGNORECASE,
)
_TIME_AMPM = re.compile(rf"\b(\d{{1,2}})(?::(\d{{2}}))?\s*{_AMPM}(?![a-z])", re.IGNORECASE)
_TIME_24 = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b(?!\s*(?:a\.?m|p\.?m))", re.IGNORECASE)
_BAJE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*baje\b", re.IGNORECASE)
_AT = re.compile(r"(?:\bat|@)\s*(\d{1,2})(?::(\d{2}))?\b(?!\s*(?:a\.?m|p\.?m|baje|:))", re.IGNORECASE)
_BARE_AMPM = re.compile(r"(?<![\d:])\b(a\.?m\.?|p\.?m\.?)(?![a-z])", re.IGNORECASE)
_NOON = re.compile(r"\b(noon|midday|midnight)\b", re.IGNORECASE)
_MORNING = re.compile(r"\b(morning|subah|savere)\b", re.IGNORECASE)
_EVENING = re.compile(r"\b(afternoon|evening|night|tonight|dopahar|dopehar|shaam|sham|raat)\b", re.IGNORECASE)

_DUR = re.compile(
    r"(?<!\bin )\b(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m|ghante|ghanta)\b"
    r"|\b(an|one|ek)\s+(hour|ghanta)\b|\b(half an hour|aadha ghanta|half hour)\b|\b(quarter of an hour)\b",
    re.IGNORECASE,
)


@dataclass
class ParsedTime:
    start: datetime | None = None
    end: datetime | None = None
    timezone: str = "UTC"
    duration_minutes: int | None = None
    assumptions: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    question: str | None = None

    @property
    def ok(self) -> bool:
        return self.start is not None and self.end is not None and not self.missing


def detect_timezone(text: str, default_tz: str) -> tuple[str, bool]:
    m = _IANA_RE.search(text)
    if m:
        try:
            ZoneInfo(m.group(1))
            return m.group(1), True
        except Exception:  # noqa: BLE001
            pass
    m = _TZ_RE.search(text)
    if m:
        return TZ_ALIASES[m.group(1).lower()], True
    return default_tz, False


def _date_part(text: str, today: date) -> tuple[date | None, list[str], str | None]:
    """(date, assumptions, problem) — problem is a missing-info code."""
    notes: list[str] = []
    m = _ISO.search(text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))), notes, None
        except ValueError:
            return None, notes, "date"
    for rx, day_i, mon_i in ((_DAY_MON, 1, 2), (_MON_DAY, 2, 1)):
        m = rx.search(text)
        if m:
            month = MONTHS[m.group(mon_i)[:3].lower()]
            year = int(m.group(3)) if m.group(3) else today.year
            try:
                d = date(year, month, int(m.group(day_i)))
            except ValueError:
                return None, notes, "date"
            if not m.group(3) and d < today:
                d = d.replace(year=today.year + 1)
                notes.append(f"No year given — using {d.year}.")
            return d, notes, None
    m = _NUMERIC.search(text)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        if a <= 12 and b <= 12 and a != b:
            return None, notes, "date_format"
        day, month = (a, b) if a > 12 or a == b else (b, a) if b > 12 else (a, b)
        try:
            return date(year, month, day), notes, None
        except ValueError:
            return None, notes, "date"
    m = _REL.search(text)
    if m:
        word = m.group(1).lower()
        if word in ("today", "aaj", "tonight"):
            return today, notes, None
        if word in ("parso", "day after tomorrow"):
            return today + timedelta(days=2), notes, None
        if word == "kal":
            notes.append("“kal” was read as tomorrow (a future meeting).")
        return today + timedelta(days=1), notes, None
    m = _WEEKDAY.search(text)
    if m:
        target = WEEKDAYS[m.group(2).lower()]
        ahead = (target - today.weekday()) % 7 or 7
        d = today + timedelta(days=ahead)
        notes.append(f"“{m.group(0).strip()}” was read as {d.strftime('%A, %B')} {d.day}.")
        return d, notes, None
    return None, notes, "date"


def _hour24(hour: int, ampm: str | None) -> int | None:
    if hour > 23:
        return None
    if ampm is None:
        return hour
    p = ampm.lower().replace(".", "")
    if hour < 1 or hour > 12:
        return None
    if p == "am":
        return 0 if hour == 12 else hour
    return 12 if hour == 12 else hour + 12


def _time_part(text: str) -> tuple[time | None, time | None, str | None]:
    """(start, end-if-range, problem)."""
    m = next((r for r in _RANGE.finditer(text) if r.group(3) or r.group(6) or r.group(2) or r.group(5)), None)
    if m:
        sa, ea = m.group(3), m.group(6)
        if sa is None and ea is not None:
            sa = ea  # "3-4pm": both pm (if that keeps start before end)
            if int(m.group(1)) % 12 > int(m.group(4)) % 12 and ea.lower().startswith("p"):
                sa = "am"
        if sa is None and ea is None:
            # 24h range like 15:00-16:00 is fine; 3:00-4:00 is ambiguous
            if int(m.group(1)) <= 12 and int(m.group(4)) <= 12:
                return None, None, "am_pm"
        sh, eh = _hour24(int(m.group(1)), sa), _hour24(int(m.group(4)), ea)
        if sh is None or eh is None:
            return None, None, "time"
        return time(sh, int(m.group(2) or 0)), time(eh, int(m.group(5) or 0)), None
    m = _TIME_AMPM.search(text)
    if m:
        h = _hour24(int(m.group(1)), m.group(3))
        return (time(h, int(m.group(2) or 0)) if h is not None else None), None, None if h is not None else "time"
    m = _NOON.search(text)
    if m:
        return (time(0, 0) if m.group(1).lower() == "midnight" else time(12, 0)), None, None
    m = _BAJE.search(text) or _TIME_24.search(text) or _AT.search(text)
    if m:
        h, minute = int(m.group(1)), int(m.group(2) or 0)
        if h > 12 or h == 0:
            return (time(h, minute) if h < 24 else None), None, None if h < 24 else "time"
        bare = _BARE_AMPM.search(text)  # e.g. the answer "PM" to "AM or PM?"
        if _MORNING.search(text) or (bare and bare.group(1).lower().startswith("a")):
            return time(0 if h == 12 else h, minute), None, None
        if _EVENING.search(text) or bare:
            return time(12 if h == 12 else h + 12, minute), None, None
        return None, None, "am_pm"
    return None, None, "time"


def parse_duration(text: str) -> int | None:
    m = _DUR.search(text)
    if not m:
        return None
    if m.group(5):
        return 30
    if m.group(6):
        return 15
    if m.group(3):
        return 60
    value, unit = float(m.group(1)), m.group(2).lower()
    minutes = value * 60 if unit.startswith(("h", "g")) else value
    return int(round(minutes)) if 1 <= minutes <= 24 * 60 else None


QUESTIONS = {
    "date": ("Which date should the event be on?", "Bhai, kis din rakhna hai event?", "इवेंट किस तारीख़ को रखना है?"),
    "time": ("What time should it start?", "Kitne baje shuru karna hai?", "यह कितने बजे शुरू होना चाहिए?"),
    "am_pm": ("Is that AM or PM?", "Bhai, subah (AM) ya shaam (PM)?", "सुबह (AM) या शाम (PM)?"),
    "date_format": ("Which date do you mean — please write it like “10 November”.",
                    "Kaunsi date — “10 November” jaise likh do, bhai.", "कौन-सी तारीख़ — “10 November” की तरह लिखें।"),
    "duration": ("How long should it be (for example 30 minutes or 1 hour)?",
                 "Kitni der ka rakhna hai — jaise 30 minute ya 1 ghanta?", "यह कितनी देर का हो — जैसे 30 मिनट या 1 घंटा?"),
    "past_time": ("That time has already passed. Which date and time should I use?",
                  "Woh time nikal chuka hai bhai. Kaunsi date aur time rakhun?", "वह समय निकल चुका है। कौन-सी तारीख़ और समय रखूँ?"),
    "nonexistent_time": ("That local time does not exist on that day (daylight-saving change). Please choose another time.",
                         "Us din daylight-saving ki wajah se woh time exist nahi karta. Koi aur time bata do.",
                         "उस दिन डेलाइट-सेविंग के कारण वह समय मौजूद नहीं है। कृपया दूसरा समय चुनें।"),
}


def question_for(code: str, lang: str) -> str:
    en, hinglish, hi = QUESTIONS.get(code, QUESTIONS["time"])
    return {"hinglish": hinglish, "hi": hi}.get(lang, en)


def parse_event_time(text: str, *, now: datetime, default_tz: str, default_duration: int = 0, lang: str = "en") -> ParsedTime:
    tz_name, explicit_tz = detect_timezone(text, default_tz)
    tz = ZoneInfo(tz_name)
    out = ParsedTime(timezone=tz_name)
    if not explicit_tz:
        out.assumptions.append(f"Timezone: {tz_name} (your default).")
    local_now = now.astimezone(tz)
    day, notes, problem = _date_part(text, local_now.date())
    out.assumptions.extend(notes)
    start_t, end_t, t_problem = _time_part(text)
    duration = parse_duration(text)
    for code in (problem, t_problem):
        if code and code not in out.missing:
            out.missing.append(code)
    if end_t is None and duration is None:
        if default_duration > 0:
            duration = default_duration
            out.assumptions.append(f"No duration given — using the default of {default_duration} minutes.")
        else:
            out.missing.append("duration")
    if out.missing:
        out.question = question_for(out.missing[0], lang)
        return out
    assert day is not None and start_t is not None
    start = datetime.combine(day, start_t, tzinfo=tz)
    # DST: a skipped wall time does not round-trip; a repeated one has two offsets.
    round_trip = start.astimezone(ZoneInfo("UTC")).astimezone(tz)
    if round_trip.replace(tzinfo=None) != start.replace(tzinfo=None):
        out.missing.append("nonexistent_time")
        out.question = question_for("nonexistent_time", lang)
        return out
    if start.replace(fold=1).utcoffset() != start.utcoffset():
        out.assumptions.append("That time occurs twice (clocks go back) — using the first occurrence.")
    if end_t is not None:
        end = datetime.combine(day, end_t, tzinfo=tz)
        if end <= start:
            end += timedelta(days=1)
            out.assumptions.append("The end time is on the next day.")
        duration = int((end - start).total_seconds() // 60)
    else:
        assert duration is not None
        end = (start.astimezone(ZoneInfo("UTC")) + timedelta(minutes=duration)).astimezone(tz)
    if start <= now:
        out.missing.append("past_time")
        out.question = question_for("past_time", lang)
        return out
    out.start, out.end, out.duration_minutes = start, end, duration
    return out


# ---------------------------------------------------------------------- labels


def _clock(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def date_label(start: datetime) -> str:
    return f"{start.strftime('%A, %B')} {start.day}, {start.year}"


def time_label(start: datetime, end: datetime) -> str:
    suffix = "" if start.date() == end.date() else f" (next day, {end.strftime('%b')} {end.day})"
    return f"{_clock(start)} – {_clock(end)}{suffix}"


def timezone_label(start: datetime, tz_name: str) -> str:
    offset = start.utcoffset() or timedelta(0)
    total = int(offset.total_seconds() // 60)
    sign = "+" if total >= 0 else "-"
    hh, mm = divmod(abs(total), 60)
    return f"{tz_name} ({start.tzname()}, UTC{sign}{hh:02d}:{mm:02d})"
