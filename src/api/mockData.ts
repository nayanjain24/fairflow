import {
  AuditEvent,
  ClassifiedFlow,
  ContractData,
  DiskReportEntry,
  ExperimentRun,
  HealthResponse,
  PolicyProposeRequest,
  PolicyProposeResponse,
  PolicyRecord,
  PolicyValidateRequest,
  PolicyValidateResponse,
  RollbackRecord,
  StatusResponse,
  TelemetryRecord,
} from './types';

export const MOCK_CONTRACT: ContractData = {
  version: 1,
  measurement_window_s: 2,
  interactive: {
    added_delay_target_ms: 30,
    added_delay_guardrail_ms: 80,
    jitter_target_ms: 10,
    jitter_guardrail_ms: 30,
    loss_target_pct: 0.5,
    loss_guardrail_pct: 2.0,
    floor_mbps: 2.0,
  },
  streaming: {
    floor_mbps: 8.0,
    added_delay_guardrail_ms: 200,
  },
  bulk: {
    floor_mbps: 2.0,
  },
  canary: {
    duration_s: 10,
    breach_windows: 2,
  },
  recovery: {
    good_windows: 3,
  },
  policy: {
    max_step_pct: 25,
    min_interval_s: 15,
    deadband_pct: 10,
  },
  link: {
    default_capacity_mbps: 100,
  },
};

// Real report markdown and metrics read directly from results/ on disk
export const REAL_DISK_REPORTS: DiskReportEntry[] = [
  {
    run_id: 'smoke_20261029_174600',
    scenario_id: 'scenario_a',
    title: 'Scenario A (S1 Download vs Call): smoke_20261029_174600',
    timestamp: 1730224132,
    artifacts_dir: 'results/m2/smoke_20261029_174600',
    metrics_summary: null,
    summary_by_arm: [
      {
        arm: 'R0_no_qos',
        n_valid: '2',
        n_total: '2',
        interactive_target_met: '0/2',
        added_delay_p99_median_ms: '197.981',
        added_delay_p99_iqr_ms: '1.461',
        added_delay_p99_ci95_low: '196.52',
        added_delay_p99_ci95_high: '199.442',
        added_delay_p99_cv: '0.0074',
        bulk_goodput_median_mbps: '95.319',
        bulk_goodput_iqr_mbps: '0.108',
        bulk_goodput_fraction_median: '0.953',
        call_loss_median_pct: '0.0',
      },
      {
        arm: 'B1_static_htb',
        n_valid: '2',
        n_total: '2',
        interactive_target_met: '1/2',
        added_delay_p99_median_ms: '36.46',
        added_delay_p99_iqr_ms: '8.818',
        added_delay_p99_ci95_low: '27.643',
        added_delay_p99_ci95_high: '45.278',
        added_delay_p99_cv: '0.2418',
        bulk_goodput_median_mbps: '90.488',
        bulk_goodput_iqr_mbps: '0.319',
        bulk_goodput_fraction_median: '0.905',
        call_loss_median_pct: '0.0',
      },
      {
        arm: 'B2a_fq_codel',
        n_valid: '2',
        n_total: '2',
        interactive_target_met: '2/2',
        added_delay_p99_median_ms: '1.508',
        added_delay_p99_iqr_ms: '0.71',
        added_delay_p99_ci95_low: '0.798',
        added_delay_p99_ci95_high: '2.218',
        added_delay_p99_cv: '0.4708',
        bulk_goodput_median_mbps: '88.175',
        bulk_goodput_iqr_mbps: '0.741',
        bulk_goodput_fraction_median: '0.882',
        call_loss_median_pct: '0.0',
      },
      {
        arm: 'B2b_cake',
        n_valid: '2',
        n_total: '2',
        interactive_target_met: '2/2',
        added_delay_p99_median_ms: '1.559',
        added_delay_p99_iqr_ms: '0.784',
        added_delay_p99_ci95_low: '0.775',
        added_delay_p99_ci95_high: '2.343',
        added_delay_p99_cv: '0.5029',
        bulk_goodput_median_mbps: '87.243',
        bulk_goodput_iqr_mbps: '0.002',
        bulk_goodput_fraction_median: '0.872',
        call_loss_median_pct: '0.0',
      },
    ],
    trial_metrics: [
      {
        arm: 'B2a_fq_codel',
        trial: '1',
        valid: 'True',
        congested_added_delay_p99_ms: '2.218',
        added_delay_p95_ms: '1.838',
        bulk_goodput_mbps: '88.917',
        call_loss_pct: '0.0',
        interactive_target_met: 'True',
        bulk_floor_met: 'True',
        congested_p95_ms: '16.931',
        congested_jitter_ms: '0.525',
      },
      {
        arm: 'B2b_cake',
        trial: '1',
        valid: 'True',
        congested_added_delay_p99_ms: '2.343',
        added_delay_p95_ms: '1.719',
        bulk_goodput_mbps: '87.241',
        call_loss_pct: '0.0',
        interactive_target_met: 'True',
        bulk_floor_met: 'True',
        congested_p95_ms: '16.866',
        congested_jitter_ms: '2.08',
      },
      {
        arm: 'B1_static_htb',
        trial: '1',
        valid: 'True',
        congested_added_delay_p99_ms: '45.278',
        added_delay_p95_ms: '36.965',
        bulk_goodput_mbps: '90.168',
        call_loss_pct: '0.0',
        interactive_target_met: 'False',
        bulk_floor_met: 'True',
        congested_p95_ms: '52.132',
        congested_jitter_ms: '5.342',
      },
      {
        arm: 'R0_no_qos',
        trial: '1',
        valid: 'True',
        congested_added_delay_p99_ms: '196.52',
        added_delay_p95_ms: '195.345',
        bulk_goodput_mbps: '95.211',
        call_loss_pct: '0.0',
        interactive_target_met: 'False',
        bulk_floor_met: 'True',
        congested_p95_ms: '210.525',
        congested_jitter_ms: '10.048',
      },
    ],
    report_markdown: `# FairFlow M2 Scenario A Report: scenario_a_baselines

- **Run ID**: \`smoke_20261029_174600\`
- **Mode**: \`smoke\`
- **Timestamp UTC**: \`2026-10-29T17:48:52.765196+00:00\`
- **Kernel**: \`Linux 6.8 (Ubuntu 24.04 aarch64)\`
- **TCP Congestion Control**: \`cubic\`
- **Contract SHA256**: \`04893b27e604b38cd0fb0e6267b307d2f05447fcde333fd73f1743b9d5a499a8\`

## 1. Primary & Secondary Metrics Summary

| Arm | Valid Trials | Target Met (k/N) | Added Delay p99 Median (ms) | Added Delay p99 IQR (ms) | 95% Bootstrap CI (ms) | Added Delay CV | Bulk Goodput Median (Mbps) | Goodput Fraction | Call Loss Median (%) |
|---|---|---|---|---|---|---|---|---|---|
| \`R0_no_qos\` | 2/2 | **0/2** | 197.98 | 1.46 | [196.52, 199.442] | 0.007 | 95.32 | 95.30% | 0.00% |
| \`B1_static_htb\` | 2/2 | **1/2** | 36.46 | 8.82 | [27.643, 45.278] | 0.242 | 90.49 | 90.50% | 0.00% |
| \`B2a_fq_codel\` | 2/2 | **2/2** | 1.51 | 0.71 | [0.798, 2.218] | 0.471 | 88.17 | 88.20% | 0.00% |
| \`B2b_cake\` | 2/2 | **2/2** | 1.56 | 0.78 | [0.775, 2.343] | 0.503 | 87.24 | 87.20% | 0.00% |

## 2. Safety Contract Adherence

| Arm | Interactive Added Delay Target <= 30 ms | Bulk Floor >= 2.0 Mbps | Status |
|---|---|---|---|
| \`R0_no_qos\` | FAIL (197.98 ms) | PASS (95.32 Mbps) | **NON-COMPLIANT** |
| \`B1_static_htb\` | FAIL (36.46 ms) | PASS (90.49 Mbps) | **NON-COMPLIANT** |
| \`B2a_fq_codel\` | PASS (1.51 ms) | PASS (88.17 Mbps) | **COMPLIANT** |
| \`B2b_cake\` | PASS (1.56 ms) | PASS (87.24 Mbps) | **COMPLIANT** |`,
  },
  {
    run_id: 'scenario_b_20261029_175134',
    scenario_id: 'scenario_b',
    title: 'Scenario B (S2 Capacity Collapse): scenario_b_20261029_175134',
    timestamp: 1730224294,
    artifacts_dir: 'results/scenario_b/scenario_b_20261029_175134',
    summary_by_arm: [],
    trial_metrics: [],
    metrics_summary: {
      scenario: 'scenario_b',
      run_id: 'scenario_b_20261029_175134',
      total_packets: 601,
      pre_collapse_p50_delay_ms: 15.24,
      pre_collapse_p95_delay_ms: 15.96,
      pre_collapse_tput_mbps: 80.03,
      post_collapse_p50_delay_ms: 15.04,
      post_collapse_p95_delay_ms: 16.2,
      post_collapse_tput_mbps: 0.0,
      capacity_collapse_adapted: true,
    },
    report_markdown: `# FairFlow Scenario B: Capacity Collapse Report
- **Run ID**: scenario_b_20261029_175134
- **Pre-Collapse (100 Mbps)**: Throughput=80.03 Mbps, p95 delay=15.96 ms
- **Post-Collapse (20 Mbps)**: Throughput=0.0 Mbps, p95 delay=16.2 ms
- **Adaptation Valid**: True`,
  },
  {
    run_id: 'scenario_c_20261029_175219',
    scenario_id: 'scenario_c',
    title: 'Scenario C (S4 Household Fairness): scenario_c_20261029_175219',
    timestamp: 1730224339,
    artifacts_dir: 'results/scenario_c/scenario_c_20261029_175219',
    summary_by_arm: [],
    trial_metrics: [],
    metrics_summary: {
      scenario: 'scenario_c',
      run_id: 'scenario_c_20261029_175219',
      stream_throughputs_mbps: [30.3, 29.15, 29.78],
      jain_fairness_index: 0.9998,
      gaming_p50_delay_ms: 15.17,
      gaming_p95_delay_ms: 25.29,
      gaming_sample_count: 667,
      fairness_target_met: true,
    },
    report_markdown: `# FairFlow Scenario C: Multi-flow Streaming + Gaming Report
- **Run ID**: scenario_c_20261029_175219
- **Streams (3 flows)**: [30.3, 29.15, 29.78] Mbps
- **Jain Fairness Index**: 0.9998 (Target >= 0.85: True)
- **Gaming Latency p95**: 25.29 ms`,
  },
  {
    run_id: 'scenario_d_20261029_175109',
    scenario_id: 'scenario_d',
    title: 'Scenario D (S3 Harmful Policy & Rollback): scenario_d_20261029_175109',
    timestamp: 1730224269,
    artifacts_dir: 'results/scenario_d/scenario_d_20261029_175109',
    summary_by_arm: [],
    trial_metrics: [],
    metrics_summary: {
      scenario: 'scenario_d',
      run_id: 'scenario_d_20261029_175109',
      harmful_policy_infeasible_rejected: true,
      rejection_reasons: [
        "Safety contract violation: 'interactive' floor (0.50 Mbps) is below contract floor (2.00 Mbps)",
      ],
      canary_breach_detected: true,
      automated_rollback_executed: true,
      coordinator_final_state: 'ROLLED_BACK',
      kernel_restoration_verified: true,
    },
    report_markdown: `# FairFlow Scenario D: Harmful Policy Rejection & Rollback Report
- **Run ID**: scenario_d_20261029_175109
- **Infeasible Policy Rejection**: PASSED (("Safety contract violation: 'interactive' floor (0.50 Mbps) is below contract floor (2.00 Mbps)",))
- **Canary Guardrail Breach Rollback**: PASSED (State=ROLLED_BACK)
- **Independent Kernel State Verification**: True`,
  },
];

// Stateful mock controller for VITE_USE_MOCK=true
class MockBackendStore {
  public controllerEnabled = true;
  public capacityMbps = 100.0;
  public enforcementState = 'ACCEPTED';
  public activePolicyId = 'pol_v1_baseline';
  public stepIndex = 12;

  public flows: ClassifiedFlow[] = [
    {
      flow_id: 'udp:10.0.2.2:5004->10.0.1.2:5004',
      protocol: 'udp',
      src_ip: '10.0.2.2',
      dst_ip: '10.0.1.2',
      src_port: 5004,
      dst_port: 5004,
      dscp: 46,
      packet_rate_pps: 50.0,
      current_rate_mbps: 0.12,
      mean_packet_size_bytes: 200,
      traffic_class: 'interactive',
      effective_class: 'interactive',
      guaranteed_minimum_mbps: 2.0,
      confidence: 0.92,
      reason: 'Heuristic classification: DSCP 46 matches interactive priority; Port 5004 in interactive heuristic list',
      is_override: false,
    },
    {
      flow_id: 'udp:10.0.2.2:27015->10.0.1.2:27015',
      protocol: 'udp',
      src_ip: '10.0.2.2',
      dst_ip: '10.0.1.2',
      src_port: 27015,
      dst_port: 27015,
      dscp: 40,
      packet_rate_pps: 66.7,
      current_rate_mbps: 0.42,
      mean_packet_size_bytes: 120,
      traffic_class: 'interactive',
      effective_class: 'interactive',
      guaranteed_minimum_mbps: 2.0,
      confidence: 0.89,
      reason: 'Heuristic classification: DSCP 40 matches interactive priority; Port 27015 in interactive heuristic list',
      is_override: false,
    },
    {
      flow_id: 'tcp:10.0.2.2:1935->10.0.1.2:51240',
      protocol: 'tcp',
      src_ip: '10.0.2.2',
      dst_ip: '10.0.1.2',
      src_port: 1935,
      dst_port: 51240,
      dscp: 26,
      packet_rate_pps: 750.0,
      current_rate_mbps: 12.5,
      mean_packet_size_bytes: 750,
      traffic_class: 'streaming',
      effective_class: 'streaming',
      guaranteed_minimum_mbps: 8.0,
      confidence: 0.84,
      reason: 'Heuristic classification: DSCP 26 matches streaming priority; Port 1935 in streaming heuristic list',
      is_override: false,
    },
    {
      flow_id: 'tcp:10.0.2.2:5201->10.0.1.2:54102',
      protocol: 'tcp',
      src_ip: '10.0.2.2',
      dst_ip: '10.0.1.2',
      src_port: 5201,
      dst_port: 54102,
      dscp: 0,
      packet_rate_pps: 6800.0,
      current_rate_mbps: 75.36,
      mean_packet_size_bytes: 1480,
      traffic_class: 'bulk',
      effective_class: 'bulk',
      guaranteed_minimum_mbps: 2.0,
      confidence: 0.86,
      reason: 'Heuristic classification: Port 5201 in bulk heuristic list; TCP MTU-sized packets (1480B) and high throughput',
      is_override: false,
    },
  ];

  public policies: PolicyRecord[] = [
    {
      policy_id: 'pol_v3_canary_spike',
      created_at: Date.now() / 1000 - 40,
      policy_type: 'ROLLED_BACK',
      is_valid: true,
      validation_error: 'added_delay (92.0 ms) > guardrail (80.0 ms) across 2 consecutive canary windows',
      classes: [
        { name: 'interactive', floor_mbps: 2.0, ceil_mbps: 95.0, priority: 1, leaf_qdisc: 'pfifo' },
        { name: 'streaming', floor_mbps: 8.0, ceil_mbps: 95.0, priority: 2, leaf_qdisc: 'pfifo' },
        { name: 'bulk', floor_mbps: 2.0, ceil_mbps: 95.0, priority: 3, leaf_qdisc: 'pfifo' },
      ],
      contract_snapshot: null,
      explanation:
        'Accepted by gate; breached canary delay guardrail (92.0 ms > 80.0 ms across 2 consecutive windows); automatically rolled back to pol_v1_baseline and verified in 0.18s.',
    },
    {
      policy_id: 'pol_v2_starve_test',
      created_at: Date.now() / 1000 - 85,
      policy_type: 'PROPOSED_REJECTED',
      is_valid: false,
      validation_error: "Safety contract violation: 'interactive' floor (0.50 Mbps) is below contract floor (2.00 Mbps)",
      classes: [
        { name: 'interactive', floor_mbps: 0.5, ceil_mbps: 95.0, priority: 1, leaf_qdisc: 'fq_codel' },
        { name: 'bulk', floor_mbps: 2.0, ceil_mbps: 95.0, priority: 3, leaf_qdisc: 'fq_codel' },
      ],
      contract_snapshot: null,
      explanation:
        "Rejected by Pre-Apply Safety Gate: Safety contract violation: 'interactive' floor (0.50 Mbps) is below contract floor (2.00 Mbps)",
    },
    {
      policy_id: 'pol_v1_baseline',
      created_at: Date.now() / 1000 - 180,
      policy_type: 'ACCEPTED_ACTIVE',
      is_valid: true,
      validation_error: null,
      classes: [
        { name: 'interactive', floor_mbps: 2.0, ceil_mbps: 95.0, priority: 1, leaf_qdisc: 'fq_codel' },
        { name: 'streaming', floor_mbps: 8.0, ceil_mbps: 95.0, priority: 2, leaf_qdisc: 'fq_codel' },
        { name: 'bulk', floor_mbps: 2.0, ceil_mbps: 95.0, priority: 3, leaf_qdisc: 'fq_codel' },
      ],
      contract_snapshot: null,
      explanation: 'Initial verified baseline policy (shaped to 95.0 Mbps on 100.0 Mbps link; contract floors reserved).',
    },
  ];

  public rollbacks: RollbackRecord[] = [
    {
      transition_id: 'trn_8f7a9d31c0b2',
      timestamp_wall: Date.now() / 1000 - 36,
      from_state: 'CANARY_MONITORING',
      to_state: 'ROLLED_BACK',
      trigger: 'CANARY_GUARDRAIL_BREACH',
      policy_id: 'pol_v3_canary_spike',
      rollback_reason: 'added_delay (92.0 ms) > guardrail (80.0 ms) across 2 consecutive windows',
      kernel_verified: true,
      details: {
        detect_time_s: 4.0,
        recover_time_s: 0.18,
        restored_policy_id: 'pol_v1_baseline',
      },
    },
  ];

  public events: AuditEvent[] = [
    {
      id: 3,
      event_id: 'evt_a81b390c41e1',
      timestamp_wall: Date.now() / 1000 - 36,
      timestamp_mono: 420.0,
      event_type: 'CANARY_ROLLBACK_VERIFIED',
      run_id: null,
      summary: 'Breach detected in canary window 2; restored pol_v1_baseline and verified kernel state in 0.18s',
      details: {
        policy_id: 'pol_v3_canary_spike',
        restored_policy_id: 'pol_v1_baseline',
        detect_time_s: 4.0,
        recover_time_s: 0.18,
      },
    },
    {
      id: 2,
      event_id: 'evt_7c910a24f881',
      timestamp_wall: Date.now() / 1000 - 85,
      timestamp_mono: 371.0,
      event_type: 'POLICY_GATE_REJECTED',
      run_id: null,
      summary: "Pre-apply gate rejected pol_v2_starve_test: 'interactive' floor (0.50 Mbps) < contract floor (2.00 Mbps)",
      details: {
        policy_id: 'pol_v2_starve_test',
      },
    },
    {
      id: 1,
      event_id: 'evt_3b2109ca7001',
      timestamp_wall: Date.now() / 1000 - 180,
      timestamp_mono: 276.0,
      event_type: 'POLICY_COMMITTED',
      run_id: null,
      summary: 'Policy pol_v1_baseline verified, passed canary, and committed as last-known-good',
      details: {
        policy_id: 'pol_v1_baseline',
      },
    },
  ];

  public experiments: ExperimentRun[] = [
    {
      run_id: 'smoke_20261029_174600',
      scenario_id: 'scenario_a',
      status: 'succeeded',
      start_time: 1730224000,
      end_time: 1730224132,
      config: { mode: 'smoke', duration_s: 30 },
      metrics_summary: {
        R0_no_qos_p99_ms: 197.98,
        B1_static_htb_p99_ms: 36.46,
        B2a_fq_codel_p99_ms: 1.51,
        B2b_cake_p99_ms: 1.56,
        target_met_fq_codel: '2/2',
      },
      raw_artifacts_dir: 'results/m2/smoke_20261029_174600',
      error_message: null,
    },
    {
      run_id: 'scenario_b_20261029_175134',
      scenario_id: 'scenario_b',
      status: 'succeeded',
      start_time: 1730224264,
      end_time: 1730224294,
      config: { duration_s: 30 },
      metrics_summary: {
        scenario: 'scenario_b',
        run_id: 'scenario_b_20261029_175134',
        total_packets: 601,
        pre_collapse_p50_delay_ms: 15.24,
        pre_collapse_p95_delay_ms: 15.96,
        pre_collapse_tput_mbps: 80.03,
        post_collapse_p50_delay_ms: 15.04,
        post_collapse_p95_delay_ms: 16.2,
        post_collapse_tput_mbps: 0.0,
        capacity_collapse_adapted: true,
      },
      raw_artifacts_dir: 'results/scenario_b/scenario_b_20261029_175134',
      error_message: null,
    },
    {
      run_id: 'scenario_c_20261029_175219',
      scenario_id: 'scenario_c',
      status: 'succeeded',
      start_time: 1730224319,
      end_time: 1730224339,
      config: { duration_s: 20 },
      metrics_summary: {
        scenario: 'scenario_c',
        run_id: 'scenario_c_20261029_175219',
        stream_throughputs_mbps: [30.3, 29.15, 29.78],
        jain_fairness_index: 0.9998,
        gaming_p50_delay_ms: 15.17,
        gaming_p95_delay_ms: 25.29,
        gaming_sample_count: 667,
        fairness_target_met: true,
      },
      raw_artifacts_dir: 'results/scenario_c/scenario_c_20261029_175219',
      error_message: null,
    },
    {
      run_id: 'scenario_d_20261029_175109',
      scenario_id: 'scenario_d',
      status: 'succeeded',
      start_time: 1730224259,
      end_time: 1730224269,
      config: { duration_s: 10 },
      metrics_summary: {
        scenario: 'scenario_d',
        run_id: 'scenario_d_20261029_175109',
        harmful_policy_infeasible_rejected: true,
        rejection_reasons: [
          "Safety contract violation: 'interactive' floor (0.50 Mbps) is below contract floor (2.00 Mbps)",
        ],
        canary_breach_detected: true,
        automated_rollback_executed: true,
        coordinator_final_state: 'ROLLED_BACK',
        kernel_restoration_verified: true,
      },
      raw_artifacts_dir: 'results/scenario_d/scenario_d_20261029_175109',
      error_message: null,
    },
  ];
}

export const mockStore = new MockBackendStore();

export function getMockHealth(): HealthResponse {
  return {
    status: 'healthy',
    service: 'fairflow-backend (mock)',
    version: '1.0.0',
    vm_connected: true,
    controller_enabled: mockStore.controllerEnabled,
  };
}

export function getMockStatus(): StatusResponse {
  return {
    controller_enabled: mockStore.controllerEnabled,
    interface: 'ff_r_lan',
    namespace: 'ff_router',
    enforcement_state: mockStore.enforcementState,
    active_policy_id: mockStore.activePolicyId,
    active_policy: {
      link_capacity_mbps: Number((mockStore.capacityMbps * 0.95).toFixed(1)),
      classes: [
        { name: 'interactive', rate_mbps: 95.0, floor_mbps: 2.0, ceil_mbps: 95.0, priority: 1, leaf_qdisc: 'fq_codel' },
        { name: 'streaming', rate_mbps: 95.0, floor_mbps: 8.0, ceil_mbps: 95.0, priority: 2, leaf_qdisc: 'fq_codel' },
        { name: 'bulk', rate_mbps: 95.0, floor_mbps: 2.0, ceil_mbps: 95.0, priority: 3, leaf_qdisc: 'fq_codel' },
      ],
    },
    capacity_estimate_mbps: mockStore.capacityMbps,
    last_step_outcome: {
      step_index: mockStore.stepIndex,
      action: 'COMMITTED',
      explanation: 'Control step completed with action COMMITTED',
      timestamp_wall: Date.now() / 1000,
    },
    timestamp: Date.now() / 1000,
  };
}

export function getMockTelemetryHistory(limit = 30): TelemetryRecord[] {
  const now = Date.now() / 1000;
  const records: TelemetryRecord[] = [];
  for (let i = 0; i < Math.min(limit, 24); i++) {
    const t = now - i * 2;
    const isCanarySpike = i === 8 || i === 9;
    records.push({
      record_id: `tel_mock_${i}`,
      timestamp_wall: t,
      timestamp_mono: 1000 - i * 2,
      window_duration_s: 2.0,
      is_valid: true,
      rtt_ms: 15.1,
      p95_latency_ms: isCanarySpike ? 91.4 : Number((16.2 + Math.sin(t) * 0.9).toFixed(2)),
      jitter_ms: isCanarySpike ? 12.4 : Number((0.85 + Math.cos(t) * 0.25).toFixed(2)),
      packet_loss_pct: isCanarySpike ? 0.4 : 0.0,
      throughput_mbps: Number((Math.min(mockStore.capacityMbps * 0.92, 88.4)).toFixed(2)),
      flows: [
        { flow_id: 'udp:10.0.2.2:5004->10.0.1.2:5004', class: 'interactive', mbps: 0.12 },
        { flow_id: 'udp:10.0.2.2:27015->10.0.1.2:27015', class: 'interactive', mbps: 0.42 },
        { flow_id: 'tcp:10.0.2.2:1935->10.0.1.2:51240', class: 'streaming', mbps: 12.5 },
        { flow_id: 'tcp:10.0.2.2:5201->10.0.1.2:54102', class: 'bulk', mbps: 75.36 },
      ],
      raw_ref: null,
    });
  }
  return records;
}

export function validateMockPolicy(req: PolicyValidateRequest): PolicyValidateResponse {
  const usable = req.capacity_is_raw ? Number((req.capacity_mbps * 0.95).toFixed(2)) : req.capacity_mbps;
  let reqMin = 0;
  const reasons: string[] = [];

  for (const c of req.policy.classes) {
    reqMin += c.floor_mbps;
    if (c.name === 'interactive' && c.floor_mbps < 2.0) {
      reasons.push(`Safety contract violation: 'interactive' floor (${c.floor_mbps.toFixed(2)} Mbps) is below contract floor (2.00 Mbps)`);
    }
    if (c.name === 'streaming' && c.floor_mbps < 8.0) {
      reasons.push(`Safety contract violation: 'streaming' floor (${c.floor_mbps.toFixed(2)} Mbps) is below contract floor (8.00 Mbps)`);
    }
    if (c.name === 'bulk' && c.floor_mbps < 2.0) {
      reasons.push(`Safety contract violation: 'bulk' floor (${c.floor_mbps.toFixed(2)} Mbps) is below contract floor (2.00 Mbps)`);
    }
  }
  if (reqMin > usable) {
    reasons.push(`Capacity infeasibility: required minimum guarantees (${reqMin.toFixed(3)} Mbps) exceed usable capacity (${usable.toFixed(3)} Mbps)`);
  }

  const isFeasible = reasons.length === 0;
  return {
    is_valid: isFeasible,
    is_feasible: isFeasible,
    usable_capacity_mbps: usable,
    required_minimum_mbps: reqMin,
    allocations_mbps: isFeasible
      ? Object.fromEntries(req.policy.classes.map((c) => [c.name, c.floor_mbps + (usable - reqMin) / req.policy.classes.length]))
      : null,
    reasons,
  };
}

export function proposeMockPolicy(req: PolicyProposeRequest): PolicyProposeResponse {
  const val = validateMockPolicy(req);
  const pid = `pol_${Math.floor(Date.now() / 1000)}_${Math.random().toString(16).slice(2, 6)}`;
  const now = Date.now() / 1000;

  const buildReportMd = (
    verdictStr: string,
    gateStr: string,
    canaryStr: string,
    reasonsList: string[]
  ) => {
    const rows = req.policy.classes
      .map(
        (c) =>
          `| ${c.name} | ${c.priority} | ${c.floor_mbps.toFixed(2)} Mbps | ${(c.ceil_mbps || c.rate_mbps).toFixed(2)} Mbps | ${c.leaf_qdisc} |`
      )
      .join('\n');
    return [
      `# FairFlow Policy Evaluation Report: ${pid}`,
      `- **Policy ID**: ${pid}`,
      `- **Timestamp UTC**: ${new Date(now * 1000).toISOString()}`,
      `- **Verdict**: ${verdictStr}`,
      `- **Target Interface**: ff_router:ff_r_lan`,
      `- **Usable Shaping Capacity**: ${val.usable_capacity_mbps.toFixed(2)} Mbps`,
      `- **Required Minimum Guarantees**: ${val.required_minimum_mbps.toFixed(2)} Mbps`,
      `- **Pre-Apply Safety Gate**: ${gateStr}`,
      `- **Canary Monitor Verdict**: ${canaryStr}`,
      '',
      '## 1. Completion / Rejection Reason & Explanation',
      ...reasonsList.map((r) => `- ${r}`),
      '',
      '## 2. Proposed Traffic Class Policy',
      '| Class | Priority | Guaranteed Floor | Rate Ceiling | Leaf Qdisc |',
      '| :--- | :--- | :--- | :--- | :--- |',
      rows,
    ].join('\n');
  };

  if (!val.is_feasible) {
    const explanation = `Rejected by Pre-Apply Safety Gate: ${val.reasons.join('; ')}`;
    const report_markdown = buildReportMd('REJECTED', 'REJECTED', 'NOT_RUN (BLOCKED BY GATE)', val.reasons);
    mockStore.policies.unshift({
      policy_id: pid,
      created_at: now,
      policy_type: 'PROPOSED_REJECTED',
      is_valid: false,
      validation_error: val.reasons.join('; '),
      classes: req.policy.classes,
      contract_snapshot: null,
      explanation,
    });
    return {
      policy_id: pid,
      verdict: 'REJECTED',
      gate_passed: false,
      canary_status: 'NOT_RUN',
      rollback_performed: false,
      reasons: val.reasons,
      explanation,
      usable_capacity_mbps: val.usable_capacity_mbps,
      required_minimum_mbps: val.required_minimum_mbps,
      report_markdown,
    };
  }

  if (req.simulate_canary_breach) {
    const reason = 'added_delay (92.0 ms) > guardrail (80.0 ms) across 2 consecutive canary windows';
    const explanation = `Accepted by gate, breached canary guardrails (${reason}); automatically rolled back and verified in 0.18s.`;
    const report_markdown = buildReportMd(
      'ROLLED_BACK',
      'PASSED',
      'BREACHED (AUTO-REVERTED)',
      [reason, 'Restored pol_v1_baseline and verified kernel qdisc state in 0.18s']
    );
    mockStore.enforcementState = 'ROLLED_BACK';
    mockStore.policies.unshift({
      policy_id: pid,
      created_at: now,
      policy_type: 'ROLLED_BACK',
      is_valid: true,
      validation_error: reason,
      classes: req.policy.classes,
      contract_snapshot: null,
      explanation,
    });
    mockStore.rollbacks.unshift({
      transition_id: `trn_${Math.random().toString(16).slice(2, 10)}`,
      timestamp_wall: now,
      from_state: 'CANARY_MONITORING',
      to_state: 'ROLLED_BACK',
      trigger: 'CANARY_GUARDRAIL_BREACH',
      policy_id: pid,
      rollback_reason: reason,
      kernel_verified: true,
      details: { detect_time_s: 4.0, recover_time_s: 0.18, restored_policy_id: mockStore.activePolicyId },
    });
    return {
      policy_id: pid,
      verdict: 'ROLLED_BACK',
      gate_passed: true,
      canary_status: 'BREACHED',
      rollback_performed: true,
      rollback_verified: true,
      detect_time_s: 4.0,
      recover_time_s: 0.18,
      reasons: [reason],
      explanation,
      usable_capacity_mbps: val.usable_capacity_mbps,
      required_minimum_mbps: val.required_minimum_mbps,
      report_markdown,
    };
  }

  const explanation = `Passed pre-apply safety gate, enforced on ff_router:ff_r_lan, and passed canary monitoring on ${val.usable_capacity_mbps} Mbps usable capacity.`;
  const reasons = [
    `All contract minimum floors satisfied (${val.required_minimum_mbps.toFixed(2)} Mbps <= ${val.usable_capacity_mbps.toFixed(2)} Mbps usable capacity).`,
    'Kernel HTB & leaf qdiscs verified on ff_router:ff_r_lan.',
  ];
  const report_markdown = buildReportMd('ACCEPTED', 'PASSED', 'PASSED (5/5 WINDOWS CLEAN)', reasons);
  mockStore.activePolicyId = pid;
  mockStore.enforcementState = 'ACCEPTED';
  mockStore.policies.unshift({
    policy_id: pid,
    created_at: now,
    policy_type: 'ACCEPTED_ACTIVE',
    is_valid: true,
    validation_error: null,
    classes: req.policy.classes,
    contract_snapshot: null,
    explanation,
  });

  return {
    policy_id: pid,
    verdict: 'ACCEPTED',
    gate_passed: true,
    canary_status: 'PASSED',
    rollback_performed: false,
    reasons,
    explanation,
    usable_capacity_mbps: val.usable_capacity_mbps,
    required_minimum_mbps: val.required_minimum_mbps,
    allocations_mbps: val.allocations_mbps,
    report_markdown,
  };
}

export function resetMockStore(): void {
  const now = Date.now() / 1000;
  mockStore.capacityMbps = 100.0;
  mockStore.activePolicyId = 'pol_v1_baseline';
  mockStore.enforcementState = 'ACCEPTED';
  mockStore.policies = [
    {
      policy_id: 'pol_v1_baseline',
      created_at: now,
      policy_type: 'ACCEPTED_ACTIVE',
      is_valid: true,
      validation_error: null,
      classes: [
        { name: 'interactive', floor_mbps: 2.0, ceil_mbps: 95.0, priority: 1, leaf_qdisc: 'fq_codel' },
        { name: 'streaming', floor_mbps: 8.0, ceil_mbps: 95.0, priority: 2, leaf_qdisc: 'fq_codel' },
        { name: 'bulk', floor_mbps: 2.0, ceil_mbps: 95.0, priority: 3, leaf_qdisc: 'fq_codel' },
      ],
      contract_snapshot: null,
      explanation: 'Clean baseline policy restored after system reset (shaped to 95.0 Mbps on 100.0 Mbps link).',
    },
  ];
  mockStore.rollbacks = [];
  mockStore.events = [
    {
      id: 1,
      event_id: 'evt_reset_clean',
      timestamp_wall: now,
      timestamp_mono: 100.0,
      event_type: 'SYSTEM_DATA_RESET',
      run_id: null,
      summary: 'Cleared all telemetry, policies, rollbacks, and overrides; restored clean baseline.',
      details: {},
    },
  ];
  mockStore.flows = mockStore.flows.map((f) => ({
    ...f,
    is_override: false,
  }));
}

export function getMockKernelQdisc() {
  const capBps = Math.round(mockStore.capacityMbps * 0.95 * 1_000_000 / 8);
  return {
    namespace: 'ff_router',
    interface: 'ff_r_lan',
    linux_kernel_active: true,
    qdiscs: [
      {
        kind: 'htb',
        handle: '1:',
        root: true,
        bytes: 482_910_400,
        packets: 324_180,
        drops: 0,
        overlimits: 1_240,
        requeues: 0,
        backlog: 0,
        qlen: 0,
        options: { r2q: 10, default: '0x30' },
      },
      {
        kind: 'fq_codel',
        handle: '100:',
        parent: '1:10',
        bytes: 18_420_100,
        packets: 92_100,
        drops: 0,
        overlimits: 0,
        requeues: 0,
        backlog: 0,
        qlen: 0,
        options: { limit: 10240, flows: 1024, quantum: 1514, target: 4999, interval: 99999, ecn: true },
      },
      {
        kind: 'fq_codel',
        handle: '200:',
        parent: '1:20',
        bytes: 94_110_200,
        packets: 68_420,
        drops: 0,
        overlimits: 0,
        requeues: 0,
        backlog: 0,
        qlen: 0,
        options: { limit: 10240, flows: 1024, quantum: 1514, target: 4999, interval: 99999, ecn: true },
      },
      {
        kind: 'fq_codel',
        handle: '300:',
        parent: '1:30',
        bytes: 370_380_100,
        packets: 163_660,
        drops: 14,
        overlimits: 0,
        requeues: 0,
        backlog: 3028,
        qlen: 2,
        options: { limit: 10240, flows: 1024, quantum: 1514, target: 4999, interval: 99999, ecn: true },
      },
    ],
    classes: [
      {
        class: 'htb',
        handle: '1:1',
        root: true,
        rate: capBps,
        ceil: capBps,
        bytes: 482_910_400,
        packets: 324_180,
        drops: 0,
        overlimits: 1_240,
        tokens: 1966,
        ctokens: 1966,
      },
      {
        class: 'htb',
        handle: '1:10',
        parent: '1:1',
        rate: 250_000,
        ceil: capBps,
        bytes: 18_420_100,
        packets: 92_100,
        drops: 0,
        overlimits: 0,
        tokens: 100000,
        ctokens: 1966,
      },
      {
        class: 'htb',
        handle: '1:20',
        parent: '1:1',
        rate: 1_000_000,
        ceil: capBps,
        bytes: 94_110_200,
        packets: 68_420,
        drops: 0,
        overlimits: 0,
        tokens: 25000,
        ctokens: 1966,
      },
      {
        class: 'htb',
        handle: '1:30',
        parent: '1:1',
        rate: 250_000,
        ceil: capBps,
        bytes: 370_380_100,
        packets: 163_660,
        drops: 14,
        overlimits: 412,
        tokens: 96000,
        ctokens: 1966,
      },
    ],
    timestamp: Date.now() / 1000,
  };
}


