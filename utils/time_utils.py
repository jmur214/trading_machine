def shift_safe(lst, idx, offset=1):
    j = idx + offset
    if j < 0 or j >= len(lst):
        return None
    return lst[j]


def ensure_utc(dt):
    """Ensure a datetime object is timezone-aware and in UTC."""
    import datetime
    if dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.timezone.utc)
    else:
        return dt.astimezone(datetime.timezone.utc)