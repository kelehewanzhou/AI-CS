import { apiGet, apiPost } from './api';
import type { User } from './types';

interface AuthResponse {
  user: User;
  expires_at: string | null;
}

export async function getCurrentUser(): Promise<User | null> {
  try {
    const data = await apiGet<AuthResponse>('/auth/me');
    return data.user;
  } catch {
    return null;
  }
}

export function login(username: string, password: string): Promise<AuthResponse> {
  return apiPost<AuthResponse>('/auth/login', { username, password });
}

export function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<{ password_changed: boolean; reauth_required: boolean }> {
  return apiPost('/auth/password', {
    current_password: currentPassword,
    new_password: newPassword,
  });
}

export async function logout(): Promise<void> {
  try {
    await apiPost('/auth/logout', {});
  } finally {
    window.location.href = '/login/';
  }
}
