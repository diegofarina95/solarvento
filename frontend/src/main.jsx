import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { purgeBillSession } from './api.js'

// Privacidad: al cerrar la pestaña se purgan las facturas cacheadas de la
// sesión. Si la página va a la bfcache (persisted) puede volver, no se purga.
window.addEventListener('pagehide', (event) => {
  if (!event.persisted) purgeBillSession()
})

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
