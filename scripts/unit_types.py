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


OTHER = "Other"


def block_of(unit):
    """The block/tower prefix, used for the Remarks note.

    More forgiving than split() in one way and just as strict in another.

    Forgiving: TEDUH numbers units like "A-08-03A", where the unit segment is
    not a plain number. That is still block A, so the segments after the prefix
    no longer have to parse as integers.

    Strict: the number must have three segments. Single-tower projects are
    numbered FLOOR-UNIT ("9-1", "10-3A"), where the prefix is a floor, not a
    block. Those projects have no blocks to report, so they return None.
    """
    parts = str(unit).strip().upper().split("-")
    if len(parts) < 3:
        return None
    head = parts[0].strip()
    return head or None


def block_counts(units):
    """units: iterable of (unit_number, is_sold) -> {block: sold count}.

    Every sold unit is counted exactly once; anything with no readable prefix
    lands under OTHER so the note always adds up to the total sold.
    """
    counts = {}
    for unit, is_sold in units:
        if not is_sold:
            continue
        b = block_of(unit) or OTHER
        counts[b] = counts.get(b, 0) + 1
    return counts


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
            b = block_of(unit) or OTHER
            sold_by_block[b] = sold_by_block.get(b, 0) + 1
    return sold_by_type, total_by_type, sold_by_block, unmatched


def note_for(sold_by_block, prefix="Latest sales"):
    """'Latest sales - Block A: 187, Block B: 104'"""
    if not sold_by_block:
        return ""
    named = sorted((b, n) for b, n in sold_by_block.items() if b != OTHER)
    if not named:
        return ""          # single-tower project: no blocks, so nothing to break down
    parts = [f"Block {b}: {n}" for b, n in named]
    if sold_by_block.get(OTHER):
        parts.append(f"{OTHER}: {sold_by_block[OTHER]}")
    return f"{prefix} - " + ", ".join(parts)
