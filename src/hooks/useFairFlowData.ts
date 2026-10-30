import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../api/client';
import { PolicyProposeRequest, PolicyValidateRequest } from '../api/types';

export function useLiveStatus(pollIntervalMs = 1000) {
  return useQuery({
    queryKey: ['fairflow', 'status'],
    queryFn: () => apiClient.getStatus(),
    refetchInterval: pollIntervalMs,
  });
}

export function useContract() {
  return useQuery({
    queryKey: ['fairflow', 'contract'],
    queryFn: () => apiClient.getContract(),
    staleTime: 60_000,
  });
}

export function useTelemetryHistory(limit = 30, pollIntervalMs = 1000) {
  return useQuery({
    queryKey: ['fairflow', 'telemetry', limit],
    queryFn: () => apiClient.getTelemetryHistory(limit),
    refetchInterval: pollIntervalMs,
  });
}

export function useClassifiedFlows(pollIntervalMs = 2000) {
  return useQuery({
    queryKey: ['fairflow', 'flows'],
    queryFn: () => apiClient.getFlows(),
    refetchInterval: pollIntervalMs,
  });
}

export function usePolicies(pollIntervalMs = 2000) {
  return useQuery({
    queryKey: ['fairflow', 'policies'],
    queryFn: () => apiClient.listPolicies(50),
    refetchInterval: pollIntervalMs,
  });
}

export function useRollbackHistory(pollIntervalMs = 2000) {
  return useQuery({
    queryKey: ['fairflow', 'rollbacks'],
    queryFn: () => apiClient.getRollbackHistory(50),
    refetchInterval: pollIntervalMs,
  });
}

export function useAuditEvents(pollIntervalMs = 2000) {
  return useQuery({
    queryKey: ['fairflow', 'events'],
    queryFn: () => apiClient.getEvents(50),
    refetchInterval: pollIntervalMs,
  });
}

export function useExperiments(pollIntervalMs = 2000) {
  return useQuery({
    queryKey: ['fairflow', 'experiments'],
    queryFn: () => apiClient.listExperiments(),
    refetchInterval: pollIntervalMs,
  });
}

export function useDiskReports() {
  return useQuery({
    queryKey: ['fairflow', 'reports'],
    queryFn: () => apiClient.getReports(),
    refetchInterval: 5000,
  });
}

export function useControllerActions() {
  const qc = useQueryClient();

  const toggleController = useMutation({
    mutationFn: (enabled: boolean) => apiClient.setControllerEnabled(enabled),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['fairflow', 'status'] });
      qc.invalidateQueries({ queryKey: ['fairflow', 'events'] });
    },
  });

  const overrideFlow = useMutation({
    mutationFn: ({
      flow_id,
      target_class,
      description,
    }: {
      flow_id: string;
      target_class: 'interactive' | 'streaming' | 'bulk';
      description?: string;
    }) => apiClient.overrideFlowClass(flow_id, target_class, description),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['fairflow', 'flows'] });
      qc.invalidateQueries({ queryKey: ['fairflow', 'events'] });
    },
  });

  const validatePolicy = useMutation({
    mutationFn: (req: PolicyValidateRequest) => apiClient.validatePolicy(req),
  });

  const proposePolicy = useMutation({
    mutationFn: (req: PolicyProposeRequest) => apiClient.proposePolicy(req),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['fairflow', 'policies'] });
      qc.invalidateQueries({ queryKey: ['fairflow', 'rollbacks'] });
      qc.invalidateQueries({ queryKey: ['fairflow', 'status'] });
      qc.invalidateQueries({ queryKey: ['fairflow', 'events'] });
    },
  });

  const updateCapacity = useMutation({
    mutationFn: (capacity_mbps: number) => apiClient.updateCapacityEstimate(capacity_mbps),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['fairflow', 'status'] });
      qc.invalidateQueries({ queryKey: ['fairflow', 'events'] });
    },
  });

  const evaluateStep = useMutation({
    mutationFn: (params: { force?: boolean; synthetic_base_delay_ms?: number; synthetic_throughput_mbps?: number }) =>
      apiClient.evaluateControllerStep(params),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['fairflow', 'telemetry'] });
      qc.invalidateQueries({ queryKey: ['fairflow', 'status'] });
      qc.invalidateQueries({ queryKey: ['fairflow', 'events'] });
    },
  });

  const startExperiment = useMutation({
    mutationFn: ({
      scenario_id,
      duration_s,
    }: {
      scenario_id: 'scenario_a' | 'scenario_b' | 'scenario_c' | 'scenario_d';
      duration_s?: number;
    }) => apiClient.startExperiment(scenario_id, duration_s),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['fairflow', 'experiments'] });
      qc.invalidateQueries({ queryKey: ['fairflow', 'reports'] });
      qc.invalidateQueries({ queryKey: ['fairflow', 'events'] });
    },
  });

  const startLiveTraffic = useMutation({
    mutationFn: (duration_s: number = 30) => apiClient.startLiveTraffic(duration_s),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['fairflow', 'telemetry'] });
      qc.invalidateQueries({ queryKey: ['fairflow', 'flows'] });
      qc.invalidateQueries({ queryKey: ['fairflow', 'events'] });
    },
  });

  const stopLiveTraffic = useMutation({
    mutationFn: () => apiClient.stopLiveTraffic(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['fairflow', 'telemetry'] });
      qc.invalidateQueries({ queryKey: ['fairflow', 'flows'] });
    },
  });

  const resetSystem = useMutation({
    mutationFn: () => apiClient.resetSystemData(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['fairflow'] });
    },
  });

  return {
    toggleController,
    overrideFlow,
    validatePolicy,
    proposePolicy,
    updateCapacity,
    evaluateStep,
    startExperiment,
    startLiveTraffic,
    stopLiveTraffic,
    resetSystem,
  };
}

