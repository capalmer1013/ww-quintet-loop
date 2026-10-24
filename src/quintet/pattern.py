"""The pattern mini-language: nested lists that divide time.

A list divides its span equally among its elements, which are:
- an int k >= 1: palette note k; 0: a rest
- "k+" / "k-": one scale step above / below palette note k
- "k=" / "k+=" / "k-=": the note "k" / "k+" / "k-" again, renewed seamlessly (written by
  generation where a held note outlasts its recording)
- _: hold the previous note (or rest) through this slot
- a list: a nested division of this slot

expand() turns one cycle into Events and tile() repeats it; voice.py edits patterns by leaf path
(leaves, event_paths) and render.py weights notes by their metric accent (accents).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

__all__ = [
    "_",
    "LEADING_HOLD",
    "Event",
    "expand",
    "tile",
    "event_paths",
    "leaves",
    "accents",
    "STEP",
    "palette_index",
    "ACCENT_DB",
]

# A scale step or renewal: palette index, then "+" (step up), "-" (step down), "=" (renew), or a
# step then "=" (renew the stepped note).
STEP = re.compile(r"([1-9][0-9]*)([+-]?=|[+-])")


def palette_index(element: int | str) -> int:
    """The palette note a note element plays or steps from: 3 for 3, "3+", "3-", "3=" and "3-="."""
    return element if isinstance(element, int) else int(STEP.fullmatch(element).group(1))


# Metric accent (dB) by level within a group: its first slot, the group start nearest the middle,
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
LEADING_HOLD = "continue"  # Event index for a leading hold: extends whatever came before the cycle


@dataclass(frozen=True)
class Event:
    """One note or rest, in beats from the start of its cycle (or piece, once tiled)."""

    start: Fraction
    beats: Fraction
    index: int | str | None  # palette index (1-based), a step like "3+", or None for a rest


@dataclass(frozen=True)
class _Leaf:
    path: tuple[int, ...]  # list indices from the top of the pattern down to this leaf
    start: Fraction
    beats: Fraction
    element: object
    accent_db: float


def _where(path: tuple[int, ...]) -> str:
    return "pattern" + "".join(f"[{i}]" for i in path)


def _is_element(node) -> bool:
    return node is _ or (type(node) is int and node >= 0) or (type(node) is str and bool(STEP.fullmatch(node)))


def _walk(pattern: list, span: Fraction) -> list[_Leaf]:
    """Every leaf in time order, holds included. Raises ValueError, naming its path, on a bad element."""
    out: list[_Leaf] = []

    def visit(node, path: tuple[int, ...], start: Fraction, beats: Fraction, db: float) -> None:
        if isinstance(node, list):
            if not node:
                raise ValueError(f"{_where(path)}: empty list is not a pattern element")
            slot = beats / len(node)
            weight = 0.5 ** len(path)
            for i, (child, level) in enumerate(zip(node, _levels(len(node)))):
                visit(child, path + (i,), start + i * slot, slot, db + ACCENT_DB[level] * weight)
        elif _is_element(node):
            out.append(_Leaf(path, start, beats, node, db))
        else:
            raise ValueError(
                f'{_where(path)}: {node!r} is not a pattern element (int >= 0, "3+"/"3-"/"3=", _, or list)'
            )

    visit(pattern, (), Fraction(0), Fraction(span), 0.0)
    return out


def _event_leaves(pattern: list) -> list[_Leaf | None]:
    """The leaf that starts each Event of expand(pattern); None for a leading hold."""
    starts: list[_Leaf | None] = []
    for leaf in _walk(pattern, Fraction(1)):
        if leaf.element is not _:
            starts.append(leaf)
        elif not starts:
            starts.append(None)
    return starts


def _extend_last(events: list[Event], beats: Fraction) -> None:
    last = events[-1]
    events[-1] = Event(last.start, last.beats + beats, last.index)


def _levels(n: int) -> list[int]:
    """Metric level (index into ACCENT_DB) of each of n equal slots.

    Slots fall in groups of 2 (the last a 3 if n is odd): the first slot is strongest, then the
    group start nearest the middle, then the other group starts, then the rest. In a lone group
    of 3 the middle is a touch stronger than the last.
    """
    if n == 3:
        return [0, 2, 3]
    starts = range(0, n - 1, 2)
    levels = [3] * n
    for s in starts[1:]:
        levels[s] = 2
    if len(starts) > 1:
        levels[min(starts[1:], key=lambda s: (abs(s - n / 2), s))] = 1
    levels[0] = 0
    return levels


def expand(pattern: list, span: Fraction) -> list[Event]:
    """One cycle of a pattern as Events tiling [0, span).

    A leading hold yields an Event with index LEADING_HOLD, which tile() merges into the previous
    cycle's last event.
    """
    events: list[Event] = []
    for leaf in _walk(pattern, span):
        if leaf.element is not _:
            events.append(Event(leaf.start, leaf.beats, leaf.element or None))
        elif events:
            _extend_last(events, leaf.beats)
        else:
            events.append(Event(leaf.start, leaf.beats, LEADING_HOLD))
    return events


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
            if e.index == LEADING_HOLD:
                if out:
                    _extend_last(out, e.beats)
                    continue
                e = Event(e.start, e.beats, None)  # nothing to hold at the very start: rest
            out.append(Event(e.start + offset, e.beats, e.index))
    return out


def leaves(pattern: list, span: Fraction) -> list[tuple[tuple[int, ...], Fraction, Fraction, object]]:
    """Every leaf as (index path, start, beats, element), holds included, in time order."""
    return [(leaf.path, leaf.start, leaf.beats, leaf.element) for leaf in _walk(pattern, span)]


def event_paths(pattern: list) -> list[tuple[int, ...] | None]:
    """For each Event of expand(pattern), the index path of the leaf that starts it (None for a
    leading hold, which continues the previous cycle)."""
    return [None if leaf is None else leaf.path for leaf in _event_leaves(pattern)]


def accents(pattern: list) -> list[float]:
    """The metric accent in dB for each Event of expand(pattern): each enclosing slot's ACCENT_DB
    level, halved per level of nesting, summed. A leading hold gets 0."""
    return [0.0 if leaf is None else leaf.accent_db for leaf in _event_leaves(pattern)]
