import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { ThemeProvider } from './contexts/ThemeContext'
import { basePath } from './config/basePath'

// Non-destructive error surfacing. A render-phase error is caught by RootErrorBoundary (below) and
// shown THROUGH React, so React keeps owning #root. A load/async error is shown by appending an
// overlay to <body> — NEVER to #root. (The previous diagnostic wrote to #root.innerHTML on error,
// which yanked the DOM out from under React and produced the confusing
// "removeChild … not a child of this node" cascade in commitDeletionEffectsOnFiber.)
if (typeof window !== 'undefined') {
  const overlay = (title: string, detail: string) => {
    const d = document.createElement('div')
    d.setAttribute('data-error-overlay', '')
    d.style.cssText =
      'position:fixed;left:0;right:0;bottom:0;max-height:45vh;overflow:auto;z-index:99999;' +
      'background:#0b0e14;color:#f87171;padding:14px 18px;margin:0;white-space:pre-wrap;' +
      'font:12.5px/1.5 ui-monospace,SFMono-Regular,monospace;border-top:2px solid #f87171'
    d.textContent = 'RUNTIME ERROR — ' + title + '\n\n' + detail
    document.body.appendChild(d) // sibling of #root; React never manages this node
  }
  window.addEventListener('error', (e) =>
    overlay('window.onerror', (e.error && e.error.stack) || e.message))
  window.addEventListener('unhandledrejection', (e) =>
    overlay('unhandledrejection', (e.reason && (e.reason.stack || e.reason.message)) || String(e.reason)))
}

class RootErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null }
  static getDerivedStateFromError(error: Error) {
    return { error }
  }
  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error('Console render error:', error, info.componentStack)
  }
  render() {
    if (this.state.error) {
      return (
        <pre
          style={{
            whiteSpace: 'pre-wrap',
            color: '#f87171',
            background: '#0b0e14',
            padding: '24px 28px',
            margin: 0,
            minHeight: '100vh',
            font: '13px/1.5 ui-monospace, SFMono-Regular, monospace',
          }}
        >
          {'RENDER ERROR\n\n' + (this.state.error.stack || String(this.state.error))}
        </pre>
      )
    }
    return this.props.children
  }
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <RootErrorBoundary>
      <BrowserRouter basename={basePath}>
        <ThemeProvider>
          <App />
        </ThemeProvider>
      </BrowserRouter>
    </RootErrorBoundary>
  </React.StrictMode>,
)
