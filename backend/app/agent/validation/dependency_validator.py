"""Dependency graph validation: known references, no self/forward references, no cycles."""

from __future__ import annotations

from uuid import UUID

from app.schemas.plan import PlannedAction


def validate_dependencies(steps: list[PlannedAction]) -> list[str]:
    errors: list[str] = []
    by_id = {s.step_id: s for s in steps}
    graph: dict[UUID, list[UUID]] = {}

    for step in steps:
        graph[step.step_id] = []
        for dep in step.depends_on:
            if dep == step.step_id:
                errors.append(f"Step {step.order} depends on itself.")
                continue
            target = by_id.get(dep)
            if target is None:
                errors.append(f"Step {step.order} depends on an unknown step.")
                continue
            if target.order >= step.order:
                errors.append(f"Step {step.order} depends on a later step ({target.order}); forward dependencies are not supported.")
            graph[step.step_id].append(dep)

    # Cycle detection (iterative DFS, three colours) — independent of ordering rules.
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {node: WHITE for node in graph}
    for start in graph:
        if colour[start] != WHITE:
            continue
        stack: list[tuple[UUID, int]] = [(start, 0)]
        colour[start] = GREY
        while stack:
            node, idx = stack[-1]
            children = graph[node]
            if idx < len(children):
                stack[-1] = (node, idx + 1)
                child = children[idx]
                if colour.get(child) == GREY:
                    errors.append("Plan contains a circular dependency.")
                    return errors
                if colour.get(child) == WHITE:
                    colour[child] = GREY
                    stack.append((child, 0))
            else:
                colour[node] = BLACK
                stack.pop()
    return errors
