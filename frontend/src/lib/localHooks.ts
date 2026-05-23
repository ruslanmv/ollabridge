/**
 * TanStack Query hooks for the local model catalog.
 *
 * All hooks share the same query-key conventions as ./hooks.ts so
 * cross-component invalidation works (e.g. enabling a model from the
 * row triggers a refetch of the KPI tiles).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { localApi } from './localApi'

// ── Reads ─────────────────────────────────────────────────────────────

export function useLocalRuntimeInfo() {
  return useQuery({
    queryKey: ['local', 'runtime-info'],
    queryFn: localApi.runtimeInfo,
    refetchInterval: 8_000,
    retry: false,
  })
}

export function useLocalModels(nodeId?: string) {
  return useQuery({
    queryKey: ['local', 'models', nodeId ?? null],
    queryFn: () => localApi.listModels({ nodeId, limit: 500 }),
    refetchInterval: 15_000,
    retry: false,
  })
}

export function useLocalTopModels(nodeId?: string, limit = 3) {
  return useQuery({
    queryKey: ['local', 'top', nodeId ?? null, limit],
    queryFn: () => localApi.topModels(nodeId, limit),
    refetchInterval: 20_000,
    retry: false,
  })
}

export function useActivePulls() {
  return useQuery({
    queryKey: ['local', 'pulls', 'active'],
    queryFn: localApi.activePulls,
    refetchInterval: (q) =>
      (q.state.data?.pulls?.length ?? 0) > 0 ? 1_000 : 5_000,
    retry: false,
  })
}

export function usePullStatus(externalId: string | null, nodeId?: string) {
  return useQuery({
    queryKey: ['local', 'pull', externalId, nodeId ?? null],
    queryFn: () => localApi.pullStatus(externalId!, nodeId),
    enabled: !!externalId,
    refetchInterval: (q) => {
      const s = q.state.data?.status
      return s === 'completed' || s === 'error' ? false : 800
    },
    retry: false,
  })
}

export function useCloudManifest(nodeId?: string) {
  return useQuery({
    queryKey: ['local', 'cloud-manifest', nodeId ?? null],
    queryFn: () => localApi.cloudManifest(nodeId),
    refetchInterval: 30_000,
    retry: false,
  })
}

// ── Mutations ─────────────────────────────────────────────────────────

function useInvalidateLocal() {
  const qc = useQueryClient()
  return () => {
    qc.invalidateQueries({ queryKey: ['local', 'models'] })
    qc.invalidateQueries({ queryKey: ['local', 'top'] })
    qc.invalidateQueries({ queryKey: ['local', 'runtime-info'] })
  }
}

export function useSyncLocalCatalog() {
  const invalidate = useInvalidateLocal()
  return useMutation({
    mutationFn: (vars: { nodeId?: string; autoEnable?: number } = {}) =>
      localApi.sync({ node_id: vars.nodeId, auto_enable: vars.autoEnable ?? 3 }),
    onSuccess: invalidate,
  })
}

export function useEnableLocalModel() {
  const invalidate = useInvalidateLocal()
  return useMutation({
    mutationFn: ({ routerModelId, enabled }: { routerModelId: string; enabled: boolean }) =>
      localApi.enable(routerModelId, enabled),
    onSuccess: invalidate,
  })
}

export function usePinLocalModel() {
  const invalidate = useInvalidateLocal()
  return useMutation({
    mutationFn: ({ routerModelId, pinned }: { routerModelId: string; pinned: boolean }) =>
      localApi.pin(routerModelId, pinned),
    onSuccess: invalidate,
  })
}

export function useTestLocalModel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (routerModelId: string) => localApi.test(routerModelId),
    onSettled: () => qc.invalidateQueries({ queryKey: ['local', 'models'] }),
  })
}

export function useManualAddLocalModel() {
  const invalidate = useInvalidateLocal()
  return useMutation({
    mutationFn: localApi.manualAdd,
    onSuccess: invalidate,
  })
}

export function useDeleteLocalModel() {
  const invalidate = useInvalidateLocal()
  return useMutation({
    mutationFn: (routerModelId: string) => localApi.remove(routerModelId),
    onSuccess: invalidate,
  })
}

export function useStartLocalPull() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ model, nodeId }: { model: string; nodeId?: string }) =>
      localApi.startPull(model, nodeId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['local', 'pulls'] }),
  })
}
