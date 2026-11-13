import { Cpu, LayoutDashboard, LockKeyhole, Moon, Settings2, Sun, Users } from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'

import { setAccessCode } from '@/api/client'
import { useTheme } from '@/lib/theme'
import { cn } from '@/lib/utils'

const NAV = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/campaigns', label: 'Campaigns', icon: Users, end: false },
  { to: '/setup', label: 'Seller profile', icon: Settings2, end: false },
  { to: '/models', label: 'Models', icon: Cpu, end: false },
]

export function AppShell() {
  const { theme, toggle } = useTheme()
  return (
    <div className="grid min-h-svh grid-cols-[232px_1fr]">
      <aside className="border-r border-sidebar-border bg-sidebar">
        <div className="sticky top-0 flex h-svh flex-col px-3 py-5">
          <div className="px-2 pb-7">
            <Wordmark />
          </div>
          <nav className="flex flex-col gap-0.5" aria-label="Main">
            {NAV.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-sidebar-foreground/75 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground',
                    isActive && 'bg-sidebar-accent font-medium text-sidebar-foreground',
                  )
                }
              >
                <Icon className="size-4" aria-hidden />
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="mt-auto flex flex-col gap-0.5 text-sm">
            <button
              type="button"
              onClick={toggle}
              className="flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sidebar-foreground/75 hover:bg-sidebar-accent hover:text-sidebar-foreground"
            >
              {theme === 'dark' ? <Sun className="size-4" /> : <Moon className="size-4" />}
              {theme === 'dark' ? 'Light theme' : 'Dark theme'}
            </button>
            <button
              type="button"
              onClick={() => {
                setAccessCode(null)
                window.dispatchEvent(new Event('lede:locked'))
              }}
              className="flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sidebar-foreground/75 hover:bg-sidebar-accent hover:text-sidebar-foreground"
            >
              <LockKeyhole className="size-4" />
              Lock
            </button>
          </div>
        </div>
      </aside>
      <main className="min-w-0 px-10 py-8">
        <Outlet />
      </main>
    </div>
  )
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn('flex items-center gap-2 text-[0.95rem] font-semibold', className)}>
      <span aria-hidden className="evidence-mark font-serif text-lg leading-none">
        L
      </span>
      Lede
    </span>
  )
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string
  description?: React.ReactNode
  actions?: React.ReactNode
}) {
  return (
    <header className="mb-7 flex items-end justify-between gap-6">
      <div className="min-w-0">
        <h1>{title}</h1>
        {description && <p className="mt-1.5 max-w-2xl text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </header>
  )
}
