// Firma visual de SolVento: el arco diario del astro sobre el horizonte. El sol
// recorre el arco según la hora local (amanecer→izquierda, mediodía→cénit,
// atardecer→derecha); de noche sale la luna recorriendo el arco nocturno. Puro
// SVG; se refresca cada minuto. Sin dependencias ni cambios en el resto de la web.
import { useEffect, useState } from 'react'

// Curva del sol (misma Bézier cuadrática que dibuja el arco): P0→P1→P2.
const P0 = [20, 88]
const P1 = [320, -55]
const P2 = [620, 88]
const SUNRISE = 7 // hora local aproximada de amanecer
const SUNSET = 21 // hora local aproximada de atardecer
const NOON = 13 // cénit: mediodía solar aprox. en España (el sol arriba a media jornada)

function bezier(t) {
  const u = 1 - t
  const x = u * u * P0[0] + 2 * u * t * P1[0] + t * t * P2[0]
  const y = u * u * P0[1] + 2 * u * t * P1[1] + t * t * P2[1]
  return [x, y]
}

// Posición del astro y si es de día, a partir de una fecha local. Pura (testable).
// De día el mapeo es a trozos para que el MEDIODÍA quede en el cénit (t=0.5),
// aunque amanecer/atardecer no sean simétricos respecto al mediodía.
export function celestialPosition(date) {
  const hour = date.getHours() + date.getMinutes() / 60
  const isDay = hour >= SUNRISE && hour < SUNSET
  let t
  if (isDay) {
    t =
      hour <= NOON
        ? 0.5 * ((hour - SUNRISE) / (NOON - SUNRISE))
        : 0.5 + 0.5 * ((hour - NOON) / (SUNSET - NOON))
  } else {
    // La noche va de SUNSET a SUNRISE del día siguiente; la luna recorre el arco.
    const nightLength = 24 - (SUNSET - SUNRISE)
    const sinceSunset = (hour - SUNSET + 24) % 24
    t = sinceSunset / nightLength
  }
  const clamped = Math.min(1, Math.max(0, t))
  const [x, y] = bezier(clamped)
  return { x, y, isDay }
}

const STARS = [
  [80, 30], [150, 55], [250, 22], [400, 40], [500, 30], [560, 58], [320, 12],
]

export default function SunArc() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60000)
    return () => clearInterval(id)
  }, [])
  const { x, y, isDay } = celestialPosition(now)

  return (
    <svg
      viewBox="0 0 640 92"
      className="pointer-events-none mx-auto -mb-3 block h-16 w-full max-w-2xl sm:h-20"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="sunarc-path" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#fbbf24" stopOpacity="0" />
          <stop offset="0.35" stopColor="#fbbf24" stopOpacity="0.9" />
          <stop offset="0.5" stopColor="#f59e0b" />
          <stop offset="0.65" stopColor="#fbbf24" stopOpacity="0.9" />
          <stop offset="1" stopColor="#fbbf24" stopOpacity="0" />
        </linearGradient>
        <radialGradient id="sunarc-sun" cx="0.4" cy="0.4" r="0.8">
          <stop offset="0" stopColor="#fde68a" />
          <stop offset="0.55" stopColor="#fbbf24" />
          <stop offset="1" stopColor="#d97706" />
        </radialGradient>
        <radialGradient id="sunarc-glow" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#fbbf24" stopOpacity="0.35" />
          <stop offset="1" stopColor="#fbbf24" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="sunarc-moon" cx="0.42" cy="0.4" r="0.8">
          <stop offset="0" stopColor="#f8fafc" />
          <stop offset="0.6" stopColor="#e2e8f0" />
          <stop offset="1" stopColor="#94a3b8" />
        </radialGradient>
        <radialGradient id="sunarc-moonglow" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#cbd5e1" stopOpacity="0.4" />
          <stop offset="1" stopColor="#cbd5e1" stopOpacity="0" />
        </radialGradient>
      </defs>

      {/* Recorrido del astro: de amanecer a atardecer */}
      <path
        d="M 20 88 Q 320 -55 620 88"
        fill="none"
        stroke="url(#sunarc-path)"
        strokeWidth="2"
        strokeDasharray="1 6"
        strokeLinecap="round"
        opacity={isDay ? 1 : 0.35}
      />
      {/* Horizonte */}
      <line x1="0" y1="88" x2="640" y2="88" stroke="#e7e2d6" strokeWidth="1.5" />

      {/* Estrellas tenues solo de noche */}
      {!isDay &&
        STARS.map(([sx, sy], i) => (
          <circle key={i} cx={sx} cy={sy} r={i % 3 === 0 ? 1.3 : 0.9} fill="#94a3b8" opacity="0.7" />
        ))}

      {/* El astro en su posición según la hora */}
      {isDay ? (
        <>
          <circle cx={x} cy={y} r="26" fill="url(#sunarc-glow)" />
          <circle cx={x} cy={y} r="11" fill="url(#sunarc-sun)" />
        </>
      ) : (
        <>
          <circle cx={x} cy={y} r="22" fill="url(#sunarc-moonglow)" />
          <circle cx={x} cy={y} r="10" fill="url(#sunarc-moon)" />
          {/* Media luna: un disco del color del papel recorta el creciente */}
          <circle cx={x + 4.5} cy={y - 1.5} r="9" fill="var(--page)" />
        </>
      )}

      {/* Marcas de amanecer y atardecer sobre el horizonte */}
      <circle cx="20" cy="88" r="3" fill="#d97706" opacity="0.5" />
      <circle cx="620" cy="88" r="3" fill="#d97706" opacity="0.5" />
    </svg>
  )
}
