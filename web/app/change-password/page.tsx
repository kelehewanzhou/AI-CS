'use client';

import { useState, type FormEvent } from 'react';
import { ApiError } from '@/lib/api';
import { changePassword } from '@/lib/auth';
import AuthGuard, { useAuthUser } from '@/components/AuthGuard';

function ChangePasswordContent() {
  const user = useAuthUser();
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    if (newPassword.length < 12) {
      setError('新密码至少需要12个字符');
      return;
    }
    if (newPassword !== confirmPassword) {
      setError('两次输入的新密码不一致');
      return;
    }
    setPending(true);
    try {
      await changePassword(currentPassword, newPassword);
      window.location.replace('/login/');
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : '网络错误，请稍后重试');
      setPending(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-card">
        <p className="eyebrow">ACCOUNT SECURITY</p>
        <h1>修改初始密码</h1>
        <p>{user?.username}，请设置一个新的登录密码后继续使用系统。</p>
        <form className="login-form" onSubmit={handleSubmit}>
          <label className="field"><span>当前密码</span><input type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} autoComplete="current-password" required /></label>
          <label className="field"><span>新密码</span><input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} autoComplete="new-password" required minLength={12} /></label>
          <label className="field"><span>确认新密码</span><input type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} autoComplete="new-password" required minLength={12} /></label>
          {error && <div className="form-error" role="alert">{error}</div>}
          <button className="button primary" type="submit" disabled={pending}>{pending ? '保存中…' : '保存新密码'}</button>
        </form>
        <div className="form-hint">密码长度为12—128个字符。保存后当前会话会被撤销，请重新登录。</div>
      </section>
    </main>
  );
}

export default function ChangePasswordPage() {
  return <AuthGuard allowInitialPasswordChange><ChangePasswordContent /></AuthGuard>;
}
