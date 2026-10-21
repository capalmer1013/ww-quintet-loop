"""Nested-list patterns: lists divide their span equally; ints index a palette, "3+"/"3-" step off a
palette note by one scale step, 0 rests, _ holds."""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

__all__ = ["_", "Event", "expand", "tile", "event_paths", "leaves", "accents", "STEP", "ACCENT_DB"]

# "3+" / "3-": palette note 3, one scale step up / down; "3=": note 3 again, renewed seamlessly
# (written by generation where a held note outlasts its recording)
STEP = re.compile(r"([1-9][0-9]*)([+=-])")
# metric accent (dB) by level within a group: its first slot, the group start nearest the middle,
# other group starts, everything else. Each level of nesting counts half as much as the one above.
ACCENT_DB = (1.0, 0.6, 0.3, 0.0)


class _Hold:
    """The single hold marker; copying it gives back the same object, so `is _` keeps working."""

    def __repr__(self) -> str:
        return "_"

    def __copy__(self) -> _Hold:
        return self

    def __deepcopy__(self, memo) -> _Hold:
        return self


_ = _Hold()  # hold: extend the previous note (or rest) through this slot
_CONTINUE = "continue"  # an event that extends whatever came before the pattern started


@dataclass(frozen=True)
class Event:
    start: Fraction  # beats
    beats: Fraction
    index: int | str | None  # palette index (1-based), a step like "3+", or None for a rest


def expand(pattern: list, span: Fraction) -> list:
    """One cycle of a pattern as Events tiling [0, span).

    A leading hold yields an Event with index _CONTINUE, which tile() merges into the previous
    cycle's last event.
    """
    leaves: list[tuple[Fraction, Fraction, object]] = []
    _walk(pattern, Fraction(0), Fraction(span), "pattern", leaves)
    events: list[Event] = []
    for start, beats, element in leaves:
        if element is _:
            if events:
                last = events[-1]
                events[-1] = Event(last.start, last.beats + beats, last.index)
            else:
                events.append(Event(start, beats, _CONTINUE))
        else:
            events.append(Event(start, beats, element or None))
    return events


def _walk(node, start: Fraction, span: Fraction, path: str, leaves: list) -> None:
    if isinstance(node, list):
        if not node:
            raise ValueError(f"{path}: empty list is not a pattern element")
        slot = span / len(node)
        for i, child in enumerate(node):
            _walk(child, start + i * slot, slot, f"{path}[{i}]", leaves)
    elif node is _ or (type(node) is int and node >= 0) or (type(node) is str and STEP.fullmatch(node)):
        leaves.append((start, span, node))
    else:
        raise ValueError(f'{path}: {node!r} is not a pattern element (int >= 0, "3+"/"3-"/"3=", _, or list)')


def event_paths(pattern: list) -> list[tuple[int, ...] | None]:
    """For each Event of expand(pattern), the index path of the leaf that starts it (None for a
    leading hold, which continues the previous cycle)."""
    paths: list[tuple[int, ...] | None] = []

    def walk(node, path: tuple[int, ...]) -> None:
        if isinstance(node, list):
            for i, child in enumerate(node):
                walk(child, path + (i,))
        elif node is not _:
            paths.append(path)
        elif not paths:
            paths.append(None)

    walk(pattern, ())
    return paths


def leaves(pattern: list, span: Fraction) -> list[tuple[tuple[int, ...], Fraction, Fraction, object]]:
    """Every leaf as (index path, start, beats, element), holds included, in time order."""
    out = []

    def walk(node, path: tuple[int, ...], start: Fraction, length: Fraction) -> None:
        if isinstance(node, list):
            for i, child in enumerate(node):
                walk(child, path + (i,), start + i * length / len(node), length / len(node))
        else:
            out.append((path, start, length, node))

    walk(pattern, (), Fraction(0), Fraction(span))
    return out


def _levels(n: int) -> list[int]:
    """Metric level (index into ACCENT_DB) of each of n equal slots: groups of 2 (one 3 if n is
    odd); the first slot strongest, the group start nearest the middle next, then other group
    starts, then the rest. In a lone group of 3 the middle is a touch stronger than the last."""
    if n == 1:
        return [0]
    if n == 3:
        return [0, 2, 3]
    groups = [2] * (n // 2)
    if n % 2:
        groups[-1] = 3
    starts = [sum(groups[:i]) for i in range(len(groups))]
    levels = [3] * n
    for s in starts[1:]:
        levels[s] = 2
    if len(starts) > 1:
        levels[min(starts[1:], key=lambda s: (abs(s - n / 2), s))] = 1
    levels[0] = 0
    return levels


def accents(pattern: list) -> list[float]:
    """The metric accent in dB for each Event of expand(pattern): the sum, down the nesting, of
    each enclosing slot's ACCENT_DB level, halved per level of depth."""
    out: list[float] = []

    def walk(node, db: float, depth: int) -> None:
        if isinstance(node, list):
            for child, level in zip(node, _levels(len(node))):
                walk(child, db + ACCENT_DB[level] * 0.5**depth, depth + 1)
        elif node is not _:
            out.append(db)
        elif not out:
            out.append(0.0)  # a leading hold continues the previous cycle

    walk(pattern, 0.0, 0)
    return out


def tile(pattern: list, span: Fraction, total: Fraction) -> list[Event]:
    """Repeat a pattern every `span` beats for `total` beats (a whole number of cycles)."""
    cycles = Fraction(total) / Fraction(span)
    if cycles.denominator != 1:
        raise ValueError(f"total {total} is not a whole number of {span}-beat cycles")
    one = expand(pattern, span)
    out: list[Event] = []
    for c in range(int(cycles)):
        offset = c * Fraction(span)
        for e in one:
            if e.index == _CONTINUE:
                if out:
                    last = out[-1]
                    out[-1] = Event(last.start, last.beats + e.beats, last.index)
                    continue
                e = Event(e.start, e.beats, None)  # nothing to hold at the very start: rest
            out.append(Event(e.start + offset, e.beats, e.index))
    return out
