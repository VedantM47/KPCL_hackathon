import { type ReactNode, useState } from 'react'
import { Info } from 'lucide-react'
import { type Explanation, SIMULATED } from '@/lib/chart-insights'
import { cn } from '@/lib/utils'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'

export type ExplainSource = Explanation | (() => Explanation)

// Controls inside a chart keep their own click behaviour (unit toggles, plant rows, pickers).
const INTERACTIVE = 'button, a, input, select, textarea, [role="combobox"], [role="tab"], [data-no-explain]'

// Wraps any chart or diagram: clicking it (or the ⓘ in its corner) opens a card saying what the
// chart shows, how to read it, and what the data currently on screen implies. The explanation is
// built when the card opens, so it always describes the data being displayed right now.
export function ChartExplainer({
  explain,
  children,
  className,
}: {
  explain: ExplainSource
  children: ReactNode
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const [content, setContent] = useState<Explanation | null>(null)

  const show = () => {
    setContent(typeof explain === 'function' ? explain() : explain)
    setOpen(true)
  }

  return (
    <>
      {/* mouse: click anywhere on the chart; keyboard / screen reader: the ⓘ button */}
      <div
        className={cn('group/explain relative cursor-pointer', className)}
        onClick={(e) => {
          // React bubbles clicks out of portals (select menus, popovers) to here: only count clicks
          // that physically landed on the chart
          if (!e.currentTarget.contains(e.target as Node)) return
          if ((e.target as HTMLElement).closest(INTERACTIVE)) return
          show()
        }}
      >
        {children}
        <button
          type='button'
          aria-label='Explain this chart'
          onClick={show}
          className='absolute top-0 right-0 z-10 flex items-center gap-1 rounded-full border border-border bg-background/90 px-1.5 py-0.5 text-[10px] text-muted-foreground opacity-60 shadow-xs transition-opacity group-hover/explain:opacity-100 focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'
        >
          <Info className='size-3' />
          <span className='hidden group-hover/explain:inline'>What does this show?</span>
        </button>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className='max-h-[85vh] overflow-y-auto sm:max-w-lg'>
          {content && (
            <>
              <DialogHeader>
                <DialogTitle className='text-base'>{content.title}</DialogTitle>
                <DialogDescription className='text-foreground/90 text-sm leading-relaxed'>{content.shows}</DialogDescription>
              </DialogHeader>
              {content.read && (
                <section>
                  <h3 className='text-muted-foreground mb-1 text-[11px] font-semibold tracking-wide uppercase'>How to read it</h3>
                  <p className='text-sm leading-relaxed'>{content.read}</p>
                </section>
              )}
              <section>
                <h3 className='text-muted-foreground mb-1 text-[11px] font-semibold tracking-wide uppercase'>
                  What the data says
                </h3>
                {content.says.length ? (
                  <ul className='list-disc space-y-1.5 pl-5 text-sm leading-relaxed'>
                    {content.says.map((s, i) => (
                      <li key={i}>{s}</li>
                    ))}
                  </ul>
                ) : (
                  <p className='text-muted-foreground text-sm'>No data is loaded yet.</p>
                )}
              </section>
              <p className='text-muted-foreground border-t pt-2 text-[11px]'>{SIMULATED}</p>
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  )
}
