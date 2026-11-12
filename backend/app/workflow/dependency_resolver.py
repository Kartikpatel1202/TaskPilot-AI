"""Workflow dependency resolution: topological order with cycle rejection (Phase 5)."""

from __future__ import annotations

from collections import deque
from uuid import UUID


class WorkflowCycleError(ValueError):
    pass


def resolve_order(nodes: list[tuple[UUID, list[UUID]]]) -> list[UUID]:
    """Kahn's algorithm. Unknown dependencies and cycles are rejected (never silently dropped)."""
    ids = [n for n, _ in nodes]
    known = set(ids)
    indegree = {n: 0 for n in ids}
    children: dict[UUID, list[UUID]] = {n: [] for n in ids}
    for node, deps in nodes:
        for dep in deps:
            if dep not in known:
                raise WorkflowCycleError(f"Step depends on an unknown step ({dep}).")
            if dep == node:
                raise WorkflowCycleError("A step cannot depend on itself.")
            indegree[node] += 1
            children[dep].append(node)
    position = {n: i for i, n in enumerate(ids)}
    ready = deque(sorted((n for n in ids if indegree[n] == 0), key=position.__getitem__))
    order: list[UUID] = []
    while ready:
        node = ready.popleft()
        order.append(node)
        for child in sorted(children[node], key=position.__getitem__):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if len(order) != len(ids):
        raise WorkflowCycleError("The workflow has a dependency cycle.")
    return order


def dependents(nodes: list[tuple[UUID, list[UUID]]], failed: UUID) -> set[UUID]:
    """Every step that (transitively) needs `failed` — they are skipped, independent steps still run."""
    out: set[UUID] = set()
    frontier = {failed}
    while frontier:
        nxt = {n for n, deps in nodes if frontier & set(deps) and n not in out}
        out |= nxt
        frontier = nxt
    return out
