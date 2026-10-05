import type { ReactNode } from "react"

import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"

export function PageHeader({
  title,
  description,
  actions,
  sample,
}: {
  title: string
  description?: string
  actions?: ReactNode
  sample?: boolean
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          {sample && <SampleBadge />}
        </div>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}

export function SampleBadge() {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Badge variant="outline" className="border-warning/40 font-mono text-[10px] text-warning">
          SAMPLE DATA
        </Badge>
      </TooltipTrigger>
      <TooltipContent>Illustrative data for the UI shell. Real data arrives with the agents.</TooltipContent>
    </Tooltip>
  )
}
