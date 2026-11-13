import { Suspense, lazy, useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { getAccessCode } from './api/client'
import { AppShell } from './components/app-shell'
import { Skeleton } from './components/ui/skeleton'
import { AccessGate } from './pages/access-gate'

// Pages load on demand: the charting library only ships with the overview.
const Overview = lazy(() => import('./pages/overview').then((m) => ({ default: m.Overview })))
const Setup = lazy(() => import('./pages/setup').then((m) => ({ default: m.Setup })))
const Campaigns = lazy(() => import('./pages/campaigns').then((m) => ({ default: m.Campaigns })))
const CampaignWorkspace = lazy(() =>
  import('./pages/campaign-workspace').then((m) => ({ default: m.CampaignWorkspace })),
)
const RunPage = lazy(() => import('./pages/run-page').then((m) => ({ default: m.RunPage })))

export function App() {
  const [unlocked, setUnlocked] = useState(() => Boolean(getAccessCode()))

  useEffect(() => {
    const lock = () => setUnlocked(false)
    window.addEventListener('std:locked', lock)
    return () => window.removeEventListener('std:locked', lock)
  }, [])

  if (!unlocked) return <AccessGate onUnlock={() => setUnlocked(true)} />

  return (
    <Suspense fallback={<Skeleton className="m-10 h-80 max-w-5xl" />}>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<Overview />} />
          <Route path="setup" element={<Setup />} />
          <Route path="campaigns" element={<Campaigns />} />
          <Route path="campaigns/:campaignId" element={<CampaignWorkspace />} />
          <Route path="runs/:runId" element={<RunPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </Suspense>
  )
}
