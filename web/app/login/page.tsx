'use client';

import { useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { ApiError } from '@/lib/api';
import { login } from '@/lib/auth';

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setPending(true);
    try {
      const data = await login(username.trim(), password);
      router.replace(data.user.must_change_password ? '/change-password/' : '/graph/');
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : '网络错误，请稍后重试');
      setPending(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-card">
        <Link className="brand" href="/">
          <span className="brand-mark">KG</span>
          <span><strong>知识图谱</strong><small>AI Learning Graph</small></span>
        </Link>
        <h1>欢迎回来</h1>
        <p>登录后继续浏览跨课程知识关系与学习记录。</p>
        <form className="login-form" onSubmit={handleSubmit}>
          <label className="field">
            <span>用户名</span>
            <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required minLength={3} maxLength={64} />
          </label>
          <label className="field">
            <span>密码</span>
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required maxLength={128} />
          </label>
          {error && <div className="form-error" role="alert">{error}</div>}
          <button className="button primary" type="submit" disabled={pending}>{pending ? '登录中…' : '登录'}</button>
        </form>
        <div className="form-hint">首次登录若需要修改初始密码，系统会自动进入改密页面。</div>
      </section>
    </main>
  );
}
