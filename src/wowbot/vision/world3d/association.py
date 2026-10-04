"""Dependency-free global minimum-cost bipartite assignment."""
from __future__ import annotations

import math
from collections.abc import Sequence


def linear_sum_assignment(costs: Sequence[Sequence[float]]) -> list[tuple[int, int]]:
    """Return a Hungarian minimum-cost assignment for a rectangular matrix.

    Infinite entries are hard gates and are omitted from the result.  The
    implementation uses the shortest augmenting path form of the Hungarian
    algorithm, keeping World3D tracking independent of the optional SciPy
    package.
    """
    matrix = [list(map(float, row)) for row in costs]
    if not matrix:
        return []
    columns = len(matrix[0])
    if columns == 0:
        return []
    if any(len(row) != columns for row in matrix):
        raise ValueError("assignment cost matrix must be rectangular")

    transposed = len(matrix) > columns
    work = ([list(row) for row in zip(*matrix)] if transposed else matrix)
    rows, columns = len(work), len(work[0])
    finite = [value for row in work for value in row if math.isfinite(value)]
    if not finite:
        return []
    # Hungarian needs finite arithmetic.  A gated edge must remain more
    # expensive than every possible all-finite assignment.
    span = max(1.0, max(abs(value) for value in finite))
    forbidden = span * (rows + columns + 2) + 1.0
    work = [[value if math.isfinite(value) else forbidden for value in row]
            for row in work]

    u = [0.0] * (rows + 1)
    v = [0.0] * (columns + 1)
    matched_row = [0] * (columns + 1)
    predecessor = [0] * (columns + 1)
    for row in range(1, rows + 1):
        matched_row[0] = row
        column = 0
        min_value = [math.inf] * (columns + 1)
        used = [False] * (columns + 1)
        while True:
            used[column] = True
            current_row = matched_row[column]
            delta, next_column = math.inf, 0
            for candidate_column in range(1, columns + 1):
                if used[candidate_column]:
                    continue
                reduced = (work[current_row - 1][candidate_column - 1]
                           - u[current_row] - v[candidate_column])
                if reduced < min_value[candidate_column]:
                    min_value[candidate_column] = reduced
                    predecessor[candidate_column] = column
                if min_value[candidate_column] < delta:
                    delta = min_value[candidate_column]
                    next_column = candidate_column
            for candidate_column in range(columns + 1):
                if used[candidate_column]:
                    u[matched_row[candidate_column]] += delta
                    v[candidate_column] -= delta
                else:
                    min_value[candidate_column] -= delta
            column = next_column
            if matched_row[column] == 0:
                break
        while True:
            next_column = predecessor[column]
            matched_row[column] = matched_row[next_column]
            column = next_column
            if column == 0:
                break

    assignment = []
    for column in range(1, columns + 1):
        if not matched_row[column]:
            continue
        work_row, work_column = matched_row[column] - 1, column - 1
        source_row, source_column = ((work_column, work_row) if transposed
                                     else (work_row, work_column))
        if math.isfinite(matrix[source_row][source_column]):
            assignment.append((source_row, source_column))
    return sorted(assignment)
