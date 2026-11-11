import type {
  AttemptView,
  ContentSummary,
  Exercise,
  LearningEvent,
  NodeDetail,
  NodeLearningState,
  QAResponse,
  SubgraphResult,
} from './types';

const configuredBaseUrl = process.env.NEXT_PUBLIC_API_URL?.trim();
export const API_BASE_URL = (configuredBaseUrl || '/api/v1').replace(/\/$/, '');

export interface ApiErrorBody {
  code?: string;
  message?: string;
  request_id?: string;
  details?: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly requestId?: string;
  readonly details?: unknown;

  constructor(status: number, body: ApiErrorBody = {}) {
    super(body.message || `请求失败（${status}）`);
    this.name = 'ApiError';
    this.status = status;
    this.code = body.code;
    this.requestId = body.request_id;
    this.details = body.details;
  }
}

function endpoint(path: string): string {
  return `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(endpoint(path), {
    ...init,
    headers,
    credentials: 'include',
  });
  const raw = await response.text();
  let body: { data?: T } & ApiErrorBody = {};
  if (raw) {
    try {
      body = JSON.parse(raw) as typeof body;
    } catch {
      body = { message: raw };
    }
  }

  if (!response.ok) {
    throw new ApiError(response.status, body);
  }
  return body.data as T;
}

export function apiGet<T>(path: string, params?: URLSearchParams): Promise<T> {
  const query = params?.toString();
  return request<T>(query ? `${path}?${query}` : path);
}

export function apiPost<T>(path: string, value: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    body: JSON.stringify(value),
  });
}

export function getSubgraph(params: URLSearchParams): Promise<SubgraphResult> {
  return apiGet<SubgraphResult>('/graph/subgraph', params);
}

export function askQuestion(question: string): Promise<QAResponse> {
  return apiPost<QAResponse>('/ask', { question });
}

export function getNode(nodeId: string): Promise<NodeDetail> {
  return apiGet<NodeDetail>(`/nodes/${encodeURIComponent(nodeId)}`);
}

export function getEdge(edgeId: string): Promise<import('./types').EdgeView> {
  return apiGet<import('./types').EdgeView>(`/edges/${encodeURIComponent(edgeId)}`);
}

export function listExercises(params: URLSearchParams): Promise<{
  items: Exercise[];
  total: number;
  limit: number;
  offset: number;
}> {
  return apiGet('/exercises', params);
}

export function listAttempts(questionId?: string): Promise<{
  items: AttemptView[];
  total: number;
  limit: number;
  offset: number;
}> {
  const params = new URLSearchParams({ limit: '20', offset: '0' });
  if (questionId) params.set('question_id', questionId);
  return apiGet('/exercises/attempts', params);
}

export function submitAttempt(value: {
  question_id: string;
  answer: unknown;
  client_submission_id: string;
}): Promise<AttemptView> {
  return apiPost('/exercises/attempts', value);
}

export function getLearningEvents(cursor?: string): Promise<{
  items: LearningEvent[];
  next_cursor: string | null;
}> {
  const params = new URLSearchParams({ limit: '20' });
  if (cursor) params.set('cursor', cursor);
  return apiGet('/learning/events', params);
}

export function getLearningStatus(): Promise<{
  items: NodeLearningState[];
  rule_version: string;
}> {
  return apiGet('/learning/status');
}

export function getContentSummary(): Promise<ContentSummary> {
  return apiGet('/learning/summary');
}

export function recordLearningEvent(
  eventType: 'view_node' | 'view_edge' | 'start_exercise',
  resourceType: 'node' | 'edge' | 'exercise',
  resourceId: string,
): Promise<LearningEvent> {
  return apiPost('/learning/events', {
    event_type: eventType,
    resource_type: resourceType,
    resource_id: resourceId,
  });
}
