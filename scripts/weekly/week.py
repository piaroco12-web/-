"""Saturday publication weeks in Korea Standard Time."""
import argparse
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KST = timezone(timedelta(hours=9))


def interval(week):
    if not re.fullmatch(r"[0-9]{4}-W[0-9]{2}", week):
        raise ValueError("주차 형식은 YYYY-Www")
    year, number = week.split("-W")
    saturday = date.fromisocalendar(int(year), int(number), 6)
    end = datetime.combine(saturday, time.min, KST)
    return end - timedelta(days=7), end


def publication_week():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week", required=True)
    week = parser.parse_args().week
    try:
        interval(week)
    except ValueError as error:
        parser.error(str(error))
    return week
