'use client';

import { useEffect, useState } from 'react';
import AuthGuard, { useAuthUser } from '@/components/AuthGuard';
import { ErrorState, LoadingState } from '@/components/AppShell';
import { ApiError, getContentSummary } from '@/lib/api';
import type { ContentSummary } from '@/lib/types';

const countLabels: Record<string, string> = { courses: '课程', nodes: '节点', edges: '关系', exercises: '习题' };
const evidenceLabels: Record<string, string> = { verified: '已核验', partial: '部分定位', pending: '待补充' };

function AcceptanceContent() {
  const user = useAuthUser();
  const [summary, setSummary] = useState<ContentSummary | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user) return;
    let active = true;
    getContentSummary().then((data) => { if (active) setSummary(data); }).catch((reason) => { if (active) setError(reason instanceof ApiError ? `${reason.message}${reason.status === 403 ? '（教师账号才可以查看内容摘要）' : ''}` : '网络错误，请稍后重试'); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [user]);

  if (loading) return <LoadingState label="正在读取内容摘要…" />;
  if (error) return <div className="access-denied"><h1>暂时无法查看验收摘要</h1><ErrorState message={error} /></div>;
  if (!summary) return <ErrorState message="未返回内容摘要" />;
  return <>
    <div className="page-heading"><div><p className="eyebrow-muted">TEACHER ACCEPTANCE</p><h1>教师验收</h1><p>检查当前种子内容的范围、数量和证据覆盖情况。</p></div><span className="status-badge">当前种子</span></div>
    <section className="panel"><h2>内容数量</h2><div className="summary-grid">{Object.entries(countLabels).map(([key, label]) => <div className="summary-card" key={key}><span>{label}</span><strong>{summary.counts[key] ?? 0}</strong></div>)}</div></section>
    <div className="content-grid two-column" style={{ marginTop: 20 }}><section className="panel"><h2>证据分布</h2><div className="summary-grid">{Object.entries(evidenceLabels).map(([key, label]) => <div className="summary-card" key={key}><span>{label}</span><strong>{summary.edge_evidence_counts[key] ?? 0}</strong></div>)}</div></section><section className="panel"><h2>导入信息</h2><dl className="kv-list"><div><dt>运行编号</dt><dd>{summary.last_import.run_id}</dd></div><div><dt>完成时间</dt><dd>{new Date(summary.last_import.finished_at).toLocaleString('zh-CN')}</dd></div><div><dt>种子校验和</dt><dd className="checksum">{summary.seed_checksum}</dd></div></dl></section></div>
  </>;
}

export default function TeacherAcceptancePage() {
  return <AuthGuard><AcceptanceContent /></AuthGuard>;
}
