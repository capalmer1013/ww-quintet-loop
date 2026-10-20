"""Nested-list patterns: lists divide their span equally; ints index a palette, 0 rests, _ holds."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

__all__ = ["_", "Event", "expand", "tile"]


class _Hold:
    def __repr__(self) -> str:
        return "_"


_ = _Hold()  # hold: extend the previous note (or rest) through this slot
_CONTINUE = "continue"  # an event that extends whatever came before the pattern started


@dataclass(frozen=True)
class Event:
    start: Fraction  # beats
    beats: Fraction
    index: int | None  # palette index (1-based), or None for a rest


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
    elif node is _ or (type(node) is int and node >= 0):
        leaves.append((start, span, node))
    else:
        raise ValueError(f"{path}: {node!r} is not a pattern element (int >= 0, _, or list)")


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
