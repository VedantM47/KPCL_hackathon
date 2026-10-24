import { Building2 } from 'lucide-react'
import { usePlant } from '@/context/plant-context'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

// Global plant selector: every page and API call follows it. "All plants" is the
// company roll-up (the original main meter); each plant has its own meter, contract
// demand, emissions, forecast and schedule.
export function PlantSwitcher() {
  const { plant, setPlant, plants } = usePlant()
  return (
    <Select value={plant} onValueChange={setPlant}>
      <SelectTrigger size='sm' className='w-52 gap-2 text-xs' aria-label='Select plant'>
        <Building2 className='text-muted-foreground size-3.5 shrink-0' />
        <SelectValue placeholder='All plants' />
      </SelectTrigger>
      <SelectContent>
        {plants.map((p) => (
          <SelectItem key={p.plant_id} value={p.plant_id}>
            {p.name}
            {p.city ? <span className='text-muted-foreground'> · {p.city}</span> : null}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
