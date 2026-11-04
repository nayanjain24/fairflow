export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  vm_connected: boolean;
  controller_enabled: boolean;
}

export interface ClassPolicyItem {
  name: string;
  rate_mbps?: number;
  floor_mbps: number;
  ceil_mbps: number;
  priority: number;
  leaf_qdisc: string;
}

export interface ActivePolicy {
  link_capacity_mbps: number;
  classes: ClassPolicyItem[];
}

export interface StepOutcomeSummary {
  step_index: number;
  action: string;
  explanation: string;
  timestamp_wall: number;
}

export interface StatusResponse {
  controller_enabled: boolean;
  interface: string;
  namespace: string;
  enforcement_state: string;
  active_policy_id: string | null;
  active_policy: ActivePolicy | null;
  capacity_estimate_mbps: number | null;
  last_step_outcome: StepOutcomeSummary | null;
  timestamp: number;
}

export interface TelemetryFlowSample {
  flow_id: string;
  proto?: string;
  class?: string;
  mbps?: number;
}

export interface TelemetryRecord {
  record_id: string;
  timestamp_wall: number;
  timestamp_mono: number;
  window_duration_s: number;
  is_valid: boolean;
  rtt_ms: number | null;
  p95_latency_ms: number | null;
  jitter_ms: number | null;
  packet_loss_pct: number | null;
  throughput_mbps: number | null;
  flows: TelemetryFlowSample[];
  raw_ref: string | null;
}

export interface PolicyRecord {
  policy_id: string;
  created_at: number;
  policy_type: string;
  is_valid: boolean;
  validation_error: string | null;
  classes: Array<{
    name: string;
    floor_mbps?: number;
    ceil_mbps?: number;
    floor?: number;
    ceil?: number;
    priority?: number;
    leaf_qdisc?: string;
  }>;
  contract_snapshot: Record<string, unknown> | null;
  explanation: string;
}

export interface PolicyValidateRequest {
  policy: {
    classes: Array<{
      name: string;
      rate_mbps: number;
      floor_mbps: number;
      ceil_mbps?: number;
      priority: number;
      leaf_qdisc: string;
    }>;
  };
  capacity_mbps: number;
  capacity_is_raw: boolean;
}

export interface PolicyValidateResponse {
  is_valid: boolean;
  is_feasible: boolean;
  usable_capacity_mbps: number;
  required_minimum_mbps: number;
  allocations_mbps: Record<string, number> | null;
  reasons: string[];
}

export interface PolicyProposeRequest {
  policy: {
    classes: Array<{
      name: string;
      rate_mbps: number;
      floor_mbps: number;
      ceil_mbps?: number;
      priority: number;
      leaf_qdisc: string;
    }>;
  };
  capacity_mbps: number;
  capacity_is_raw: boolean;
  simulate_canary_breach?: boolean;
}

export interface PolicyProposeResponse {
  policy_id: string;
  verdict: 'ACCEPTED' | 'REJECTED' | 'ROLLED_BACK';
  gate_passed: boolean;
  canary_status: 'PASSED' | 'BREACHED' | 'NOT_RUN';
  rollback_performed: boolean;
  rollback_verified?: boolean;
  detect_time_s?: number;
  recover_time_s?: number;
  reasons: string[];
  explanation?: string;
  usable_capacity_mbps: number;
  required_minimum_mbps: number;
  allocations_mbps?: Record<string, number> | null;
  report_markdown?: string;
}

export interface AuditEvent {
  id: number;
  event_id: string;
  timestamp_wall: number;
  timestamp_mono: number | null;
  event_type: string;
  run_id: string | null;
  summary: string;
  details: Record<string, unknown>;
}

export interface RollbackRecord {
  transition_id: string;
  timestamp_wall: number;
  from_state: string;
  to_state: string;
  trigger: string;
  policy_id: string | null;
  rollback_reason: string | null;
  kernel_verified: boolean;
  details: {
    detect_time_s?: number;
    recover_time_s?: number;
    restored_policy_id?: string;
    [key: string]: unknown;
  };
}

export interface ClassifiedFlow {
  flow_id: string;
  protocol: string;
  src_ip: string;
  dst_ip: string;
  src_port: number | null;
  dst_port: number | null;
  dscp: number | null;
  packet_rate_pps: number;
  current_rate_mbps: number;
  mean_packet_size_bytes: number;
  traffic_class: 'interactive' | 'streaming' | 'bulk' | 'unknown';
  effective_class: 'interactive' | 'streaming' | 'bulk';
  guaranteed_minimum_mbps: number;
  confidence: number;
  reason: string;
  is_override: boolean;
}

export interface ContractData {
  version: number;
  measurement_window_s: number;
  interactive: {
    added_delay_target_ms: number;
    added_delay_guardrail_ms: number;
    jitter_target_ms: number;
    jitter_guardrail_ms: number;
    loss_target_pct: number;
    loss_guardrail_pct: number;
    floor_mbps: number;
  };
  streaming: {
    floor_mbps: number;
    added_delay_guardrail_ms: number;
  };
  bulk: {
    floor_mbps: number;
  };
  canary: {
    duration_s: number;
    breach_windows: number;
  };
  recovery: {
    good_windows: number;
  };
  policy: {
    max_step_pct: number;
    min_interval_s: number;
    deadband_pct: number;
  };
  link: {
    default_capacity_mbps: number;
  };
}

export interface ExperimentRun {
  run_id: string;
  scenario_id: 'scenario_a' | 'scenario_b' | 'scenario_c' | 'scenario_d';
  status: 'pending' | 'running' | 'succeeded' | 'failed';
  start_time: number;
  end_time: number | null;
  config: Record<string, unknown>;
  metrics_summary: Record<string, unknown> | null;
  raw_artifacts_dir: string | null;
  error_message: string | null;
}

export interface ArmSummaryRow {
  arm: string;
  n_valid: string;
  n_total: string;
  interactive_target_met: string;
  added_delay_p99_median_ms: string;
  added_delay_p99_iqr_ms: string;
  added_delay_p99_ci95_low: string;
  added_delay_p99_ci95_high: string;
  added_delay_p99_cv: string;
  bulk_goodput_median_mbps: string;
  bulk_goodput_iqr_mbps: string;
  bulk_goodput_fraction_median: string;
  call_loss_median_pct: string;
}

export interface DiskReportEntry {
  run_id: string;
  scenario_id: 'scenario_a' | 'scenario_b' | 'scenario_c' | 'scenario_d' | 'policy_evaluation';
  title: string;
  timestamp: number;
  report_markdown: string;
  summary_by_arm: ArmSummaryRow[];
  trial_metrics: Record<string, string>[];
  metrics_summary: Record<string, unknown> | null;
  artifacts_dir: string;
}

export interface ReportsResponse {
  count: number;
  reports: DiskReportEntry[];
}

export interface KernelQdiscEntry {
  kind: string;
  handle: string;
  parent?: string;
  root?: boolean;
  bytes?: number;
  packets?: number;
  drops?: number;
  overlimits?: number;
  requeues?: number;
  backlog?: number;
  qlen?: number;
  options?: Record<string, unknown>;
}

export interface KernelClassEntry {
  class: string;
  handle: string;
  parent?: string;
  root?: boolean;
  rate?: number;
  ceil?: number;
  bytes?: number;
  packets?: number;
  drops?: number;
  overlimits?: number;
  tokens?: number;
  ctokens?: number;
}

export interface KernelQdiscResponse {
  namespace: string;
  interface: string;
  linux_kernel_active: boolean;
  qdiscs: KernelQdiscEntry[];
  classes: KernelClassEntry[];
  timestamp: number;
}


