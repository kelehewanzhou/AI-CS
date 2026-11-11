'use client';

import { Suspense, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { v4 as uuidv4 } from 'uuid';
import AuthGuard, { useAuthUser } from '@/components/AuthGuard';
import { EmptyState, ErrorState, LoadingState } from '@/components/AppShell';
import { ApiError, listAttempts, listExercises, recordLearningEvent, submitAttempt } from '@/lib/api';
import type { AttemptView, Exercise } from '@/lib/types';

function formatDate(value: string) {
  return new Date(value).toLocaleString('zh-CN', { dateStyle: 'medium', timeStyle: 'short' });
}

function ExerciseContent() {
  const user = useAuthUser();
  const searchParams = useSearchParams();
  const questionId = searchParams.get('id');
  const nodeId = searchParams.get('node_id');
  const [items, setItems] = useState<Exercise[]>([]);
  const [exercise, setExercise] = useState<Exercise | null>(null);
  const [answer, setAnswer] = useState<unknown>(null);
  const [submissionId, setSubmissionId] = useState<string | null>(null);
  const [result, setResult] = useState<AttemptView | null>(null);
  const [history, setHistory] = useState<AttemptView[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const startedQuestions = useRef(new Set<string>());

  useEffect(() => {
    if (!user) return;
    let active = true;
    setLoading(true);
    setError('');
    const params = new URLSearchParams({ limit: '20', offset: '0' });
    if (questionId) params.set('question_id', questionId);
    if (nodeId) params.set('node_id', nodeId);
    listExercises(params).then((data) => {
      if (!active) return;
      setItems(data.items);
      setExercise(data.items[0] || null);
    }).catch((reason) => { if (active) setError(reason instanceof ApiError ? reason.message : '网络错误，请稍后重试'); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [nodeId, questionId, user]);

  useEffect(() => {
    if (!exercise) return;
    setAnswer(null);
    setResult(null);
    setSubmissionId(uuidv4());
    if (!startedQuestions.current.has(exercise.question_id)) {
      startedQuestions.current.add(exercise.question_id);
      void recordLearningEvent('start_exercise', 'exercise', exercise.question_id).catch(() => undefined);
    }
    let active = true;
    listAttempts(exercise.question_id).then((data) => { if (active) setHistory(data.items); }).catch(() => undefined);
    return () => { active = false; };
  }, [exercise]);

  async function handleSubmit() {
    if (!exercise || submissionId === null || answer === null || answer === '') return;
    setSubmitting(true);
    setError('');
    try {
      const data = await submitAttempt({ question_id: exercise.question_id, answer, client_submission_id: submissionId });
      setResult(data);
      setSubmissionId(uuidv4());
      const refreshed = await listAttempts(exercise.question_id);
      setHistory(refreshed.items);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : '网络错误，请保持当前答案后重试');
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <LoadingState label="正在加载习题…" />;
  if (error && !exercise) return <ErrorState message={error} />;
  if (!exercise) return <EmptyState title="没有找到习题" detail={nodeId ? '该节点当前没有可用练习。' : '请通过题目编号或节点进入练习。'} />;

  return <>
    <div className="page-heading"><div><p className="eyebrow-muted">PRACTICE ROOM</p><h1>习题练习</h1><p>{nodeId ? `节点 ${nodeId} 的练习` : '通过答题检验你的理解。'}</p></div>{items.length > 1 && <label className="field" style={{ minWidth: 220 }}><span>选择题目</span><select value={exercise.question_id} onChange={(event) => setExercise(items.find((item) => item.question_id === event.target.value) || null)}>{items.map((item) => <option key={item.question_id} value={item.question_id}>{item.question_id} · {item.content.slice(0, 22)}</option>)}</select></label>}</div>
    <div className="content-grid two-column">
      <section className="exercise-card">
        <div className="question-number">{exercise.question_id} · 难度 {exercise.difficulty}</div>
        <div className="question-content">{exercise.content}</div>
        {exercise.type === 'choice' && exercise.options && <div className="choice-list">{exercise.options.map((option) => <label className="choice-option" key={option.key}><input type="radio" name="answer" checked={answer === option.key} onChange={() => setAnswer(option.key)} /> <span><strong>{option.key}.</strong> {option.text}</span></label>)}</div>}
        {exercise.type === 'judge' && <div className="choice-list"><label className="choice-option"><input type="radio" name="answer" checked={answer === true} onChange={() => setAnswer(true)} />正确</label><label className="choice-option"><input type="radio" name="answer" checked={answer === false} onChange={() => setAnswer(false)} />错误</label></div>}
        {exercise.type !== 'choice' && exercise.type !== 'judge' && <textarea className="answer-textarea" value={typeof answer === 'string' ? answer : ''} onChange={(event) => setAnswer(event.target.value)} placeholder="请输入你的答案" />}
        {error && <div className="form-error" style={{ marginTop: 16 }} role="alert">{error}</div>}
        <div className="filter-row"><span className="muted">每次主动提交使用新的客户端编号</span><button className="button primary" onClick={() => void handleSubmit()} disabled={submitting || answer === null || answer === ''}>{submitting ? '提交中…' : '提交答案'}</button></div>
        {result && <div className={`result-box ${result.is_correct ? 'correct' : 'wrong'}`}><strong>{result.is_correct ? '本次回答正确' : '本次回答未正确'}</strong><div>{result.feedback}</div></div>}
      </section>
      <section className="panel"><div className="section-heading"><h2>答题历史</h2><span className="muted">{history.length} 条</span></div>{history.length ? <div className="history-list">{history.map((attempt) => <div className="history-item" key={attempt.attempt_id}><div className="history-main"><strong>{attempt.is_correct ? '回答正确' : '回答错误'} · {attempt.is_evaluation ? '评估题' : '练习题'}</strong><small>{formatDate(attempt.submitted_at)} · 答案：{String(attempt.answer)}</small></div><span className={attempt.is_correct ? 'correct-text' : 'wrong-text'}>{attempt.is_correct ? '正确' : '错误'}</span></div>)}</div> : <EmptyState title="暂无答题记录" detail="提交第一份答案后会显示在这里。" />}</section>
    </div>
  </>;
}

export default function ExercisePage() {
  return <Suspense fallback={<LoadingState />}><AuthGuard><ExerciseContent /></AuthGuard></Suspense>;
}
