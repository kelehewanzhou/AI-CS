'use client';

import Link from 'next/link';
import { Suspense, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import AuthGuard, { useAuthUser } from '@/components/AuthGuard';
import { EmptyState, ErrorState, LoadingState } from '@/components/AppShell';
import { ApiError, getEdge, recordLearningEvent } from '@/lib/api';
import type { EdgeView } from '@/lib/types';

function EdgeContent() {
  const user = useAuthUser();
  const searchParams = useSearchParams();
  const edgeId = searchParams.get('id');
  const [edge, setEdge] = useState<EdgeView | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const recordedEdge = useRef<string | null>(null);

  useEffect(() => {
    if (!user || !edgeId) { setLoading(false); return; }
    let active = true;
    getEdge(edgeId).then((data) => {
      if (!active) return;
      setEdge(data);
      if (recordedEdge.current !== edgeId) {
        recordedEdge.current = edgeId;
        void recordLearningEvent('view_edge', 'edge', edgeId).catch(() => undefined);
      }
    }).catch((reason) => { if (active) setError(reason instanceof ApiError ? reason.message : '网络错误，请稍后重试'); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [edgeId, user]);

  if (!edgeId) return <EmptyState title="缺少关系编号" detail="请从图谱或节点详情中选择一条关系。" />;
  if (loading) return <LoadingState label="正在加载关系详情…" />;
  if (error) return <ErrorState message={error} />;
  if (!edge) return <EmptyState title="没有找到关系" />;
  return <>
    <div className="page-heading"><div><p className="eyebrow-muted">EDGE DETAIL · {edge.edge_id}</p><h1>{edge.display_label}</h1><p>{edge.relation_type} · 展示方向：{edge.display_mode}</p></div><span className="status-badge">{edge.evidence_status}</span></div>
    <div className="content-grid two-column">
      <section className="panel"><h2>关系端点</h2><div className="edge-list"><Link className="edge-card" href={`/node/?id=${encodeURIComponent(edge.source_id)}`}><strong>起点 · {edge.source_title}</strong><small>{edge.source_id}</small></Link><div className="muted" style={{ textAlign: 'center', padding: 4 }}>↓</div><Link className="edge-card" href={`/node/?id=${encodeURIComponent(edge.target_id)}`}><strong>终点 · {edge.target_title}</strong><small>{edge.target_id}</small></Link></div><h2 style={{ marginTop: 28 }}>作用机制</h2><p className="detail-copy">{edge.mechanism}</p>{edge.boundary_note && <><h3>边界说明</h3><p className="detail-copy">{edge.boundary_note}</p></>}</section>
      <aside className="content-grid"><section className="panel"><h2>证据</h2><dl className="kv-list"><div><dt>证据等级</dt><dd>{edge.abc_grade}</dd></div><div><dt>证据状态</dt><dd>{edge.evidence_status}</dd></div><div><dt>摘要</dt><dd>{edge.evidence_summary}</dd></div></dl>{edge.evidence_detail && <div className="meta-strip">{Object.entries(edge.evidence_detail).map(([key, value]) => <span className="meta-pill" key={key}>{key}：{String(value || '未填写')}</span>)}</div>}</section></aside>
    </div>
  </>;
}

export default function EdgePage() {
  return <Suspense fallback={<LoadingState />}><AuthGuard><EdgeContent /></AuthGuard></Suspense>;
}
