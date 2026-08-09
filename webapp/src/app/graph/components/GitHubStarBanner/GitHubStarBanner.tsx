'use client'

interface GitHubStarBannerProps {
  hasAttackChain: boolean
}

// The upstream-repo "star us on GitHub" banner is removed in this internal
// build. Kept as a no-op so the call site still type-checks.
export function GitHubStarBanner(_props: GitHubStarBannerProps) {
  return null
}
