/** TanStack Query hooks for OllaBridge data. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import type { ModelAccessPatch, SourceUpsertBody } from './api'

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

// ── Providers Hub ────────────────────────────────────────────

import type { HFModelsQuery } from './api'

export function useProvidersList() {
  return useQuery({
    queryKey: ['providersList'],
    queryFn: api.providersList,
    refetchInterval: 8_000,
    retry: false,
  })
}

export function useProvidersAliases() {
  return useQuery({
    queryKey: ['providersAliases'],
    queryFn: api.providersAliases,
    refetchInterval: 15_000,
    retry: false,
  })
}

export function useHFStatus() {
  return useQuery({
    queryKey: ['hfStatus'],
    queryFn: api.hfStatus,
    refetchInterval: 5_000,
    retry: false,
  })
}

export function useHFModels(params: HFModelsQuery) {
  return useQuery({
    queryKey: ['hfModels', params],
    queryFn: () => api.hfModels(params),
    retry: false,
  })
}

export function useHFRecommendations(n = 3) {
  return useQuery({
    queryKey: ['hfRecommendations', n],
    queryFn: () => api.hfRecommendations(n),
    refetchInterval: 30_000,
    retry: false,
  })
}

// ── External Sources Hub ──────────────────────────────────────

const SOURCES_KEY = ['sources'] as const

export function useSources() {
  return useQuery({
    queryKey: SOURCES_KEY,
    queryFn: api.listSources,
    refetchInterval: 15_000,
    retry: false,
  })
}

export function useUpsertSource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, body }: { name: string; body: SourceUpsertBody }) =>
      api.upsertSource(name, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: SOURCES_KEY }),
  })
}

export function useTestSource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => api.testSource(name),
    onSuccess: () => qc.invalidateQueries({ queryKey: SOURCES_KEY }),
  })
}

export function useRotateSource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, api_key }: { name: string; api_key: string }) =>
      api.rotateSource(name, api_key),
    onSuccess: () => qc.invalidateQueries({ queryKey: SOURCES_KEY }),
  })
}

export function useDeleteSource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => api.deleteSource(name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: SOURCES_KEY })
      qc.invalidateQueries({ queryKey: MODEL_ACCESS_KEY })
    },
  })
}

// ── Models & Access ───────────────────────────────────────────

const MODEL_ACCESS_KEY = ['modelAccess'] as const
const CLOUD_MANIFEST_KEY = ['cloudModelManifest'] as const

export function useModelAccess() {
  return useQuery({
    queryKey: MODEL_ACCESS_KEY,
    queryFn: api.listModelAccess,
    refetchInterval: 15_000,
    retry: false,
  })
}

export function useSetModelAccess() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      sourceId,
      modelId,
      body,
    }: {
      sourceId: string
      modelId: string
      body: ModelAccessPatch
    }) => api.setModelAccess(sourceId, modelId, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: MODEL_ACCESS_KEY })
      qc.invalidateQueries({ queryKey: CLOUD_MANIFEST_KEY })
    },
  })
}

export function useCloudModelManifest() {
  return useQuery({
    queryKey: CLOUD_MANIFEST_KEY,
    queryFn: api.cloudModelManifest,
    refetchInterval: 15_000,
    retry: false,
  })
}
