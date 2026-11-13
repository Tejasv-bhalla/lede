import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './client'
import type {
  Campaign,
  CampaignCheck,
  Contact,
  CsvPreview,
  Dashboard,
  ModelChoice,
  ModelRole,
  ModelSettings,
  ModelTest,
  ProviderId,
  Prospect,
  ProspectInput,
  Review,
  RunDetail,
  RunState,
  SellerProfile,
  Tier,
} from './types'

export const keys = {
  profile: ['profile'] as const,
  campaigns: ['campaigns'] as const,
  campaign: (id: string) => ['campaigns', id] as const,
  check: (id: string) => ['campaigns', id, 'check'] as const,
  prospects: (id: string) => ['campaigns', id, 'prospects'] as const,
  runs: ['runs'] as const,
  run: (id: string) => ['runs', id] as const,
  dashboard: ['dashboard'] as const,
  models: ['models'] as const,
}

export function useProfile() {
  return useQuery({
    queryKey: keys.profile,
    queryFn: () => api.get<SellerProfile>('/profile'),
    retry: (count, err) => (err as { status?: number }).status !== 404 && count < 2,
  })
}

export function useSaveProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (p: SellerProfile) => api.put<{ version: number }>('/profile', p),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.profile }),
  })
}

export function useCampaigns() {
  return useQuery({ queryKey: keys.campaigns, queryFn: () => api.get<Campaign[]>('/campaigns') })
}

export function useCampaign(id: string) {
  return useQuery({
    queryKey: keys.campaign(id),
    queryFn: () => api.get<Campaign>(`/campaigns/${id}`),
    // A new campaign has no id; '/campaigns/' would redirect to the list.
    enabled: Boolean(id),
  })
}

export function useSaveCampaign() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (c: Partial<Campaign>) =>
      c.id ? api.put<Campaign>(`/campaigns/${c.id}`, c) : api.post<Campaign>('/campaigns', c),
    onSuccess: (saved) => {
      qc.invalidateQueries({ queryKey: keys.campaigns })
      qc.invalidateQueries({ queryKey: keys.check(saved.id) })
    },
  })
}

export function useCampaignCheck(id: string | undefined, enabled = true) {
  return useQuery({
    queryKey: keys.check(id ?? ''),
    queryFn: () => api.post<CampaignCheck>(`/campaigns/${id}/validate`),
    enabled: Boolean(id) && enabled,
  })
}

export function useProspects(campaignId: string) {
  return useQuery({
    queryKey: keys.prospects(campaignId),
    queryFn: () => api.get<Prospect[]>(`/campaigns/${campaignId}/prospects`),
    // Keep last-run status fresh while runs are in flight.
    refetchInterval: (q) =>
      q.state.data?.some((p) => p.last_run?.state === 'RUNNING') ? 4000 : false,
  })
}

export function useAddProspect(campaignId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (p: ProspectInput) => api.post<Prospect>(`/campaigns/${campaignId}/prospects`, p),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.prospects(campaignId) }),
  })
}

export function useImportCsv(campaignId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ file, dryRun }: { file: File; dryRun: boolean }) => {
      const form = new FormData()
      form.append('file', file)
      return api.post<CsvPreview>(`/campaigns/${campaignId}/prospects/csv?dry_run=${dryRun}`, form)
    },
    onSuccess: (_, { dryRun }) => {
      if (!dryRun) qc.invalidateQueries({ queryKey: keys.prospects(campaignId) })
    },
  })
}

export function useStartRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { prospect_id: number; tier: Tier; pinned_identity?: Contact }) =>
      api.post<{ run_id: string }>('/runs', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.runs })
      qc.invalidateQueries({ queryKey: ['campaigns'] })
    },
  })
}

export function useRuns(filters: { campaign_id?: string; state?: RunState } = {}) {
  const params = new URLSearchParams(
    Object.entries(filters).filter(([, v]) => v) as [string, string][],
  )
  return useQuery({
    queryKey: [...keys.runs, filters],
    queryFn: () => api.get<(RunDetail & { prospect: ProspectInput })[]>(`/runs?${params}`),
  })
}

export function useRun(id: string) {
  return useQuery({ queryKey: keys.run(id), queryFn: () => api.get<RunDetail>(`/runs/${id}`) })
}

export function useReview(runId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      action: 'approve' | 'edit' | 'reject'
      subject?: string
      body?: string
      reason?: string
    }) => api.post<Review>(`/runs/${runId}/review`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.run(runId) })
      qc.invalidateQueries({ queryKey: keys.dashboard })
    },
  })
}

export function useDashboard() {
  return useQuery({ queryKey: keys.dashboard, queryFn: () => api.get<Dashboard>('/dashboard') })
}

// ── model settings ──────────────────────────────────────────────────────────

export function useModels() {
  return useQuery({ queryKey: keys.models, queryFn: () => api.get<ModelSettings>('/models') })
}

function useModelMutation<V>(fn: (v: V) => Promise<ModelSettings>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (data) => qc.setQueryData(keys.models, data),
  })
}

export function useSaveKey() {
  return useModelMutation((v: { provider: ProviderId; api_key: string; base_url?: string }) =>
    api.put<ModelSettings>(`/models/keys/${v.provider}`, {
      api_key: v.api_key,
      base_url: v.base_url || null,
    }),
  )
}

export function useRemoveKey() {
  return useModelMutation((provider: ProviderId) =>
    api.del<ModelSettings>(`/models/keys/${provider}`),
  )
}

export function useSaveRoles() {
  return useModelMutation((roles: Partial<Record<ModelRole, ModelChoice | null>>) =>
    api.put<ModelSettings>('/models/roles', roles),
  )
}

export function useTestModel() {
  return useMutation({
    mutationFn: (choice: ModelChoice) => api.post<ModelTest>('/models/test', choice),
  })
}
