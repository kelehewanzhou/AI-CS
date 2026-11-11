'use client';

import Link from 'next/link';
import { Suspense, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import AuthGuard, { useAuthUser } from '@/components/AuthGuard';
import { EmptyState, ErrorState, LoadingState } from '@/components/AppShell';
import { ApiError, getNode, recordLearningEvent } from '@/lib/api';
import type { EdgeView, NodeDetail } from '@/lib/types';

function EdgeList({ title, edges }: { title: string; edges: EdgeView[] }) {
  return <section className="panel"><div className="section-heading"><h2>{title}</h2><span className="muted">{edges.length} 条</span></div>{edges.length ? <div className="edge-list">{edges.map((edge) => <Link className="edge-card" href={`/edge/?id=${encodeURIComponent(edge.edge_id)}`} key={edge.edge_id}><strong>{edge.display_label}</strong><small>{edge.source_title} → {edge.target_title} · {edge.evidence_status}</small></Link>)}</div> : <EmptyState title="暂无关系" />}</section>;
}

function NodeContent() {
  const user = useAuthUser();
  const searchParams = useSearchParams();
  const nodeId = searchParams.get('id');
  const [detail, setDetail] = useState<NodeDetail | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const recordedNode = useRef<string | null>(null);

  useEffect(() => {
    if (!user || !nodeId) { setLoading(false); return; }
    let active = true;
    setLoading(true);
    setError('');
    getNode(nodeId)
      .then((data) => {
        if (!active) return;
        setDetail(data);
        if (recordedNode.current !== nodeId) {
          recordedNode.current = nodeId;
          void recordLearningEvent('view_node', 'node', nodeId).catch(() => undefined);
        }
      })
      .catch((reason) => { if (active) setError(reason instanceof ApiError ? reason.message : '网络错误，请稍后重试'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [nodeId, user]);

  if (!nodeId) return <EmptyState title="缺少节点编号" detail="请从图谱中选择一个节点。" />;
  if (loading) return <LoadingState label="正在加载节点详情…" />;
  if (error) return <ErrorState message={error} />;
  if (!detail) return <EmptyState title="没有找到节点" />;
  const { node, learning } = detail;
  return <>
    <div className="page-heading"><div><p className="eyebrow-muted">NODE DETAIL · {node.node_id}</p><div className="detail-title"><div><h1>{node.title}</h1><p>{node.course_code} · {node.chapter_scope}</p></div></div></div><Link className="button secondary" href={`/exercise/?node_id=${encodeURIComponent(node.node_id)}`}>开始练习</Link></div>
    <div className="content-grid two-column">
      <div className="content-grid">
        <section className="panel"><h2>概念描述</h2><p className="detail-copy">{node.description}</p><div className="meta-strip">{node.aliases.map((alias) => <span className="tag" key={alias}>别名：{alias}</span>)}{node.scope_tags.map((tag) => <span className="tag" key={tag}>{tag}</span>)}</div></section>
        <EdgeList title="出向关系" edges={node.outgoing_edges} />
        <EdgeList title="入向关系" edges={node.incoming_edges} />
      </div>
      <aside className="content-grid">
        <section className="panel"><h2>学习状态</h2><dl className="kv-list"><div><dt>当前状态</dt><dd><span className={`status-badge ${learning.state === '已掌握' ? '' : learning.state === '未学习' ? 'gray' : 'warn'}`}>{learning.state}</span></dd></div><div><dt>状态原因</dt><dd>{learning.reason}</dd></div><div><dt>查看过节点</dt><dd>{learning.has_viewed ? '是' : '否'}</dd></div><div><dt>答题次数</dt><dd>{learning.total_attempt_count}</dd></div><div><dt>评估次数</dt><dd>{learning.evaluation_count}</dd></div><div><dt>近期正确率</dt><dd>{learning.recent_accuracy === null ? '暂无' : `${(learning.recent_accuracy * 100).toFixed(0)}%`}</dd></div></dl></section>
        <section className="panel"><h2>证据概览</h2><dl className="kv-list"><div><dt>状态</dt><dd>{node.evidence_overview.status}</dd></div><div><dt>说明</dt><dd>{node.evidence_overview.reason}</dd></div><div><dt>关系证据</dt><dd>{node.evidence_overview.edge_ids.length} 条</dd></div></dl></section>
        <section className="panel"><div className="section-heading"><h2>练习题</h2><span className="status-badge">{detail.exercise_count} 题</span></div><p className="muted">通过练习检验对该节点的理解，并将结果纳入学习状态。</p><Link className="button primary" href={`/exercise/?node_id=${encodeURIComponent(node.node_id)}`}>查看题目</Link></section>
      </aside>
    </div>
  </>;
}

export default function NodePage() {
  return <Suspense fallback={<LoadingState />}><AuthGuard><NodeContent /></AuthGuard></Suspense>;
}
