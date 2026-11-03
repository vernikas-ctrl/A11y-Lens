import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import AccessGate from './access/AccessGate.tsx'

// The gate wraps the app here rather than inside App, so that nothing the app
// renders can be reached without passing it. `children` is not constructed at
// all until the backend has confirmed a code -- task 8.0's "a fresh browser
// sees only the code prompt" means nothing in the page, not hidden with CSS.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AccessGate>
      <App />
    </AccessGate>
  </StrictMode>,
)
