"""Query counts stay bounded while preserving learning and evidence semantics."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import event

from auth.models import User
from exercise.models import Exercise, ExerciseAttempt, ExerciseRelatedNode
from graph.models import KnowledgeEdge, KnowledgeNode
from graph.schemas import SubgraphQuery
from graph.service import GraphService
from learning.models import LearningEvent
from learning.repository import LearningRepository
from learning.rules import LearningRules
from learning.service import LearningService
from test_learning import _seed_learning_content


def measured(engine, action):
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        return action(), len(statements)
    finally:
        event.remove(engine, "before_cursor_execute", record)


def test_learning_batches_twenty_nodes_and_preserves_user_scope(db_session, db_engine):
    _seed_learning_content(db_session)
    nodes = [f"DS{100 + i}" for i in range(20)]
    db_session.add_all(KnowledgeNode(node_id=node_id, course_code="DS", title=node_id,
                                   chapter_scope="test", description="test", aliases=[], scope_tags=[]) for node_id in nodes)
    users = [User(username=name, role="student", password_hash="unused") for name in ("batch_user", "other_user")]
    db_session.add_all(users)
    db_session.flush()
    user_id, other_id = [user.user_id for user in users]
    at = datetime.now(timezone.utc)
    db_session.add_all(ExerciseRelatedNode(question_id="Q001", node_id=node_id) for node_id in nodes)
    db_session.add_all([
        ExerciseAttempt(user_id=user_id, question_id="Q001", client_submission_id=uuid4(), answer="B", is_correct=False, is_evaluation=True, submitted_at=at),
        ExerciseAttempt(user_id=user_id, question_id="Q001", client_submission_id=uuid4(), answer="A", is_correct=True, is_evaluation=False, submitted_at=at),
        ExerciseAttempt(user_id=other_id, question_id="Q001", client_submission_id=uuid4(), answer="A", is_correct=True, is_evaluation=True, submitted_at=at),
        LearningEvent(user_id=user_id, event_type="start_exercise", question_id="Q001"),
        LearningEvent(user_id=other_id, event_type="view_node", node_id="OS03"),
    ])
    db_session.commit()
    service = LearningService(db_session)
    single, small_count = measured(db_engine, lambda: service.get_states(user_id, nodes[:1]))
    states, large_count = measured(db_engine, lambda: service.get_states(user_id, nodes))
    assert small_count == large_count == 5  # one validation plus four input queries
    assert states[0] == single[0]
    assert all(state["evaluation_count"] == 1 and state["total_attempt_count"] == 2
               and state["recent_accuracy"] == 0 and state["has_viewed"] for state in states)
    # Deactivation changes availability, while historical first answers remain.
    db_session.get(Exercise, "Q001").is_active = False
    db_session.commit()
    after = service.get_states(user_id, [nodes[0], "OS03"])
    assert after[0]["available_exercise_count"] == 0 and after[0]["evaluation_count"] == 1
    assert after[1]["state"] == "未学习"


def test_batch_learning_matches_existing_repository_inputs(db_session):
    _seed_learning_content(db_session)
    user = User(username="parity", role="student", password_hash="unused")
    db_session.add(user)
    db_session.flush()
    at = datetime.now(timezone.utc)
    for index, question_id in enumerate(("Q001", "Q002", "Q003", "Q004", "Q005")):
        db_session.add(ExerciseAttempt(user_id=user.user_id, question_id=question_id,
                       client_submission_id=uuid4(), answer="A", is_correct=index % 2 == 0,
                       is_evaluation=True, submitted_at=at))
    db_session.commit()
    repo = LearningRepository(db_session)
    for state in LearningService(db_session).get_states(user.user_id):
        node_id = state["node_id"]
        evaluations = repo.list_evaluations(user.user_id, node_id)
        expected = LearningRules._compute_state(node_id, repo.count_available_exercises(node_id),
                    evaluations, len(evaluations), repo.count_attempts(user.user_id, node_id),
                    repo.has_learning_activity(user.user_id, node_id))
        assert state == expected


def test_graph_queries_are_bounded_and_evidence_ignores_display_filters(db_session, db_engine):
    _seed_learning_content(db_session)
    for index in range(20):
        node_id = f"DS{100 + index}"
        db_session.add(KnowledgeNode(node_id=node_id, course_code="DS", title=node_id,
                       chapter_scope="test", description="test", aliases=[], scope_tags=[]))
        db_session.add(KnowledgeEdge(edge_id=f"E{100 + index}", source_id="DS04", target_id=node_id,
                       relation_type="contrast", mechanism="test", abc_grade="C", boundary_note="",
                       evidence_status="待补充", evidence_summary="test"))
    db_session.commit()
    service = GraphService(db_session)
    result, queries = measured(db_engine, lambda: service.get_subgraph(SubgraphQuery(), ""))
    assert len(result.nodes) == 25 and len(result.edges) == 23
    assert queries == 3
    filtered, filtered_queries = measured(db_engine, lambda: service.get_subgraph(
        SubgraphQuery(node_id="CO03", hops=1, evidence_status=["已核验"]), ""))
    assert filtered_queries == 4
    assert [edge.edge_id for edge in filtered.edges] == ["E001"]
    # OS02 also has pending E002, even though that edge is filtered out.
    assert next(node for node in filtered.nodes if node.node_id == "OS02").evidence_status == "待补充"
