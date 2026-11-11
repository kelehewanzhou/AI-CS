'use client';

import Link from 'next/link';
import { useRef, useState, type FormEvent } from 'react';
import { ApiError, askQuestion } from '@/lib/api';
import type { QAResponse } from '@/lib/types';

const reasonLabels: Record<NonNullable<QAResponse['reason']>, string> = {
  no_match: '未匹配到知识点',
  too_many_nodes: '涉及知识点过多',
  ambiguous_relation: '请明确一种关系类型',
  no_direct_relation: '未记录所询直接关系',
};

const statusLabels: Record<QAResponse['status'], string> = {
  answered: '已回答',
  not_covered: '暂未覆盖',
  insufficient_evidence: '证据不足',
};

export default function AskPanel() {
  const [question, setQuestion] = useState('');
  const [result, setResult] = useState<QAResponse | null>(null);
  const [error, setError] = useState('');
  const [requestId, setRequestId] = useState('');
  const [loading, setLoading] = useState(false);
  const inFlight = useRef(false);

  async function handleAsk(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cleanQuestion = question.trim();
    if (inFlight.current) return;
    if (!cleanQuestion || Array.from(cleanQuestion).length > 500) {
      setResult(null);
      setRequestId('');
      setError('请输入1—500字的问题。');
      return;
    }

    inFlight.current = true;
    setLoading(true);
    setError('');
    setRequestId('');
    setResult(null);
    try {
      setResult(await askQuestion(cleanQuestion));
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : '问答服务暂时不可用，请稍后重试。');
      if (reason instanceof ApiError) setRequestId(reason.requestId || '');
    } finally {
      inFlight.current = false;
      setLoading(false);
    }
  }

  return (
    <section className="panel ask-panel" aria-labelledby="ask-heading">
      <div className="section-heading">
        <h2 id="ask-heading">知识问答</h2>
        <span className="muted">每次询问一至两个知识点</span>
      </div>
      <form onSubmit={handleAsk} aria-busy={loading}>
        <label className="field" htmlFor="ask-question">
          <span>你的问题</span>
          <textarea
            id="ask-question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="例如：什么是TLB？或：TLB和虚拟内存是什么关系？"
            rows={3}
            maxLength={500}
            disabled={loading}
            aria-describedby="ask-hint"
          />
        </label>
        <div className="ask-actions">
          <small id="ask-hint" className="muted">请勿输入个人信息。回答依据当前图谱中已核验的关系证据。</small>
          <button className="button primary" type="submit" disabled={loading || !question.trim()}>
            {loading ? '查询中…' : '提问'}
          </button>
        </div>
      </form>
      <div aria-live="polite" aria-atomic="true">
        {loading && <p className="muted" role="status">正在检索知识点和关系证据…</p>}
        {error && <div className="form-error ask-error" role="alert">
          <strong>提问失败</strong><p>{error}</p>
          {requestId && <small className="checksum">请求编号：{requestId}</small>}
        </div>}
        {result && <div className={`ask-answer ${result.status}`}>
          <div className="section-heading">
            <h3>{statusLabels[result.status]}</h3>
            {result.uncertainty_flag && <span className="status-badge warn">当前无法提供可靠回答</span>}
          </div>
          <p className="ask-answer-text">{result.answer}</p>
          {result.reason && <p className="muted">原因：{reasonLabels[result.reason]}</p>}
          {result.boundary_note && <p className="ask-boundary">说明：{result.boundary_note}</p>}
          {result.status === 'answered' && <div className="ask-references">
            <div><span className="muted">引用节点</span>{result.used_node_ids.map((id) =>
              <Link className="tag" key={id} href={`/node/?id=${encodeURIComponent(id)}`}>{id}</Link>,
            )}</div>
            <div><span className="muted">引用关系</span>{result.used_edge_ids.map((id) =>
              <Link className="tag" key={id} href={`/edge/?id=${encodeURIComponent(id)}`}>{id}</Link>,
            )}</div>
          </div>}
        </div>}
      </div>
    </section>
  );
}
