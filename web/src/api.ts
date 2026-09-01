const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export type JobStatus =
  | "pending"
  | "discovering"
  | "vision"
  | "generating"
  | "selecting"
  | "validating"
  | "executing"
  | "judging"
  | "advancing"
  | "finalizing"
  | "completed"
  | "failed"
  | "circuit_broken"
  | "cancelled";

export const TERMINAL_STATUSES: JobStatus[] = ["completed", "failed", "circuit_broken", "cancelled"];

export function statusBadgeClass(status: JobStatus): string {
  if (status === "completed") return "badge-completed";
  if (status === "failed" || status === "circuit_broken") return "badge-circuit_broken";
  if (status === "cancelled") return "badge-cancelled";
  if (status === "pending") return "badge-pending";
  return "badge-running";
}

export interface JobSummary {
  job_id: string;
  target_url: string;
  max_scenarios: number | null;
  max_pages: number | null;
  created_at: string;
  status: JobStatus;
}

export interface ScenarioStep {
  action: string;
  target_selector: string | null;
  value: string | null;
}

export interface Scenario {
  scenario_id: string;
  page_url: string;
  title: string;
  description: string;
  steps: ScenarioStep[];
  expect_failure: boolean;
  priority: number;
}

export interface ValidationResult {
  scenario_id: string;
  deterministic_checks_passed: boolean;
  deterministic_errors: string[];
  llm_review_passed: boolean;
  llm_review_notes: string;
  approved: boolean;
}

export interface DomDiffEntry {
  op: "added" | "removed";
  text: string;
}

export interface EvidenceCapture {
  screenshots: string[];
  console_logs: string[];
  network_errors: string[];
  dom_diffs: DomDiffEntry[];
  url_before: string;
  url_after: string;
  deterministic_signals: Record<string, unknown>;
}

export interface ExecutionResult {
  scenario_id: string;
  status: "success" | "failure" | "error";
  evidence: EvidenceCapture;
  error_message: string | null;
}

export interface JudgeVerdict {
  scenario_id: string;
  verdict: "pass" | "fail";
  deterministic_veto: boolean;
  reasoning: string;
  confidence: number;
}

export interface FailureState {
  agent_name: string;
  consecutive_failures: number;
  last_error: string | null;
  degraded_mode: boolean;
}

export interface DiscoveryScreenshot {
  page_url: string;
  viewport_name: string;
  url: string;
}

export interface JobDetail {
  job_id: string;
  target_url: string;
  status: JobStatus;
  max_scenarios: number | null;
  max_pages: number | null;
  pages_tested: number;
  current_scenario_index: number;
  scenario_count: number;
  scenarios: Scenario[];
  discovery_screenshots: DiscoveryScreenshot[];
  validation_results: Record<string, ValidationResult>;
  execution_results: Record<string, ExecutionResult>;
  judge_verdicts: Record<string, JudgeVerdict>;
  failure_states: Record<string, FailureState>;
  circuit_breaker_tripped: boolean;
  final_report: {
    scenario_count: number;
    pages_tested: number;
    passed: number;
    failed: number;
    blocked_pages: { url: string; reason: string | null }[];
  } | null;
  created_at: string;
  updated_at: string;
}

export interface TraceSpan {
  span_id: string;
  name: string;
  start_time: string;
  end_time: string;
  duration: number;
  status: string;
  trace_id: string;
  parent_span_id: string;
}

export interface JobTrace {
  enabled: boolean;
  spans: TraceSpan[];
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${body}`);
  }
  return response.json();
}

export function createJob(
  targetUrl: string,
  maxScenarios: number | null,
  maxPages: number | null
) {
  return request<{ job_id: string; status: JobStatus }>("/jobs", {
    method: "POST",
    body: JSON.stringify({
      target_url: targetUrl,
      max_scenarios: maxScenarios,
      max_pages: maxPages,
    }),
  });
}

export function listJobs() {
  return request<JobSummary[]>("/jobs");
}

export function getJob(jobId: string) {
  return request<JobDetail>(`/jobs/${jobId}`);
}

export function cancelJob(jobId: string) {
  return request<{ job_id: string; status: JobStatus }>(`/jobs/${jobId}/cancel`, {
    method: "POST",
  });
}

export function resumeJob(jobId: string) {
  return request<{ job_id: string; status: JobStatus; resumed: boolean }>(
    `/jobs/${jobId}/resume`,
    { method: "POST" }
  );
}

export function getJobTrace(jobId: string) {
  return request<JobTrace>(`/jobs/${jobId}/trace`);
}

export { API_BASE_URL };
