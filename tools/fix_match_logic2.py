import pathlib
p = pathlib.Path('ledger/domain/direct_trip_schedule_authority.py')
content = p.read_text(encoding='utf-8')

old_func = '''def match_service_period(
    service_start_on: str,
    service_end_on: str,
    records: Iterable[ScheduleRecord],
    *,
    authoritative_only: bool = True,
) -> list[ScheduleRecord]:
    """Return containing schedules using checkout-exclusive booking dates.

    Tie-breaking when multiple trips match:
    1. Prefer trip where starts_on == service_start_on (trip begins on check-in day)
    2. Prefer trip with latest starts_on (most recent trip)
    """
    period = normalize_service_period(service_start_on, service_end_on)
    matches = [
        record
        for record in records
        if (not authoritative_only or record.is_authoritative)
        and record.starts_on <= period.service_start_on
        and period.last_service_on <= record.ends_on
    ]
    if len(matches) <= 1:
        return sorted(matches, key=lambda record: record.trip_code)

    # Tie-break: prefer trip starting on check-in day
    exact_start = [r for r in matches if r.starts_on == period.service_start_on]
    if len(exact_start) == 1:
        return exact_start

    # Tie-break: prefer most recent trip (latest starts_on)
    latest_start = max(matches, key=lambda r: r.starts_on)
    return [latest_start]'''

new_func = '''def match_service_period(
    service_start_on: str,
    service_end_on: str,
    records: Iterable[ScheduleRecord],
    *,
    authoritative_only: bool = True,
) -> list[ScheduleRecord]:
    """Return containing schedules using checkout-exclusive booking dates.

    Tie-breaking when multiple trips match:
    1. Prefer trip where starts_on == service_start_on (trip begins on check-in day)
    2. Prefer trip with latest starts_on (most recent trip)
    3. Prefer trip with latest ends_on (longest trip, outer trip)
    """
    period = normalize_service_period(service_start_on, service_end_on)
    matches = [
        record
        for record in records
        if (not authoritative_only or record.is_authoritative)
        and record.starts_on <= period.service_start_on
        and period.last_service_on <= record.ends_on
    ]
    if len(matches) <= 1:
        return sorted(matches, key=lambda record: record.trip_code)

    # Tie-break 1: prefer trip starting on check-in day
    exact_start = [r for r in matches if r.starts_on == period.service_start_on]
    if len(exact_start) == 1:
        return exact_start

    # Tie-break 2: prefer most recent trip (latest starts_on)
    max_start = max(r.starts_on for r in matches)
    latest_start = [r for r in matches if r.starts_on == max_start]
    if len(latest_start) == 1:
        return latest_start

    # Tie-break 3: prefer longest trip (latest ends_on)
    longest = max(latest_start, key=lambda r: r.ends_on)
    return [longest]'''

content = content.replace(old_func, new_func)
p.write_text(content, encoding='utf-8')
print("Updated")