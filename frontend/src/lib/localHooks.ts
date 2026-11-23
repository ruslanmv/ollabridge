/**
 * TanStack Query hooks for the local model catalog.
 *
 * All hooks share the same query-key conventions as ./hooks.ts so
 * cross-component invalidation works (e.g. enabling a model from the
 * row triggers a refetch of the KPI tiles).
 */

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { localApi } from './localApi'
import type { LibrarySource } from './localApi'

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

// ── Model library ───────────────────────────────────────────────────────

// The app refetches every query on a timer by default. Library lookups go to
// other sites and change slowly, so they run once and stay until asked again.
const ONCE = { refetchInterval: false, refetchOnWindowFocus: false, retry: false } as const

export function useLibrarySearch(query: string, source: LibrarySource, enabled = true) {
  return useQuery({
    queryKey: ['local', 'library', 'search', source, query],
    queryFn: () => localApi.librarySearch(query, source),
    enabled,
    staleTime: 5 * 60_000,
    // Keep the last results on screen while the next query loads, so the list never blanks.
    placeholderData: keepPreviousData,
    ...ONCE,
  })
}

export function useLibraryBuilds(name: string | null, source: LibrarySource, tags: string[] = []) {
  return useQuery({
    queryKey: ['local', 'library', 'builds', source, name, tags.join(',')],
    queryFn: () => localApi.libraryBuilds(name!, source, tags),
    enabled: !!name,
    staleTime: 5 * 60_000,
    ...ONCE,
  })
}

export function useRecommendations(enabled = true) {
  return useQuery({
    queryKey: ['local', 'library', 'recommendations'],
    queryFn: localApi.recommendations,
    enabled,
    staleTime: 60_000,
    ...ONCE,
  })
}

export function useSetRecommendations() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (enabled: boolean) => localApi.setRecommendations(enabled),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['local', 'library', 'recommendations'] }),
  })
}

export function useCancelLocalPull() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ model, nodeId }: { model: string; nodeId?: string }) =>
      localApi.cancelPull(model, nodeId),
    onSettled: () => qc.invalidateQueries({ queryKey: ['local', 'pull'] }),
  })
}

export function useCreateVariant() {
  return useMutation({ mutationFn: localApi.createVariant })
}

// ── Model copies ("Build a model") ────────────────────────────────────

const VARIANTS_KEY = ['local', 'variants']

export function useModelVariants(enabled = true) {
  return useQuery({
    queryKey: VARIANTS_KEY,
    queryFn: localApi.variants,
    enabled,
    staleTime: 15_000,
    retry: false,
  })
}

export function useBuildVariant() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: localApi.buildVariant,
    onSettled: () => qc.invalidateQueries({ queryKey: VARIANTS_KEY }),
  })
}

export function useTestVariant() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => localApi.testVariant(name),
    onSettled: () => qc.invalidateQueries({ queryKey: VARIANTS_KEY }),
  })
}

export function useRemoveVariant() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => localApi.removeVariant(name),
    onSettled: () => qc.invalidateQueries({ queryKey: VARIANTS_KEY }),
  })
}
