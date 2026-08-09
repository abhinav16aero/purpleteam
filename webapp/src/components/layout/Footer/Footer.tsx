'use client'

import { ArrowUpCircle } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useVersionCheck } from '@/hooks/useVersionCheck'
import { SystemMeter } from '@/components/system/SystemMeter'
import styles from './Footer.module.css'

export function Footer() {
  const currentYear = new Date().getFullYear()
  const { currentVersion, latestVersion, updateAvailable } = useVersionCheck()
  const router = useRouter()

  return (
    <footer className={styles.footer}>
      <div className={styles.content}>
        <div className={styles.left}>
          <span className={styles.copyright}>
            © {currentYear} Swaraj Chakravyuh. All rights reserved.
          </span>
        </div>
        <div className={styles.right}>
          <SystemMeter />
          <div className={styles.versionWrapper}>
            {updateAvailable && latestVersion && (
              <button
                className={styles.updateBadge}
                onClick={() => router.push('/settings?tab=system')}
                title={`Update to v${latestVersion}`}
              >
                <ArrowUpCircle size={12} />
                v{latestVersion} available
              </button>
            )}
            <span className={styles.version}>v{currentVersion}</span>
          </div>
        </div>
      </div>
    </footer>
  )
}
