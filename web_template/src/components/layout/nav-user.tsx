import { SidebarMenu, SidebarMenuItem } from '@/components/ui/sidebar'

type NavUserProps = {
  user: {
    name: string
    email: string
  }
}

// This is an internal control-room dashboard with no real accounts, so the
// template's account/billing/sign-out menu is replaced with a static
// data-provenance line instead of dead links to a deleted settings section.
export function NavUser({ user }: NavUserProps) {
  return (
    <SidebarMenu>
      <SidebarMenuItem className='px-2 py-1.5'>
        <p className='truncate text-xs font-medium text-sidebar-foreground'>{user.name}</p>
        <p className='truncate text-[11px] text-muted-foreground'>{user.email}</p>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}
