from uuid import uuid4

import pytest
from operations.modules.workflows.application.contracts import ApprovalPolicy, Assignment
from operations.modules.workflows.domain.graph import (
    Edge,
    Node,
    approval_complete,
    eligible_approvers,
    require_next_approver,
    validate_graph,
)
from pydantic import ValidationError


def test_decisions_and_explicit_returns_do_not_create_forward_cycles() -> None:
    nodes = (
        Node("start", "start"),
        Node("review", "review", "submitter"),
        Node("decision", "decision"),
        Node("approval", "approval", "review"),
        Node("end", "end"),
    )
    edges = (
        Edge("start", "review"),
        Edge("review", "decision"),
        Edge("decision", "approval", "true"),
        Edge("decision", "end", "false"),
        Edge("approval", "end"),
    )
    assert validate_graph(nodes, edges) == "start"
    with pytest.raises(ValueError, match="workflow_forward_cycle"):
        validate_graph(nodes, (*edges[:-1], Edge("approval", "review")))


@pytest.mark.parametrize(
    "nodes,edges,error",
    [
        ((Node("a", "start"), Node("a", "end")), (Edge("a", "a"),), "duplicate"),
        ((Node("a", "start"), Node("b", "end")), (Edge("a", "missing"),), "unknown"),
        (
            (Node("a", "start"), Node("b", "end"), Node("c", "end")),
            (Edge("a", "b"),),
            "unreachable",
        ),
        (
            (Node("a", "start"), Node("b", "decision"), Node("c", "end")),
            (Edge("a", "b"), Edge("b", "c", "true")),
            "invalid_workflow_transitions",
        ),
        (
            (Node("a", "start"), Node("b", "approval", "a"), Node("c", "end")),
            (Edge("a", "b"), Edge("b", "c")),
            "invalid_workflow_return_target",
        ),
    ],
)
def test_invalid_graphs(nodes: tuple[Node, ...], edges: tuple[Edge, ...], error: str) -> None:
    with pytest.raises(ValueError, match=error):
        validate_graph(nodes, edges)


def test_independent_approval_deduplicates_without_reordering() -> None:
    author, first, second = uuid4(), uuid4(), uuid4()
    assert eligible_approvers((first, author, first, second), author) == (first, second)
    assert eligible_approvers((author,), author) == ()
    with pytest.raises(ValueError, match="invalid_approval_recipients"):
        approval_complete("one", (), frozenset())


def test_completion_policies_and_sequential_authority() -> None:
    recipients = (uuid4(), uuid4(), uuid4())
    first = frozenset(recipients[:1])
    assert approval_complete("one", recipients, first)
    assert not approval_complete("all", recipients, first)
    assert not approval_complete("quorum", recipients, first, 2)
    assert approval_complete("quorum", recipients, frozenset(recipients[:2]), 2)
    assert approval_complete("all", recipients, frozenset(recipients))
    assert approval_complete("sequential", recipients, frozenset(recipients))
    require_next_approver("sequential", recipients, first, recipients[1])
    with pytest.raises(ValueError, match="out_of_sequence"):
        require_next_approver("sequential", recipients, first, recipients[2])
    with pytest.raises(ValueError, match="out_of_sequence"):
        approval_complete("sequential", recipients, frozenset({recipients[2]}))
    with pytest.raises(ValueError, match="already_recorded"):
        require_next_approver("all", recipients, first, recipients[0])
    with pytest.raises(ValueError, match="not_assigned"):
        approval_complete("one", recipients, frozenset({uuid4()}))
    with pytest.raises(ValueError, match="invalid_approval_quorum"):
        approval_complete("quorum", recipients, first, 4)


def test_assignment_and_policy_reject_ambiguous_contracts() -> None:
    Assignment(kind="department_role", target_id=uuid4(), role="Approver")
    Assignment(kind="submission_field", field_key="approver")
    with pytest.raises(ValidationError):
        Assignment(kind="user", target_id=uuid4(), role="Approver")
    with pytest.raises(ValidationError):
        Assignment(kind="project_role")
    with pytest.raises(ValidationError):
        ApprovalPolicy(mode="all", quorum=1)
    with pytest.raises(ValidationError):
        ApprovalPolicy(mode="quorum")
