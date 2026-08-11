#!/usr/bin/env python3
"""Classify TEDUH unit numbers into the unit types used in the Johor report.

The rules live in unit_types.json next to projects.csv, so they can be edited
without touching code. A unit number looks like BLOCK-FLOOR-UNIT, e.g. "A-6-4"
or "1A-07-01"; the type is decided by the unit segment, with a table of exact
unit numbers taking precedence (that is what separates A-6-3 from A-7-3).
"""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CFG = None


def config():
    global _CFG
    if _CFG is None:
        path = os.path.join(ROOT, "unit_types.json")
        _CFG = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    return _CFG


def split(unit):
    """'1A-07-01' -> ('1A', 7, 1). Returns None if it doesn't look like a unit number."""
    parts = str(unit).strip().upper().split("-")
    if len(parts) < 3:
        return None
    try:
        return parts[0], int(parts[1]), int(parts[2])
    except ValueError:
        return None


def block_of(unit):
    """The block/tower prefix, used for the Remarks note."""
    p = split(unit)
    return p[0] if p else None


def classify(project_key, unit):
    """Return the unit type for one unit number, or None if no rule matches."""
    spec = config().get(project_key)
    if not spec:
        return None
    key = str(unit).strip().upper()

    exact = spec.get("exact") or {}
    if key in exact:                       # specific units beat the general rule
        return exact[key]

    parts = split(key)
    if not parts:
        return None
    tower, _, num = parts

    by_tower = spec.get("by_tower_unit")
    if by_tower:
        return (by_tower.get(tower) or {}).get(str(num))
    return (spec.get("by_unit") or {}).get(str(num))


def tally(project_key, units):
    """units: iterable of (unit_number, is_sold). Returns per-type and per-block counts."""
    spec = config().get(project_key) or {}
    types = [t["key"] for t in spec.get("types", [])]
    sold_by_type = {t: 0 for t in types}
    total_by_type = {t: 0 for t in types}
    sold_by_block, unmatched = {}, []

    for unit, is_sold in units:
        t = classify(project_key, unit)
        if t is None:
            unmatched.append(unit)
        else:
            total_by_type[t] = total_by_type.get(t, 0) + 1
            if is_sold:
                sold_by_type[t] = sold_by_type.get(t, 0) + 1
        if is_sold:
            b = block_of(unit)
            if b:
                sold_by_block[b] = sold_by_block.get(b, 0) + 1
    return sold_by_type, total_by_type, sold_by_block, unmatched


def note_for(sold_by_block, prefix="Latest sales"):
    """'Latest sales - Block A: 187, Block B: 104'"""
    if not sold_by_block:
        return ""
    parts = [f"Block {b}: {n}" for b, n in sorted(sold_by_block.items())]
    return f"{prefix} - " + ", ".join(parts)
