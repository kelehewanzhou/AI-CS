export type UserRole = 'student' | 'teacher';

export interface User {
  user_id: string;
  username: string;
  role: UserRole;
  must_change_password: boolean;
}

export interface GraphNode {
  node_id: string;
  title: string;
  course_code: 'DS' | 'CO' | 'OS' | 'CN';
  evidence_status: '已核验' | '部分定位' | '待补充';
}

export interface EdgeView {
  edge_id: string;
  source_id: string;
  source_title: string;
  target_id: string;
  target_title: string;
  relation_type: 'prerequisite' | 'implements' | 'contrast' | 'boundary';
  display_mode: 'directed' | 'symmetric';
  display_label: string;
  mechanism: string;
  abc_grade: 'A' | 'B' | 'C';
  boundary_note: string;
  evidence_status: '已核验' | '部分定位' | '待补充';
  evidence_summary: string;
  evidence_detail: Record<string, unknown> | null;
}

export interface EvidenceOverview {
  status: '已核验' | '部分定位' | '待补充' | '无证据';
  reason: string;
  counts: Record<string, number>;
  edge_ids: string[];
}

export interface NodeContent {
  node_id: string;
  title: string;
  course_code: string;
  chapter_scope: string;
  description: string;
  aliases: string[];
  scope_tags: string[];
  evidence_overview: EvidenceOverview;
  incoming_edges: EdgeView[];
  outgoing_edges: EdgeView[];
}

export interface NodeLearningState {
  node_id: string;
  state: string;
  reason: string;
  has_viewed: boolean;
  total_attempt_count: number;
  evaluation_count: number;
  recent_window_size: number;
  recent_accuracy: number | null;
  latest_evaluation_correct: boolean | null;
  available_exercise_count: number;
  can_evaluate_mastery: boolean;
  rule_version: string;
}

export interface NodeDetail {
  node: NodeContent;
  exercise_count: number;
  learning: NodeLearningState;
}

export interface SubgraphMeta {
  mode: string;
  seed_node_ids: string[];
  applied_hops: number;
  filters: Record<string, unknown>;
  node_count: number;
  edge_count: number;
  limits: { nodes: number; edges: number };
  truncated: boolean;
  seed_checksum: string;
}

export interface SubgraphResult {
  nodes: GraphNode[];
  edges: EdgeView[];
  meta: SubgraphMeta;
}

export interface Exercise {
  question_id: string;
  type: string;
  content: string;
  options: Array<{ key: string; text: string }> | null;
  difficulty: number;
  related_node_ids: string[];
  is_active: boolean;
}

export interface AttemptView {
  attempt_id: number;
  client_submission_id: string;
  question: Exercise;
  answer: unknown;
  is_correct: boolean;
  is_evaluation: boolean;
  submitted_at: string;
  feedback: string;
}

export interface LearningEvent {
  event_id: number;
  event_type: string;
  resource_type: string;
  resource_id: string;
  created_at: string;
}

export interface ContentSummary {
  content_scope: string;
  seed_checksum: string;
  last_import: { run_id: string; finished_at: string };
  counts: Record<string, number>;
  edge_evidence_counts: Record<string, number>;
}

export interface QAResponse {
  status: 'answered' | 'not_covered' | 'insufficient_evidence';
  reason: 'no_match' | 'too_many_nodes' | 'ambiguous_relation' | 'no_direct_relation' | null;
  answer: string;
  used_node_ids: string[];
  used_edge_ids: string[];
  uncertainty_flag: boolean;
  boundary_note: string;
}
