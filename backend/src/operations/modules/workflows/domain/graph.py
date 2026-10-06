"""Industry-neutral graph and approval invariants; no user-authored execution."""

from collections import defaultdict
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

type NodeKind = Literal["start", "review", "approval", "decision", "notify", "end"]
type ApprovalMode = Literal["one", "all", "quorum", "sequential"]


@dataclass(frozen=True)
class Node:
    key: str
    kind: NodeKind
    return_to: str | None = None


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    outcome: Literal["continue", "true", "false"] = "continue"


def validate_graph(nodes: tuple[Node, ...], edges: tuple[Edge, ...]) -> str:
    if not 2 <= len(nodes) <= 100 or not 1 <= len(edges) <= 200:
        raise ValueError("workflow_graph_limit")
    by_key = {node.key: node for node in nodes}
    if len(by_key) != len(nodes):
        raise ValueError("duplicate_workflow_node")
    starts = [node.key for node in nodes if node.kind == "start"]
    if len(starts) != 1 or not any(node.kind == "end" for node in nodes):
        raise ValueError("workflow_requires_start_and_end")
    outgoing: dict[str, list[Edge]] = defaultdict(list)
    incoming: dict[str, list[Edge]] = defaultdict(list)
    for edge in edges:
        if edge.source not in by_key or edge.target not in by_key:
            raise ValueError("unknown_workflow_node")
        outgoing[edge.source].append(edge)
        incoming[edge.target].append(edge)
    for node in nodes:
        outcomes = [edge.outcome for edge in outgoing[node.key]]
        expected = (
            []
            if node.kind == "end"
            else (["false", "true"] if node.kind == "decision" else ["continue"])
        )
        if sorted(outcomes) != expected:
            raise ValueError("invalid_workflow_transitions")
        if node.kind == "start" and incoming[node.key]:
            raise ValueError("workflow_start_has_incoming_edge")
        if node.return_to is not None:
            if node.kind not in {"review", "approval"}:
                raise ValueError("workflow_return_requires_human_node")
            if node.return_to != "submitter" and (
                node.return_to not in by_key
                or by_key[node.return_to].kind not in {"review", "approval"}
                or node.return_to == node.key
            ):
                raise ValueError("invalid_workflow_return_target")
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(key: str) -> None:
        if key in visiting:
            raise ValueError("workflow_forward_cycle")
        if key in visited:
            return
        visiting.add(key)
        for edge in outgoing[key]:
            visit(edge.target)
        visiting.remove(key)
        visited.add(key)

    visit(starts[0])
    if visited != set(by_key):
        raise ValueError("unreachable_workflow_node")
    return starts[0]


def eligible_approvers(candidates: tuple[UUID, ...], submitter: UUID) -> tuple[UUID, ...]:
    """Preserve assignment order for sequential policies; exclude the submitter."""
    return tuple(dict.fromkeys(user for user in candidates if user != submitter))


def approval_complete(
    mode: ApprovalMode,
    recipients: tuple[UUID, ...],
    approved: frozenset[UUID],
    quorum: int | None = None,
) -> bool:
    if not recipients or len(set(recipients)) != len(recipients):
        raise ValueError("invalid_approval_recipients")
    if not approved.issubset(recipients):
        raise ValueError("approval_actor_not_assigned")
    if mode == "quorum":
        if quorum is None or not 1 <= quorum <= len(recipients):
            raise ValueError("invalid_approval_quorum")
        return len(approved) >= quorum
    if quorum is not None:
        raise ValueError("quorum_requires_quorum_policy")
    if mode == "sequential":
        if approved != frozenset(recipients[: len(approved)]):
            raise ValueError("approval_out_of_sequence")
        return len(approved) == len(recipients)
    return bool(approved) if mode == "one" else len(approved) == len(recipients)


def require_next_approver(
    mode: ApprovalMode, recipients: tuple[UUID, ...], approved: frozenset[UUID], actor: UUID
) -> None:
    if actor not in recipients:
        raise ValueError("approval_actor_not_assigned")
    if actor in approved:
        raise ValueError("approval_already_recorded")
    if mode == "sequential" and (
        len(approved) >= len(recipients) or recipients[len(approved)] != actor
    ):
        raise ValueError("approval_out_of_sequence")
