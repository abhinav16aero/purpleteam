import { useEffect, useRef, useState } from 'react'
import { X, Terminal, CheckCircle, AlertCircle, Pause, Play, Trash2, Square, Loader2, Download } from 'lucide-react'
import type { ReconLogEvent, ReconStatus } from './types'
import { COORDINATOR_PHASES } from './coordinatorGraph'

interface ReconLogsDrawerProps {
  isOpen: boolean
  onClose: () => void
  logs: ReconLogEvent[]
  currentPhase: string | null
  currentPhaseNumber: number | null
  status: ReconStatus
  onClearLogs: () => void
  onPause?: () => void
  onResume?: () => void
  onStop?: () => void
  title?: string
  phases?: readonly string[]
  totalPhases?: number
  errorMessage?: string | null
  hidePhaseProgress?: boolean
}

export function ReconLogsDrawer({
  isOpen,
  onClose,
  logs,
  currentPhase,
  currentPhaseNumber,
  status,
  onClearLogs,
  onPause,
  onResume,
  onStop,
  title = 'Reconnaissance Logs',
  phases = COORDINATOR_PHASES,
  totalPhases = COORDINATOR_PHASES.length,
  errorMessage,
  hidePhaseProgress = false,
}: ReconLogsDrawerProps) {
  const logsEndRef = useRef<HTMLDivElement>(null)
  const logsContainerRef = useRef<HTMLDivElement>(null)
  const [autoScroll, setAutoScroll] = useState(true)

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (autoScroll && logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs, autoScroll])

  // Detect manual scroll to disable auto-scroll
  const handleScroll = () => {
    if (!logsContainerRef.current) return
    const { scrollTop, scrollHeight, clientHeight } = logsContainerRef.current
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 50
    setAutoScroll(isAtBottom)
  }

  const getStatusIcon = () => {
    switch (status) {
      case 'running':
      case 'starting':
        return <div className="ra-drawer-running" />
      case 'paused':
        return <Pause size={14} className="ra-drawer-paused" />
      case 'pausing':
      case 'stopping':
        return <Loader2 size={14} className="ra-drawer-spinner" />
      case 'completed':
        return <CheckCircle size={14} className="ra-drawer-success" />
      case 'error':
        return <AlertCircle size={14} className="ra-drawer-error" />
      default:
        return <Terminal size={14} />
    }
  }

  const getStatusText = () => {
    switch (status) {
      case 'starting':
        return 'Starting...'
      case 'running':
        if (!currentPhase) return 'Running...'
        return hidePhaseProgress
          ? `Scanning: ${currentPhase}`
          : `Phase ${currentPhaseNumber}/${totalPhases}: ${currentPhase}`
      case 'paused':
        if (!currentPhase) return 'Paused'
        return hidePhaseProgress
          ? `Paused: ${currentPhase}`
          : `Paused - Phase ${currentPhaseNumber}/${totalPhases}: ${currentPhase}`
      case 'completed':
        return 'Completed'
      case 'error':
        return errorMessage ? `Error: ${errorMessage}` : 'Error'
      case 'pausing':
        return 'Pausing...'
      case 'stopping':
        return 'Stopping...'
      default:
        return 'Idle'
    }
  }

  const handleDownloadLogs = () => {
    if (logs.length === 0) return

    const lines = logs.map(log => {
      const ts = new Date(log.timestamp).toISOString()
      const level = log.level.toUpperCase().padEnd(7)
      const phase = log.phase ? ` [${log.phase}]` : ''
      return `${ts}  ${level}${phase}  ${log.log}`
    })

    // Add header
    const header = [
      `# ${title}`,
      `# Status: ${status}`,
      `# Phase: ${currentPhase || 'N/A'} (${currentPhaseNumber || 0}/${totalPhases})`,
      `# Exported: ${new Date().toISOString()}`,
      `# Total lines: ${logs.length}`,
      '',
    ]

    const content = [...header, ...lines].join('\n')
    const blob = new Blob([content], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    // Sanitize title for filename
    const safeName = title.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/_+$/, '')
    a.download = `${safeName}_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.log`
    a.click()
    URL.revokeObjectURL(url)
  }

  const getLogClassName = (level: string) => {
    switch (level) {
      case 'error':
        return 'ra-log-error'
      case 'warning':
        return 'ra-log-warning'
      case 'success':
        return 'ra-log-success'
      case 'action':
        return 'ra-log-action'
      default:
        return 'ra-log-info'
    }
  }

  // Highlight the union target-list breakdown emitted by build_target_urls
  const isTargetsLine = (logText: string) =>
    logText.includes('[Targets]') &&
    (logText.includes('Merged ') || logText.includes('No targets'))

  // Memory governor (Part 5): "[RESOURCE-CAP] <tool> <PARAM> <env> -> <eff> ..."
  const isResourceCapLine = (logText: string) => logText.includes('[RESOURCE-CAP]')

  return (
    <div className={`ra-drawer${isOpen ? ' ra-drawer-open' : ''}`}>
      {/* Header */}
      <div className="ra-drawer-header">
        <div className="ra-drawer-title">
          <Terminal size={16} />
          <span>{title}</span>
        </div>
        <button
          className="ra-drawer-close"
          onClick={onClose}
          aria-label="Close drawer"
        >
          <X size={16} />
        </button>
      </div>

      {/* Status bar */}
      <div className="ra-drawer-statusbar">
        <div className="ra-drawer-statusleft">
          {getStatusIcon()}
          <span className="ra-drawer-statustext" title={getStatusText()}>{getStatusText()}</span>
        </div>
        <div className="ra-drawer-statusactions">
          {(status === 'running' || status === 'paused' || status === 'pausing') && (
            <button
              className={`ra-drawer-iconbtn${status === 'paused' ? ' ra-drawer-iconbtn-paused' : ''}`}
              onClick={status === 'paused' ? onResume : onPause}
              disabled={status === 'pausing'}
              title={status === 'pausing' ? 'Pausing...' : status === 'paused' ? 'Resume pipeline' : 'Pause pipeline'}
            >
              {status === 'pausing'
                ? <Loader2 size={14} className="ra-drawer-spinner" />
                : status === 'paused' ? <Play size={14} /> : <Pause size={14} />}
            </button>
          )}
          {(status === 'running' || status === 'paused' || status === 'pausing') && (
            <button
              className="ra-drawer-iconbtn ra-drawer-iconbtn-stop"
              onClick={onStop}
              title="Stop pipeline"
            >
              <Square size={14} />
            </button>
          )}
          <button
            className="ra-drawer-iconbtn"
            onClick={handleDownloadLogs}
            disabled={logs.length === 0}
            title="Download logs"
          >
            <Download size={14} />
          </button>
          <button
            className="ra-drawer-iconbtn"
            onClick={onClearLogs}
            title="Clear logs"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {/* Phase progress (hidden for single-phase partial recon) */}
      {!hidePhaseProgress && (
        <div className="ra-drawer-phaseprogress">
          {phases.map((phase, index) => {
            const phaseNum = index + 1
            const isActive = currentPhaseNumber === phaseNum
            const isCompleted = currentPhaseNumber !== null && phaseNum < currentPhaseNumber
            const isPending = currentPhaseNumber === null || phaseNum > currentPhaseNumber

            return (
              <div
                key={phase}
                className={`ra-drawer-phaseitem ${isActive ? 'ra-drawer-phase-active' : ''} ${isCompleted ? 'ra-drawer-phase-completed' : ''} ${isPending ? 'ra-drawer-phase-pending' : ''}`}
                title={phase}
              >
                <span className="ra-drawer-phasenumber">{phaseNum}</span>
              </div>
            )
          })}
        </div>
      )}

      {/* Logs container */}
      <div
        ref={logsContainerRef}
        className="ra-drawer-logs"
        onScroll={handleScroll}
      >
        {logs.length === 0 ? (
          <div className="ra-drawer-emptylogs">
            <Terminal size={24} />
            <p>Waiting for logs...</p>
          </div>
        ) : (
          <>
            {logs.map((log, index) => (
              <div
                key={index}
                className={`ra-log-line ${getLogClassName(log.level)}${
                  isTargetsLine(log.log) ? ' ra-log-targets' : ''
                }${isResourceCapLine(log.log) ? ' ra-log-resourcecap' : ''}`}
              >
                <span className="ra-log-timestamp">
                  {new Date(log.timestamp).toLocaleTimeString()}
                </span>
                <span className="ra-log-message">{log.log}</span>
              </div>
            ))}
            <div ref={logsEndRef} />
          </>
        )}
      </div>

      {/* Auto-scroll indicator */}
      {!autoScroll && (
        <button
          className="ra-drawer-scrolltobottom"
          onClick={() => {
            setAutoScroll(true)
            logsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
          }}
        >
          Scroll to bottom
        </button>
      )}
    </div>
  )
}

export default ReconLogsDrawer