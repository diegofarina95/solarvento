import { useEffect, useRef } from 'react'

// Hueco de publicidad (Google AdSense). No renderiza NADA hasta que se
// configure un cliente en el build:
//   VITE_ADSENSE_CLIENT=ca-pub-XXXXXXXXXXXXXXXX npm run build
// y opcionalmente un slot por hueco (VITE_ADSENSE_SLOT_TOP, _RESULTS, _FOOTER).
// Así la web funciona igual hoy y basta un rebuild para activar anuncios
// cuando esté en su dominio definitivo.
const ADS_CLIENT = import.meta.env.VITE_ADSENSE_CLIENT
const SLOTS = {
  top: import.meta.env.VITE_ADSENSE_SLOT_TOP,
  results: import.meta.env.VITE_ADSENSE_SLOT_RESULTS,
  footer: import.meta.env.VITE_ADSENSE_SLOT_FOOTER,
}

let scriptInjected = false

function ensureAdsScript() {
  if (scriptInjected || !ADS_CLIENT) return
  scriptInjected = true
  const script = document.createElement('script')
  script.async = true
  script.src = `https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${ADS_CLIENT}`
  script.crossOrigin = 'anonymous'
  document.head.appendChild(script)
}

export default function AdSlot({ placement }) {
  const ref = useRef(null)
  const slot = SLOTS[placement]
  const enabled = Boolean(ADS_CLIENT && slot)

  useEffect(() => {
    if (!enabled || !ref.current) return
    ensureAdsScript()
    try {
      ;(window.adsbygoogle = window.adsbygoogle || []).push({})
    } catch {
      /* bloqueadores de anuncios: silencioso */
    }
  }, [enabled])

  if (!enabled) return null

  return (
    <div className="my-4 print:hidden" aria-hidden="true">
      <ins
        ref={ref}
        className="adsbygoogle"
        style={{ display: 'block' }}
        data-ad-client={ADS_CLIENT}
        data-ad-slot={slot}
        data-ad-format="auto"
        data-full-width-responsive="true"
      />
    </div>
  )
}
