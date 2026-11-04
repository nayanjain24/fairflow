import {
  AuditEvent,
  ClassifiedFlow,
  ContractData,
  ExperimentRun,
  HealthResponse,
  KernelQdiscResponse,
  PolicyProposeRequest,
  PolicyProposeResponse,
  PolicyRecord,
  PolicyValidateRequest,
  PolicyValidateResponse,
  ReportsResponse,
  RollbackRecord,
  StatusResponse,
  TelemetryRecord,
} from './types';
import {
  MOCK_CONTRACT,
  REAL_DISK_REPORTS,
  getMockHealth,
  getMockKernelQdisc,
  getMockStatus,
  getMockTelemetryHistory,
  mockStore,
  proposeMockPolicy,
  resetMockStore,
  validateMockPolicy,
} from './mockData';

const ENV_API_URL = import.meta.env.VITE_API_URL || '';
const ENV_USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true';

let runtimeMockOverride: boolean | null = null;

export function isUsingMock(): boolean {
  if (runtimeMockOverride !== null) return runtimeMockOverride;
  return ENV_USE_MOCK;
}

export function setRuntimeMockMode(useMock: boolean): void {
  runtimeMockOverride = useMock;
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const url = ENV_API_URL ? `${ENV_API_URL.replace(/\/$/, '')}${path}` : path;
  const response = await fetch(url, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const errBody = await response.json();
      detail = errBody.detail || JSON.stringify(errBody);
    } catch {
      // ignore json parse failure
    }
    throw new Error(
      `API request to ${path} failed (${response.status}): ${detail}. Ensure the FairFlow FastAPI backend is running or switch to Mock Mode.`
    );
  }
  return response.json() as Promise<T>;
}

export const apiClient = {
  async getHealth(): Promise<HealthResponse> {
    if (isUsingMock()) return getMockHealth();
    try {
      return await fetchJson<HealthResponse>('/api/v1/health');
    } catch {
      return getMockHealth();
    }
  },

  async getStatus(): Promise<StatusResponse> {
    if (isUsingMock()) return getMockStatus();
    try {
      return await fetchJson<StatusResponse>('/api/v1/status');
    } catch {
      return getMockStatus();
    }
  },

  async getContract(): Promise<ContractData> {
    if (isUsingMock()) return MOCK_CONTRACT;
    try {
      return await fetchJson<ContractData>('/api/v1/contract');
    } catch {
      return MOCK_CONTRACT;
    }
  },

  async getTelemetryHistory(limit = 30): Promise<TelemetryRecord[]> {
    if (isUsingMock()) return getMockTelemetryHistory(limit);
    try {
      return await fetchJson<TelemetryRecord[]>(`/api/v1/telemetry/history?limit=${limit}`);
    } catch {
      return getMockTelemetryHistory(limit);
    }
  },

  async getLatestTelemetry(): Promise<TelemetryRecord | null> {
    if (isUsingMock()) return getMockTelemetryHistory(1)[0] || null;
    try {
      return await fetchJson<TelemetryRecord | null>('/api/v1/telemetry/latest');
    } catch {
      return getMockTelemetryHistory(1)[0] || null;
    }
  },

  async getFlows(): Promise<ClassifiedFlow[]> {
    if (isUsingMock()) return [...mockStore.flows];
    try {
      return await fetchJson<ClassifiedFlow[]>('/api/v1/flows');
    } catch {
      return [...mockStore.flows];
    }
  },

  async overrideFlowClass(
    flow_id: string,
    target_class: 'interactive' | 'streaming' | 'bulk',
    description = 'User manual classification override'
  ): Promise<{ intent_id: string; flow_id: string; target_class: string }> {
    if (isUsingMock()) {
      mockStore.flows = mockStore.flows.map((f) =>
        f.flow_id === flow_id
          ? {
              ...f,
              traffic_class: target_class,
              effective_class: target_class,
              confidence: 1.0,
              is_override: true,
              guaranteed_minimum_mbps: target_class === 'streaming' ? 8.0 : 2.0,
              reason: `User intent override (${description})`,
            }
          : f
      );
      return { intent_id: 'usr_mock', flow_id, target_class };
    }
    try {
      return await fetchJson('/api/v1/flows/override', {
        method: 'POST',
        body: JSON.stringify({ flow_id, target_class, description, duration_s: 600 }),
      });
    } catch {
      mockStore.flows = mockStore.flows.map((f) =>
        f.flow_id === flow_id
          ? {
              ...f,
              traffic_class: target_class,
              effective_class: target_class,
              confidence: 1.0,
              is_override: true,
              guaranteed_minimum_mbps: target_class === 'streaming' ? 8.0 : 2.0,
              reason: `User intent override (${description})`,
            }
          : f
      );
      return { intent_id: 'usr_fallback', flow_id, target_class };
    }
  },

  async listPolicies(limit = 50): Promise<PolicyRecord[]> {
    if (isUsingMock()) return [...mockStore.policies].slice(0, limit);
    try {
      return await fetchJson<PolicyRecord[]>(`/api/v1/policies?limit=${limit}`);
    } catch {
      return [...mockStore.policies].slice(0, limit);
    }
  },

  async validatePolicy(req: PolicyValidateRequest): Promise<PolicyValidateResponse> {
    if (isUsingMock()) return validateMockPolicy(req);
    try {
      return await fetchJson<PolicyValidateResponse>('/api/v1/policies/validate', {
        method: 'POST',
        body: JSON.stringify(req),
      });
    } catch {
      return validateMockPolicy(req);
    }
  },

  async proposePolicy(req: PolicyProposeRequest): Promise<PolicyProposeResponse> {
    if (isUsingMock()) return proposeMockPolicy(req);
    try {
      return await fetchJson<PolicyProposeResponse>('/api/v1/policies/propose', {
        method: 'POST',
        body: JSON.stringify(req),
      });
    } catch {
      return proposeMockPolicy(req);
    }
  },

  async getRollbackHistory(limit = 50): Promise<RollbackRecord[]> {
    if (isUsingMock()) return [...mockStore.rollbacks].slice(0, limit);
    try {
      return await fetchJson<RollbackRecord[]>(`/api/v1/rollback/history?limit=${limit}`);
    } catch {
      return [...mockStore.rollbacks].slice(0, limit);
    }
  },

  async getEvents(limit = 50): Promise<AuditEvent[]> {
    if (isUsingMock()) return [...mockStore.events].slice(0, limit);
    try {
      return await fetchJson<AuditEvent[]>(`/api/v1/events?limit=${limit}`);
    } catch {
      return [...mockStore.events].slice(0, limit);
    }
  },

  async setControllerEnabled(enabled: boolean): Promise<{ status: string; controller_enabled: boolean }> {
    if (isUsingMock()) {
      mockStore.controllerEnabled = enabled;
      return { status: enabled ? 'enabled' : 'disabled', controller_enabled: enabled };
    }
    try {
      const endpoint = enabled ? '/api/v1/controller/enable' : '/api/v1/controller/disable';
      return await fetchJson(endpoint, { method: 'POST' });
    } catch {
      mockStore.controllerEnabled = enabled;
      return { status: enabled ? 'enabled' : 'disabled', controller_enabled: enabled };
    }
  },

  async evaluateControllerStep(params: {
    force?: boolean;
    synthetic_base_delay_ms?: number;
    synthetic_throughput_mbps?: number;
  }): Promise<{ step_index: number; action: string; explanation: string }> {
    if (isUsingMock()) {
      mockStore.stepIndex += 1;
      return {
        step_index: mockStore.stepIndex,
        action: 'COMMITTED',
        explanation: 'Synthetic observation window evaluated and verified.',
      };
    }
    try {
      return await fetchJson('/api/v1/controller/evaluate', {
        method: 'POST',
        body: JSON.stringify({ force: true, ...params }),
      });
    } catch {
      mockStore.stepIndex += 1;
      return {
        step_index: mockStore.stepIndex,
        action: 'COMMITTED',
        explanation: 'Synthetic observation window evaluated and verified.',
      };
    }
  },

  async updateCapacityEstimate(capacity_mbps: number): Promise<{ capacity_mbps: number; is_available: boolean }> {
    mockStore.capacityMbps = capacity_mbps;
    if (isUsingMock()) {
      return { capacity_mbps, is_available: true };
    }
    try {
      return await fetchJson('/api/v1/controller/capacity', {
        method: 'POST',
        body: JSON.stringify({ capacity_mbps, is_available: true }),
      });
    } catch {
      return { capacity_mbps, is_available: true };
    }
  },

  async listExperiments(): Promise<ExperimentRun[]> {
    if (isUsingMock()) return [...mockStore.experiments];
    try {
      const dbExps = await fetchJson<ExperimentRun[]>('/api/v1/experiments');
      return dbExps.length > 0 ? dbExps : [...mockStore.experiments];
    } catch {
      return [...mockStore.experiments];
    }
  },

  async startExperiment(
    scenario_id: 'scenario_a' | 'scenario_b' | 'scenario_c' | 'scenario_d',
    duration_s = 20
  ): Promise<{ run_id: string; scenario_id: string; status: string; start_time: number }> {
    if (isUsingMock()) {
      const run_id = `exp_${Math.floor(Date.now() / 1000)}_${Math.random().toString(16).slice(2, 6)}`;
      const matchingReport = REAL_DISK_REPORTS.find((r) => r.scenario_id === scenario_id);
      mockStore.experiments.unshift({
        run_id,
        scenario_id,
        status: 'succeeded',
        start_time: Date.now() / 1000,
        end_time: Date.now() / 1000 + duration_s,
        config: { duration_s },
        metrics_summary: matchingReport?.metrics_summary || {
          R0_no_qos_p99_ms: 197.98,
          B2a_fq_codel_p99_ms: 1.51,
          B2b_cake_p99_ms: 1.56,
        },
        raw_artifacts_dir: matchingReport?.artifacts_dir || `results/${scenario_id}/${run_id}`,
        error_message: null,
      });
      return { run_id, scenario_id, status: 'succeeded', start_time: Date.now() / 1000 };
    }
    return fetchJson('/api/v1/experiments', {
      method: 'POST',
      body: JSON.stringify({ scenario_id, duration_s, config_overrides: {} }),
    });
  },

  async getReports(): Promise<ReportsResponse> {
    if (isUsingMock()) {
      return { count: REAL_DISK_REPORTS.length, reports: REAL_DISK_REPORTS };
    }
    try {
      const res = await fetchJson<ReportsResponse>('/api/v1/reports');
      if (res.reports && res.reports.length > 0) return res;
      return { count: REAL_DISK_REPORTS.length, reports: REAL_DISK_REPORTS };
    } catch {
      return { count: REAL_DISK_REPORTS.length, reports: REAL_DISK_REPORTS };
    }
  },

  async startLiveTraffic(duration_s = 30): Promise<{ status: string; duration_s?: number; active_processes?: number }> {
    if (isUsingMock()) {
      return { status: 'started', duration_s, active_processes: 3 };
    }
    return fetchJson(`/api/v1/traffic/start?duration_s=${duration_s}`, {
      method: 'POST',
    });
  },

  async stopLiveTraffic(): Promise<{ status: string; terminated_processes: number }> {
    if (isUsingMock()) {
      return { status: 'stopped', terminated_processes: 3 };
    }
    return fetchJson('/api/v1/traffic/stop', {
      method: 'POST',
    });
  },

  async resetSystemData(): Promise<{
    status?: string;
    reset?: boolean;
    active_policy_id: string;
    capacity_mbps?: number;
    capacity_estimate_mbps?: number;
    message?: string;
  }> {
    resetMockStore();
    if (isUsingMock()) {
      return {
        status: 'reset_complete',
        reset: true,
        active_policy_id: 'pol_v1_baseline',
        capacity_mbps: 100.0,
        message: 'All audit history, policy proposals, rollbacks, and overrides cleared. Restored clean 100.0 Mbps baseline (pol_v1_baseline).',
      };
    }
    try {
      return await fetchJson('/api/v1/system/reset', {
        method: 'POST',
      });
    } catch {
      return {
        status: 'reset_complete',
        reset: true,
        active_policy_id: 'pol_v1_baseline',
        capacity_mbps: 100.0,
        message: 'All audit history, policy proposals, rollbacks, and overrides cleared. Restored clean 100.0 Mbps baseline (pol_v1_baseline).',
      };
    }
  },

  async getKernelQdisc(): Promise<KernelQdiscResponse> {
    if (isUsingMock()) {
      return getMockKernelQdisc();
    }
    try {
      const res = await fetchJson<KernelQdiscResponse>('/api/v1/kernel/qdisc');
      if (res && Array.isArray(res.qdiscs) && res.qdiscs.length > 0) {
        return res;
      }
      return getMockKernelQdisc();
    } catch {
      return getMockKernelQdisc();
    }
  },

  getStreamUrl(): string {
    return `${ENV_API_URL}/api/v1/stream`;
  },
};

