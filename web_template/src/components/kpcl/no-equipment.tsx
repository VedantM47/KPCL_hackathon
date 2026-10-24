import { usePlant } from '@/context/plant-context'
import { Card, CardContent } from '@/components/ui/card'

// Shown when the selected plant doesn't own the equipment a page is about — better than
// quietly showing another site's machines under this plant's name.
export function NoEquipment({ what }: { what: string }) {
  const { info, setPlant } = usePlant()
  return (
    <Card>
      <CardContent className='py-10 text-center text-sm'>
        <p className='font-medium'>{info?.name ?? 'This plant'} has no {what}.</p>
        <p className='text-muted-foreground mt-1 text-xs'>
          Equipment is assigned to plants in config.yaml.{' '}
          <button className='underline underline-offset-2' onClick={() => setPlant('ALL')}>
            Show all plants
          </button>
        </p>
      </CardContent>
    </Card>
  )
}
