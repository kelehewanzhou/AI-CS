'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import type { ReactNode } from 'react';
import { logout } from '@/lib/auth';
import type { User } from '@/lib/types';

export function LoadingState({ label = '正在加载…' }: { label?: string }) {
  return <div className="state-card"><span className="spinner" aria-hidden="true" />{label}</div>;
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="state-card error-state">
      <strong>加载失败</strong>
      <span>{message}</span>
      {onRetry && <button className="button secondary small" onClick={onRetry}>重试</button>}
    </div>
  );
}

export function EmptyState({ title, detail }: { title: string; detail?: string }) {
  return <div className="empty-state"><strong>{title}</strong>{detail && <span>{detail}</span>}</div>;
}

export default function AppShell({ user, children }: { user: User; children: ReactNode }) {
  const pathname = usePathname();
  const navItems = [
    { href: '/graph/', label: '知识图谱' },
    { href: '/learning/', label: '学习记录' },
    ...(user.role === 'teacher' ? [{ href: '/teacher/acceptance/', label: '教师验收' }] : []),
  ];

  return (
    <div className="app-shell">
      <header className="topbar">
        <Link className="brand" href="/graph/">
          <span className="brand-mark">KG</span>
          <span><strong>知识图谱</strong><small>AI Learning Graph</small></span>
        </Link>
        <nav className="topnav" aria-label="主导航">
          {navItems.map((item) => (
            <Link className={pathname === item.href ? 'active' : ''} href={item.href} key={item.href}>{item.label}</Link>
          ))}
        </nav>
        <div className="account-area">
          <span className="user-chip"><span className="avatar">{user.username.slice(0, 1).toUpperCase()}</span>{user.username}<em>{user.role === 'teacher' ? '教师' : '学生'}</em></span>
          <button className="logout-button" onClick={() => void logout()}>退出</button>
        </div>
      </header>
      <main className="page-container">{children}</main>
    </div>
  );
}
