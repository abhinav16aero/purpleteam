import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { ThemeProvider } from './contexts/ThemeContext'
import { basePath } from './config/basePath'

// TEMP DIAGNOSTIC: paint any uncaught runtime error onto the page instead of showing a blank white
// screen (CSP-safe — DOM only, no inline script). Remove once the console is loading.
if (typeof window !== 'undefined') {
  const paint = (title: string, detail: string) => {
    const el = document.getElementById('root')
    if (el) el.innerHTML =
      '<pre style="white-space:pre-wrap;color:#e05561;background:#0b0e14;padding:24px 28px;margin:0;'
      + 'min-height:100vh;font:13px/1.5 ui-monospace,monospace">RUNTIME ERROR — ' + title + '\n\n'
      + String(detail).replace(/[&<]/g, (c) => (c === '&' ? '&amp;' : '&lt;')) + '</pre>'
  }
  window.addEventListener('error', (e) => paint('window.onerror', (e.error && e.error.stack) || e.message))
  window.addEventListener('unhandledrejection', (e) =>
    paint('unhandledrejection', (e.reason && (e.reason.stack || e.reason.message)) || String(e.reason)))
}

try {
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <BrowserRouter basename={basePath}>
        <ThemeProvider>
          <App />
        </ThemeProvider>
      </BrowserRouter>
    </React.StrictMode>,
  )
} catch (err) {
  const el = document.getElementById('root')
  if (el) el.textContent = 'MOUNT ERROR: ' + ((err as Error)?.stack || err)
}
