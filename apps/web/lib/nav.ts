import {
  BookOpenTextIcon,
  FlameIcon,
  HouseIcon,
  LayersIcon,
  type LucideIcon,
  MessageSquareIcon,
  SettingsIcon,
} from "lucide-react"

export interface NavItem {
  href: string
  label: string
  icon: LucideIcon
  /** second key of the "g then <key>" shortcut */
  key: string
}

export const NAV: NavItem[] = [
  { href: "/", label: "Home", icon: HouseIcon, key: "h" },
  { href: "/chat", label: "Chat", icon: MessageSquareIcon, key: "c" },
  { href: "/stories", label: "Stories", icon: LayersIcon, key: "s" },
  { href: "/research", label: "Research", icon: BookOpenTextIcon, key: "r" },
  { href: "/outliers", label: "Outliers", icon: FlameIcon, key: "o" },
  { href: "/settings", label: "Settings", icon: SettingsIcon, key: "," },
]

export const AGENT_INFO = [
  { name: "scout", description: "Find and score new story leads" },
  { name: "outlier", description: "Find competitor videos beating their median" },
  { name: "researcher", description: "Build a sourced research dossier" },
] as const
