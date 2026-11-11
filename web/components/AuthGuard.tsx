'use client';

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import AppShell, { LoadingState } from './AppShell';
import { getCurrentUser } from '@/lib/auth';
import type { User } from '@/lib/types';

const AuthContext = createContext<User | null>(null);

export function useAuthUser(): User | null {
  return useContext(AuthContext);
}

export default function AuthGuard({ children, allowInitialPasswordChange = false }: {
  children: ReactNode;
  allowInitialPasswordChange?: boolean;
}) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    getCurrentUser().then((currentUser) => {
      if (!active) return;
      if (!currentUser) {
        window.location.replace('/login/');
        return;
      }
      if (currentUser.must_change_password && !allowInitialPasswordChange) {
        window.location.replace('/change-password/');
        return;
      }
      setUser(currentUser);
      setLoading(false);
    });
    return () => { active = false; };
  }, [allowInitialPasswordChange]);

  if (loading || !user) return <LoadingState label="正在恢复登录身份…" />;
  if (allowInitialPasswordChange && user.must_change_password) {
    return <AuthContext.Provider value={user}>{children}</AuthContext.Provider>;
  }
  return (
    <AuthContext.Provider value={user}>
      <AppShell user={user}>{children}</AppShell>
    </AuthContext.Provider>
  );
}
