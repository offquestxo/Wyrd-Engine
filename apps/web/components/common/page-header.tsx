import type { ReactNode } from "react"

/** Style A page header (data pages): optional mono eyebrow, 34px title, one-line description. */
export function PageHeader({
  title,
  description,
  eyebrow,
  actions,
}: {
  title: ReactNode
  description?: ReactNode
  eyebrow?: ReactNode
  actions?: ReactNode
}) {
  return (
    <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
      <div className="flex min-w-0 flex-col gap-1.5">
        {eyebrow && <span className="num text-[11.5px] tracking-[1.4px] text-subtle-foreground uppercase">{eyebrow}</span>}
        <h1 className="text-[32px] leading-tight font-semibold tracking-[-0.8px] md:text-[34px]">{title}</h1>
        {description && <p className="max-w-2xl text-[14.5px] text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}
