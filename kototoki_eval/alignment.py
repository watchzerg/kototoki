"""Exact Levenshtein alignment with adaptive bands and ambiguity tracking."""

from array import array
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Alignment:
    substitutions: int
    deletions: int
    insertions: int
    mapping: tuple[int | None, ...]
    ambiguous: frozenset[int]
    distance: int
    _traces: list[tuple[int, bytearray]] = field(default_factory=list, repr=False, compare=False)
    _states: tuple[tuple[int, int], ...] = field(default=(), repr=False, compare=False)
    _rows: dict[int, tuple[int, ...]] = field(default_factory=dict, repr=False, compare=False)

    def span_boundary_invariant(self, start: int, end: int) -> tuple[int, int] | None:
        """Return fixed endpoints iff EVERY optimal path maps the complete span."""
        if not 0 <= start < end <= len(self.mapping):
            raise ValueError("Span must be a nonempty reference range")
        if not self._traces:
            values = self.mapping[start:end]
            return (values[0], values[-1]) if all(v is not None for v in values) else None
        first: set[int] = set()
        last: set[int] = set()
        for i in range(start + 1, end + 1):
            for j in self._rows.get(i, ()):
                direction = self._traces[i][1][j - self._traces[i][0]]
                if direction & 2:
                    return None
                if direction & 1:
                    if i == start + 1:
                        first.add(j - 1)
                    if i == end:
                        last.add(j - 1)
        return (next(iter(first)), next(iter(last))) if len(first) == len(last) == 1 else None

    def span_candidate_positions(self, start: int, end: int) -> frozenset[int]:
        """All candidate chars selected by any optimal path for this span."""
        if not self._traces:
            return frozenset(value for value in self.mapping[start:end] if value is not None)
        return frozenset(j - 1 for i in range(start + 1, end + 1) for j in self._rows.get(i, ())
                         if self._traces[i][1][j - self._traces[i][0]] & 1)

    def span_has_stable_anchor(self, start: int, end: int,
                               exact_match: Callable[[int, int], bool]) -> bool:
        """Require at least one exact character anchor on EVERY optimal path."""
        if not self._traces:
            return any(value is not None and exact_match(i, value)
                       for i, value in enumerate(self.mapping[start:end], start))
        pending = [(end, j) for j in self._rows.get(end, ())]
        seen: set[tuple[int, int]] = set()
        while pending:
            i, j = pending.pop()
            if (i, j) in seen:
                continue
            seen.add((i, j))
            if i == start:
                return False
            direction = self._traces[i][1][j - self._traces[i][0]]
            if direction & 1 and not exact_match(i - 1, j - 1):
                pending.append((i - 1, j - 1))
            if direction & 2:
                pending.append((i - 1, j))
            if direction & 4:
                pending.append((i, j - 1))
        return True

    def complete_possible(self, start: int, end: int) -> bool:
        """Whether any globally optimal path keeps every char of this span.

        This is joint path feasibility, not independent per-character guesses.
        It prevents definitely incomplete repeated text from inflating upper bounds.
        """
        if not self._traces:
            return all(v is not None for v in self.mapping[start:end])
        possible = {self._states[0]}
        for i, j in self._states:
            if (i, j) not in possible:
                continue
            if not i and not j:
                return True
            direction = self._traces[i][1][j - self._traces[i][0]]
            if direction & 1:
                possible.add((i - 1, j - 1))
            if direction & 2 and not start <= i - 1 < end:
                possible.add((i - 1, j))
            if direction & 4:
                possible.add((i, j - 1))
        return (0, 0) in possible

    def possible_span_bounds(self, start: int, end: int,
                             allowed_positions: set[int] | None = None,
                             exact_match: Callable[[int, int], bool] | None = None,
                             chronological: Callable[[int, int], bool] | None = None) -> set[tuple[int, int]]:
        """Joint first/last candidate positions on complete optimal span paths."""
        if not self._traces:
            positions = self.mapping[start:end]
            return ({(positions[0], positions[-1])}
                    if positions and all(v is not None and (allowed_positions is None or v in allowed_positions)
                                         for v in positions)
                    and (exact_match is None or any(exact_match(r, h) for r, h in enumerate(positions, start)))
                    and (chronological is None or all(chronological(left, right) for left, right in zip(positions, positions[1:])))
                    else set())
        pending: list[tuple[int, int, int, int, bool]] = []
        for j in self._rows.get(end, ()):
            i = end
            if (self._traces[i][1][j - self._traces[i][0]] & 1
                    and (allowed_positions is None or j - 1 in allowed_positions)):
                pending.append((i - 1, j - 1, j - 1, j - 1,
                                exact_match is None or exact_match(i - 1, j - 1)))
        seen: set[tuple[int, int, int, int, bool]] = set()
        bounds: set[tuple[int, int]] = set()
        while pending:
            i, j, last, nearest, anchored = pending.pop()
            if (i, j, last, nearest, anchored) in seen:
                continue
            seen.add((i, j, last, nearest, anchored))
            if i == start:
                if anchored:
                    bounds.add((j, last))
                continue
            direction = self._traces[i][1][j - self._traces[i][0]]
            if (direction & 1 and (allowed_positions is None or j - 1 in allowed_positions)
                    and (chronological is None or chronological(j - 1, nearest))):
                pending.append((i - 1, j - 1, last, j - 1,
                                anchored or exact_match is None or exact_match(i - 1, j - 1)))
            if direction & 4:
                pending.append((i, j - 1, last, nearest, anchored))
        return bounds


def align(reference: str, candidate: str) -> Alignment:
    """Return an exact minimum edit path, plus all uncertain character matches.

    Ties prefer diagonal, deletion, insertion solely for S/D/I accounting.
    Timing never resolves ties. Every optimal path is inspected for ambiguity.
    A band is exact when its optimum is smaller than the band width: any path
    leaving that band would require at least that many insertion/deletion edits.
    """
    n, m = len(reference), len(candidate)
    if not n:
        return Alignment(0, 0, m, (), frozenset(), m)
    if not m:
        return Alignment(0, n, 0, (None,) * n, frozenset(), n)
    band = min(max(n, m), max(32, abs(n - m) + 1))
    infinity = n + m + 1
    while True:
        traces: list[tuple[int, bytearray]] = []
        previous = array("I", range(min(m, band) + 1))
        traces.append((0, bytearray([0] + [4] * (len(previous) - 1))))
        previous_lo = 0
        for i in range(1, n + 1):
            lo, hi = max(0, i - band), min(m, i + band)
            current = array("I")
            directions = bytearray()
            for j in range(lo, hi + 1):
                diagonal = (previous[j - 1 - previous_lo]
                            + (reference[i - 1] != candidate[j - 1])
                            if j and previous_lo <= j - 1 < previous_lo + len(previous)
                            else infinity)
                deletion = (previous[j - previous_lo] + 1
                            if previous_lo <= j < previous_lo + len(previous)
                            else infinity)
                insertion = current[-1] + 1 if j > lo else infinity
                value = min(diagonal, deletion, insertion)
                current.append(value)
                directions.append((1 if diagonal == value else 0)
                                  | (2 if deletion == value else 0)
                                  | (4 if insertion == value else 0))
            traces.append((lo, directions))
            previous, previous_lo = current, lo
        distance = previous[m - previous_lo]
        if distance < band or band == max(n, m):
            break
        band = min(max(n, m), band * 2)

    mapping: list[int | None] = [None] * n
    i, j = n, m
    substitutions = deletions = insertions = 0
    while i or j:
        direction = traces[i][1][j - traces[i][0]]
        if direction & 1:
            mapping[i - 1] = j - 1
            substitutions += reference[i - 1] != candidate[j - 1]
            i, j = i - 1, j - 1
        elif direction & 2:
            deletions += 1
            i -= 1
        else:
            insertions += 1
            j -= 1

    # Traverse the optimal-path DAG once. A reference position is uncertain if
    # any equally good path assigns it to another candidate position or deletes it.
    seen: set[tuple[int, int]] = set()
    pending = [(n, m)]
    ambiguous: set[int] = set()
    while pending:
        i, j = pending.pop()
        if (i, j) in seen or (not i and not j):
            continue
        seen.add((i, j))
        direction = traces[i][1][j - traces[i][0]]
        if direction & 1:
            if mapping[i - 1] != j - 1:
                ambiguous.add(i - 1)
            pending.append((i - 1, j - 1))
        if direction & 2:
            if mapping[i - 1] is not None:
                ambiguous.add(i - 1)
            pending.append((i - 1, j))
        if direction & 4:
            pending.append((i, j - 1))
    states = tuple(sorted(seen | {(0, 0)}, key=lambda ij: ij[0] + ij[1], reverse=True)) if ambiguous else ()
    rows: dict[int, list[int]] = {}
    for i, j in states:
        rows.setdefault(i, []).append(j)
    return Alignment(substitutions, deletions, insertions, tuple(mapping),
                     frozenset(ambiguous), distance, traces if ambiguous else [], states,
                     {i: tuple(values) for i, values in rows.items()})
