'use client';

import { Suspense, useEffect, useState, type FormEvent } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import GraphVisualization from '@/components/GraphVisualization';
import AskPanel from '@/components/AskPanel';
import AuthGuard, { useAuthUser } from '@/components/AuthGuard';
import { EmptyState, ErrorState, LoadingState } from '@/components/AppShell';
import { ApiError, getSubgraph } from '@/lib/api';
import type { SubgraphResult } from '@/lib/types';

const relationFilters = [
  ['prerequisite', '前置关系'],
  ['implements', '实现关系'],
  ['contrast', '对比关系'],
  ['boundary', '边界关系'],
] as const;
const evidenceFilters = [
  ['已核验', '已核验'],
  ['部分定位', '部分定位'],
  ['待补充', '待补充'],
] as const;

function GraphContent() {
  const user = useAuthUser();
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryString = searchParams.toString();
  const [result, setResult] = useState<SubgraphResult | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [courseCode, setCourseCode] = useState('');
  const [keyword, setKeyword] = useState('');
  const [hops, setHops] = useState('1');
  const [relations, setRelations] = useState<string[]>([]);
  const [evidenceStatuses, setEvidenceStatuses] = useState<string[]>([]);

  useEffect(() => {
    const params = new URLSearchParams(queryString);
    setCourseCode(params.get('course_code') || '');
    setKeyword(params.get('q') || '');
    setHops(params.get('hops') || '1');
    setRelations(params.getAll('relation_type'));
    setEvidenceStatuses(params.getAll('evidence_status'));
  }, [queryString]);

  useEffect(() => {
    if (!user) return;
    let active = true;
    setLoading(true);
    setError('');
    getSubgraph(new URLSearchParams(queryString))
      .then((data) => { if (active) setResult(data); })
      .catch((reason) => { if (active) setError(reason instanceof ApiError ? reason.message : '网络错误，请稍后重试'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [queryString, user]);

  function toggle(setter: (values: string[]) => void, values: string[], value: string) {
    setter(values.includes(value) ? values.filter((item) => item !== value) : [...values, value]);
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const params = new URLSearchParams();
    const cleanKeyword = keyword.trim();
    if (courseCode) params.set('course_code', courseCode);
    if (cleanKeyword) params.set('q', cleanKeyword);
    if (courseCode || cleanKeyword) params.set('hops', hops);
    relations.forEach((value) => params.append('relation_type', value));
    evidenceStatuses.forEach((value) => params.append('evidence_status', value));
    const query = params.toString();
    router.push(query ? `/graph/?${query}` : '/graph/');
  }

  return (
    <>
      <div className="page-heading">
        <div><p className="eyebrow-muted">KNOWLEDGE GRAPH</p><h1>跨课程知识图谱</h1><p>从课程、关键词和关系证据开始探索概念连接。</p></div>
      </div>
      <section className="panel">
        <form onSubmit={handleSubmit}>
          <div className="form-grid">
            <label className="field"><span>课程</span><select value={courseCode} onChange={(event) => setCourseCode(event.target.value)}><option value="">全部课程</option><option value="DS">数据结构</option><option value="CO">计算机组成原理</option><option value="OS">操作系统</option><option value="CN">计算机网络</option></select></label>
            <label className="field"><span>搜索节点</span><input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="例如：TLB" maxLength={100} /></label>
            <label className="field"><span>关系跳数</span><select value={hops} onChange={(event) => setHops(event.target.value)}><option value="1">1 跳</option><option value="2">2 跳</option></select></label>
            <button className="button primary" type="submit">查询图谱</button>
          </div>
          <div className="filter-row"><span className="muted">关系类型</span><div className="filter-options">{relationFilters.map(([value, label]) => <label key={value}><input type="checkbox" checked={relations.includes(value)} onChange={() => toggle(setRelations, relations, value)} />{label}</label>)}</div></div>
          <div className="filter-row"><span className="muted">证据状态</span><div className="filter-options">{evidenceFilters.map(([value, label]) => <label key={value}><input type="checkbox" checked={evidenceStatuses.includes(value)} onChange={() => toggle(setEvidenceStatuses, evidenceStatuses, value)} />{label}</label>)}</div></div>
        </form>
      </section>
      <AskPanel />
      {loading && <LoadingState label="正在读取图谱数据…" />}
      {!loading && error && <ErrorState message={error} onRetry={() => window.location.reload()} />}
      {!loading && !error && result && <>
        <section className="panel" style={{ marginTop: 20 }}>
          <div className="section-heading"><h2>图谱视图</h2><div className="graph-legend"><span><i className="legend-dot" />节点</span><span>{result.meta.node_count} 个节点</span><span>{result.meta.edge_count} 条关系</span>{result.meta.truncated && <span className="status-badge warn">结果已截断</span>}</div></div>
          {result.nodes.length ? <GraphVisualization nodes={result.nodes} edges={result.edges} /> : <EmptyState title="没有找到匹配节点" detail="可以调整课程、关键词或关系过滤条件。" />}
          <div className="meta-strip"><span className="meta-pill">模式：{result.meta.mode}</span><span className="meta-pill">跳数：{result.meta.applied_hops}</span><span className="meta-pill checksum">种子：{result.meta.seed_checksum || '暂无'}</span></div>
        </section>
        {!!result.edges.length && <section className="panel" style={{ marginTop: 20 }}><h2>关系清单</h2><div className="edge-list">{result.edges.map((edge) => <a className="edge-card" href={`/edge/?id=${encodeURIComponent(edge.edge_id)}`} key={edge.edge_id}><strong>{edge.source_title} → {edge.target_title}</strong><small>{edge.display_label} · {edge.evidence_status}</small></a>)}</div></section>}
      </>}
    </>
  );
}

export default function GraphPage() {
  return <Suspense fallback={<LoadingState />}><AuthGuard><GraphContent /></AuthGuard></Suspense>;
}
