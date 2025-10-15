def shift_safe(lst, idx, offset=1):
    j = idx + offset
    if j < 0 or j >= len(lst):
        return None
    return lst[j]