/** TanStack Query hooks for OllaBridge data. */

import { useQuery } from '@tanstack/react-query'
import { api } from './api'

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    refetchInterval: 10_000,
    retry: false,
  })
}

export function useModels() {
  return useQuery({
    queryKey: ['models'],
    queryFn: api.models,
    refetchInterval: 30_000,
    retry: false,
  })
}

export function useRuntimes() {
  return useQuery({
    queryKey: ['runtimes'],
    queryFn: api.runtimes,
    refetchInterval: 10_000,
    retry: false,
  })
}

export function useRecent(limit = 20) {
  return useQuery({
    queryKey: ['recent', limit],
    queryFn: () => api.recent(limit),
    refetchInterval: 5_000,
    retry: false,
  })
}

export function useFlowMetrics() {
  return useQuery({
    queryKey: ['flow-metrics'],
    queryFn: api.flowMetrics,
    refetchInterval: 1_500,
    retry: false,
  })
}

export function usePairInfo() {
  return useQuery({
    queryKey: ['pairInfo'],
    queryFn: api.pairInfo,
    refetchInterval: 10_000,
    retry: false,
  })
}

export function usePairedDevices() {
  return useQuery({
    queryKey: ['pairDevices'],
    queryFn: api.pairDevices,
    refetchInterval: 10_000,
    retry: false,
  })
}

export function useConnectionInfo() {
  return useQuery({
    queryKey: ['connectionInfo'],
    queryFn: api.connectionInfo,
    retry: false,
  })
}

export function useSettings() {
  return useQuery({
    queryKey: ['settings'],
    queryFn: api.getSettings,
    retry: false,
  })
}

export function useConsumerNodes() {
  return useQuery({
    queryKey: ['consumerNodes'],
    queryFn: api.consumerNodes,
    refetchInterval: 10_000,
    retry: false,
  })
}

export function useCloudStatus() {
  return useQuery({
    queryKey: ['cloudStatus'],
    queryFn: api.cloudStatus,
    refetchInterval: 3_000,
    retry: false,
  })
}

// Backward-compatible alias for older components
export const usePairDevices = usePairedDevices
