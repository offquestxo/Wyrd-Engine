import { notFound } from "next/navigation"

import { ComponentPreview } from "./preview"

export const metadata = { title: "Components (dev)" }

/** Dev-only gallery of the redesign's shared components on real engine data. 404 in production. */
export default function Page() {
  if (process.env.NODE_ENV === "production") notFound()
  return <ComponentPreview />
}
