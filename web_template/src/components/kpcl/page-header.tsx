import { type ReactNode } from 'react'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { PlantSwitcher } from '@/components/kpcl/plant-switcher'

type PageHeaderProps = {
  title: string
  description?: string
  actions?: ReactNode
  children: ReactNode
}

// Shared chrome for every KPCL view: top bar (search/theme/data badge) +
// a dense page title row + the page body.
export function PageShell({ title, description, actions, children }: PageHeaderProps) {
  return (
    <>
      <Header>
        <div className='ms-2 font-mono text-xs text-muted-foreground'>KPCL Energy Ops</div>
        <PlantSwitcher />
        <Search />
        <div className='ms-auto flex items-center gap-2'>
          <ThemeSwitch />
          <ProfileDropdown />
        </div>
      </Header>
      <Main>
        <div className='mb-4 flex flex-wrap items-end justify-between gap-2'>
          <div>
            <h1 className='text-xl font-semibold tracking-tight'>{title}</h1>
            {description && <p className='text-muted-foreground mt-0.5 text-sm'>{description}</p>}
          </div>
          {actions && <div className='flex flex-wrap items-center gap-2'>{actions}</div>}
        </div>
        {children}
      </Main>
    </>
  )
}
