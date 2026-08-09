'use client'

interface WikiInfoButtonProps {
  /** Wiki key or a fully-qualified https URL. */
  target: string
  /** Optional label rendered next to the icon. */
  label?: string
  /** Override the tooltip. */
  title?: string
  /** Icon size (px). */
  size?: number
  /** Extra class names. */
  className?: string
  /** Stop click propagation so collapsible section headers don't toggle. */
  stopPropagation?: boolean
}

// Wiki links to the upstream repository are disabled in this internal build.
// The component is kept as a no-op so existing call sites still type-check.
export function WikiInfoButton(_props: WikiInfoButtonProps) {
  return null
}
