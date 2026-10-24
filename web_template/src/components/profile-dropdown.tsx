import { Badge } from '@/components/ui/badge'

// This is an internal control-room dashboard with no real user accounts, so
// the template's profile/sign-out dropdown is replaced with a static data
// provenance badge instead of a fake user menu with dead links.
export function ProfileDropdown() {
  return (
    <Badge
      variant='outline'
      className='hidden shrink-0 border-amber-500/40 text-[11px] font-medium text-amber-600 sm:inline-flex dark:text-amber-400'
    >
      Simulated data
    </Badge>
  )
}
