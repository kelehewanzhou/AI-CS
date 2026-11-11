'use client';

import { Suspense, useCallback, useEffect, useState } from 'react';
import AuthGuard, { useAuthUser } from '@/components/AuthGuard';
import { EmptyState, ErrorState, LoadingState } from '@/components/AppShell';
import { ApiError, getLearningEvents, getLearningStatus } from '@/lib/api';
import type { LearningEvent, NodeLearningState } from '@/lib/types';

const eventLabels: Record<string, string> = { view_node: '查看节点', view_edge: '查看关系', start_exercise: '开始练习' };

function formatDate(value: string) {
  return new Date(value).toLocaleString('zh-CN', { dateStyle: 'medium', timeStyle: 'short' });
}

function LearningContent() {
  const user = useAuthUser();
  const [events, setEvents] = useState<LearningEvent[]>([]);
  const [statuses, setStatuses] = useState<NodeLearningState[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [eventsLoading, setEventsLoading] = useState(true);
  const [statusLoading, setStatusLoading] = useState(true);
  const [eventsError, setEventsError] = useState('');
  const [statusError, setStatusError] = useState('');

  const loadEvents = useCallback(async (cursor?: string) => {
    setEventsLoading(true);
    setEventsError('');
    try {
      const data = await getLearningEvents(cursor);
      setEvents((current) => cursor ? [...current, ...data.items] : data.items);
      setNextCursor(data.next_cursor);
    } catch (reason) {
      setEventsError(reason instanceof ApiError ? reason.message : '网络错误，请稍后重试');
    } finally { setEventsLoading(false); }
  }, []);

  const loadStatuses = useCallback(async () => {
    setStatusLoading(true);
    setStatusError('');
    try { setStatuses((await getLearningStatus()).items); }
    catch (reason) { setStatusError(reason instanceof ApiError ? reason.message : '网络错误，请稍后重试'); }
    finally { setStatusLoading(false); }
  }, []);

  useEffect(() => { if (user) { void loadEvents(); void loadStatuses(); } }, [loadEvents, loadStatuses, user]);

  return <>
    <div className="page-heading"><div><p className="eyebrow-muted">LEARNING JOURNAL</p><h1>学习记录</h1><p>查看你的浏览轨迹与节点掌握状态。</p></div><button className="button secondary" onClick={() => { void loadEvents(); void loadStatuses(); }}>刷新数据</button></div>
    <div className="content-grid two-column">
      <section className="panel"><div className="section-heading"><h2>事件历史</h2><span className="muted">按时间倒序</span></div>{eventsLoading && !events.length ? <LoadingState label="正在读取事件…" /> : eventsError ? <ErrorState message={eventsError} onRetry={() => void loadEvents()} /> : events.length ? <><div className="event-list">{events.map((event) => <div className="event-item" key={event.event_id}><div className="event-main"><strong>{eventLabels[event.event_type] || event.event_type} · {event.resource_id}</strong><small>{event.resource_type} · {formatDate(event.created_at)}</small></div><span className="meta-pill">#{event.event_id}</span></div>)}</div>{nextCursor && <div className="pager"><button className="button secondary small" onClick={() => void loadEvents(nextCursor)} disabled={eventsLoading}>{eventsLoading ? '加载中…' : '加载更多'}</button></div>}</> : <EmptyState title="暂无学习事件" detail="浏览节点或开始练习后会记录在这里。" />}</section>
      <section className="panel"><div className="section-heading"><h2>节点状态</h2><span className="muted">固定规则计算</span></div>{statusLoading ? <LoadingState label="正在计算状态…" /> : statusError ? <ErrorState message={statusError} onRetry={() => void loadStatuses()} /> : statuses.length ? <div className="status-list">{statuses.map((status) => <div className="status-row" key={status.node_id}><div className="history-main"><strong>{status.node_id}</strong><small>{status.reason} · 评估 {status.evaluation_count} 次</small></div><span className={`status-badge ${status.state === '已掌握' ? '' : status.state === '未学习' ? 'gray' : 'warn'}`}>{status.state}</span></div>)}</div> : <EmptyState title="暂无节点状态" />}</section>
    </div>
  </>;
}

export default function LearningPage() {
  return <Suspense fallback={<LoadingState />}><AuthGuard><LearningContent /></AuthGuard></Suspense>;
}
