import Link from 'next/link';

export default function HomePage() {
  return (
    <main className="landing-page">
      <div className="landing-card">
        <p className="eyebrow">AI · LEARNING GRAPH</p>
        <h1>AI跨课程知识图谱学习系统</h1>
        <p className="landing-copy">
          连接课程概念、关系证据与练习记录，帮助你沿着知识结构完成学习。
        </p>
        <div className="landing-actions">
          <Link className="button primary" href="/login/">进入系统</Link>
          <Link className="button secondary" href="/graph/">查看图谱</Link>
        </div>
      </div>
    </main>
  );
}
