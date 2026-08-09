'use client'

import type { ReactNode } from 'react'
import Image from 'next/image'
// Guarded drop-in for next/link: consults the unsaved-changes guard before
// navigating, so header links prompt when a dirty form would lose edits.
import { GuardedLink as Link } from '@/components/GuardedLink'
import { usePathname } from 'next/navigation'
import { Crosshair, FolderOpen, Shield, TrendingUp, FileText, Settings, Users, GitBranch, Network } from 'lucide-react'
import { ThemeToggle } from '@/components/ThemeToggle'
import { ProjectSelector } from './ProjectSelector'
import { UserSelector } from './UserSelector'
import { useAuth } from '@/providers/AuthProvider'
import { useProject } from '@/providers/ProjectProvider'
import styles from './GlobalHeader.module.css'

/**
 * Compact top navigation bar. `label` is the (Indian-language) display name;
 * `title` is the English meaning surfaced as a hover tooltip. Related items are
 * clubbed into the central core-nav pill.
 */
export function GlobalHeader() {
  const pathname = usePathname()
  const { isAdmin } = useAuth()
  const { projectId } = useProject()

  const coreNav: Array<{ label: string; title: string; href: string; icon: ReactNode }> = [
    { label: 'Ranbhoomi', title: 'Red Zone', href: '/graph', icon: <Crosshair size={13} /> },
    ...(projectId
      ? [{ label: 'Anveshan', title: 'Recon Pipeline', href: `/projects/${projectId}/settings`, icon: <GitBranch size={13} /> }]
      : []),
    { label: 'Upchaar', title: 'CypherFix', href: '/cypherfix', icon: <Shield size={13} /> },
    { label: 'Drishti', title: 'Insights', href: '/insights', icon: <TrendingUp size={13} /> },
    { label: 'Pravah', title: 'TrafficMind', href: '/traffic', icon: <Network size={13} /> },
    { label: 'Prativedan', title: 'Reports', href: '/reports', icon: <FileText size={13} /> },
  ]

  return (
    <header className={styles.header}>
      <Link href="/graph" className={styles.logo} title="Swaraj Chakravyuh">
        <Image src="/logo.svg" alt="Swaraj Chakravyuh" width={22} height={22} className={styles.logoImg} />
        <span className={styles.logoText}>
          <span className={styles.logoAccent}>Swaraj</span> Chakravyuh
        </span>
      </Link>

      <div className={styles.spacer} />

      <div className={styles.actions}>
        <nav className={styles.coreNav}>
          {coreNav.map(item => {
            const isActive = pathname === item.href || pathname.startsWith(`${item.href}/`)
            return (
              <Link
                key={item.href}
                href={item.href}
                title={item.title}
                className={`${styles.coreNavItem} ${isActive ? styles.coreNavItemActive : ''}`}
              >
                {item.icon}
                <span>{item.label}</span>
              </Link>
            )
          })}
        </nav>

        <Link
          href="/projects"
          title="Projects"
          className={`${styles.navItem} ${pathname === '/projects' || pathname.startsWith('/projects/') ? styles.navItemActive : ''}`}
        >
          <FolderOpen size={13} />
          <span>Pariyojana</span>
        </Link>

        {isAdmin && (
          <Link
            href="/settings/users"
            title="Users"
            className={`${styles.navItem} ${pathname === '/settings/users' ? styles.navItemActive : ''}`}
          >
            <Users size={13} />
            <span>Sadasya</span>
          </Link>
        )}

        <div className={styles.divider} />
        <ProjectSelector />
        <div className={styles.divider} />
        <ThemeToggle />
        <div className={styles.divider} />
        <UserSelector />
        <div className={styles.divider} />

        <Link
          href="/settings"
          className={`${styles.helpLink} ${pathname === '/settings' ? styles.navItemActive : ''}`}
          title="Settings"
        >
          <Settings size={15} />
        </Link>
      </div>
    </header>
  )
}
