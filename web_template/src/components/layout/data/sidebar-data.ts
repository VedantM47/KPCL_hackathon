import {
  Factory,
  Fan,
  Snowflake,
  Gauge,
  Leaf,
  ListChecks,
  Radio,
  Droplets,
} from 'lucide-react'
import { type SidebarData } from '../types'

export const sidebarData: SidebarData = {
  user: {
    name: 'Control Room',
    email: 'energy-ops@kpcl.local',
    avatar: '/avatars/shadcn.jpg',
  },
  teams: [
    {
      name: 'KPCL Energy Ops',
      logo: Factory,
      plan: 'Benchmark-calibrated simulation',
    },
  ],
  navGroups: [
    {
      title: 'Plants',
      items: [
        {
          title: 'Live Monitor',
          url: '/live',
          icon: Radio,
        },
        {
          title: 'Plant Overview',
          url: '/',
          icon: Gauge,
        },
        {
          title: 'Compressor Room',
          url: '/compressor-room',
          icon: Fan,
        },
        {
          title: 'Refrigeration',
          url: '/refrigeration',
          icon: Snowflake,
        },
        {
          title: 'Production',
          url: '/production',
          icon: Factory,
        },
      ],
    },
    {
      title: 'Sustainability',
      items: [
        {
          title: 'Carbon & ESG',
          url: '/carbon',
          icon: Leaf,
        },
        {
          title: 'Loss Tracker',
          url: '/losses',
          icon: Droplets,
        },
        {
          title: 'Action Center',
          url: '/action-center',
          icon: ListChecks,
        },
      ],
    },
  ],
}
