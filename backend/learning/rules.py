"""Deterministic learning-state rules for task 6."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from .repository import LearningRepository


class LearningRules:
    """The only implementation of the P0 learning-state rule table."""

    RULE_VERSION = "p0-first-distinct-v1"

    @staticmethod
    def compute_state(user_id: UUID, node_id: str, db: Session) -> dict:
        repo = LearningRepository(db)
        available_count = repo.count_available_exercises(node_id)
        can_evaluate = available_count >= 3
        evaluations = repo.list_evaluations(user_id, node_id)
        evaluation_count = len(evaluations)
        total_attempts = repo.count_attempts(user_id, node_id)
        has_viewed = repo.has_learning_activity(user_id, node_id)

        if evaluation_count == 0:
            if has_viewed:
                state = "学习中"
                reason = "no_exercises" if available_count == 0 else "viewed_or_started"
            else:
                state = "未学习"
                reason = "no_activity"
            return {
                "node_id": node_id,
                "state": state,
                "reason": reason,
                "has_viewed": bool(has_viewed),
                "total_attempt_count": total_attempts,
                "evaluation_count": 0,
                "recent_window_size": 0,
                "recent_accuracy": None,
                "latest_evaluation_correct": None,
                "available_exercise_count": available_count,
                "can_evaluate_mastery": can_evaluate,
                "rule_version": LearningRules.RULE_VERSION,
            }

        window_size = min(5, evaluation_count)
        recent_evaluations = evaluations[:window_size]
        correct_count = sum(1 for is_correct, _, _ in recent_evaluations if is_correct)
        latest_correct = recent_evaluations[0][0]
        accuracy_meets = correct_count * 5 >= window_size * 4

        if evaluation_count >= 3 and accuracy_meets and latest_correct:
            state = "已掌握"
            reason = "mastery_rule_met"
        else:
            state = "练习中"
            if evaluation_count < 3:
                reason = "insufficient_distinct_questions"
            elif not accuracy_meets:
                reason = "accuracy_below_threshold"
            elif not latest_correct:
                reason = "latest_evaluation_wrong"

        return {
            "node_id": node_id,
            "state": state,
            "reason": reason,
            "has_viewed": bool(has_viewed),
            "total_attempt_count": total_attempts,
            "evaluation_count": evaluation_count,
            "recent_window_size": window_size,
            "recent_accuracy": correct_count / window_size,
            "latest_evaluation_correct": bool(latest_correct),
            "available_exercise_count": available_count,
            "can_evaluate_mastery": can_evaluate,
            "rule_version": LearningRules.RULE_VERSION,
        }


def compute_node_learning_state(user_id: UUID, node_id: str, db: Session) -> dict:
    """Compatibility entry point named by the §3.6 rule contract."""

    return LearningRules.compute_state(user_id, node_id, db)
