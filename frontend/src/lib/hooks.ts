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
  const { data: health } = useHealth()
  const online = health?.status === 'ok'

  return useQuery({
    queryKey: ['models'],
    queryFn: api.models,
    refetchInterval: online ? 30_000 : false,
    retry: false,
    enabled: online,
  })
}

export function useRuntimes() {
  const { data: health } = useHealth()
  const online = health?.status === 'ok'

  return useQuery({
    queryKey: ['runtimes'],
    queryFn: api.runtimes,
    refetchInterval: online ? 10_000 : false,
    retry: false,
    enabled: online,
  })
}

export function useRecent(limit = 20) {
  const { data: health } = useHealth()
  const online = health?.status === 'ok'

  return useQuery({
    queryKey: ['recent', limit],
    queryFn: () => api.recent(limit),
    refetchInterval: online ? 5_000 : false,
    retry: false,
    enabled: online,
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

export function useConnectionInfo() {
  const { data: health } = useHealth()
  const online = health?.status === 'ok'

  return useQuery({
    queryKey: ['connectionInfo'],
    queryFn: api.connectionInfo,
    retry: false,
    enabled: online,
  })
}

export function useSettings() {
  const { data: health } = useHealth()
  const online = health?.status === 'ok'

  return useQuery({
    queryKey: ['settings'],
    queryFn: api.getSettings,
    retry: false,
    enabled: online,
  })
}
