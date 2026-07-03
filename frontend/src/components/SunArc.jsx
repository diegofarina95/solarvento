// Firma visual de SolVento: el arco diario del sol sobre el horizonte, lo
// mismo que la app calcula (horas de sol pico, curva del día tipo). Puro SVG,
// sin animación: un gesto, no un adorno.
export default function SunArc() {
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
      </defs>

      {/* Recorrido del sol: de amanecer a atardecer */}
      <path
        d="M 20 88 Q 320 -55 620 88"
        fill="none"
        stroke="url(#sunarc-path)"
        strokeWidth="2"
        strokeDasharray="1 6"
        strokeLinecap="round"
      />
      {/* Horizonte */}
      <line x1="0" y1="88" x2="640" y2="88" stroke="#e7e2d6" strokeWidth="1.5" />

      {/* El sol en su cénit */}
      <circle cx="320" cy="18" r="26" fill="url(#sunarc-glow)" />
      <circle cx="320" cy="18" r="11" fill="url(#sunarc-sun)" />

      {/* Marcas de amanecer y atardecer sobre el horizonte */}
      <circle cx="20" cy="88" r="3" fill="#d97706" opacity="0.5" />
      <circle cx="620" cy="88" r="3" fill="#d97706" opacity="0.5" />
    </svg>
  )
}
