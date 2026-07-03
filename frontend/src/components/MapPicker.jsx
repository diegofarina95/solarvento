import { useEffect, useRef } from 'react'
import { MapContainer, TileLayer, Marker, useMapEvents, useMap } from 'react-leaflet'
import L from 'leaflet'
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png'
import markerIcon from 'leaflet/dist/images/marker-icon.png'
import markerShadow from 'leaflet/dist/images/marker-shadow.png'

// Con bundlers, Leaflet no resuelve solo las rutas de sus iconos por defecto.
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x,
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
})

function ClickHandler({ onChange }) {
  useMapEvents({
    click(e) {
      onChange({ lat: e.latlng.lat, lon: e.latlng.lng })
    },
  })
  return null
}

function FlyToPosition({ position, internalChange }) {
  const map = useMap()
  const isFirstRender = useRef(true)
  useEffect(() => {
    // En el primer render se respeta la vista inicial (España completa)
    if (isFirstRender.current) {
      isFirstRender.current = false
      return
    }
    // Un clic o arrastre dentro del mapa no debe mover la cámara: el usuario
    // ya está mirando donde quiere. Solo se vuela cuando la posición viene de
    // fuera (buscador, factura, selector de país).
    if (internalChange.current) {
      internalChange.current = false
      return
    }
    map.flyTo([position.lat, position.lon], Math.max(map.getZoom(), 10), { duration: 0.8 })
  }, [map, position.lat, position.lon, internalChange])
  return null
}

export default function MapPicker({ position, onChange }) {
  const internalChange = useRef(false)

  function handleInternalChange(next) {
    internalChange.current = true
    onChange(next)
  }

  return (
    <MapContainer
      center={[position.lat, position.lon]}
      zoom={6}
      className="h-72 w-full rounded-xl border border-stone-200 sm:h-80"
      scrollWheelZoom
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <ClickHandler onChange={handleInternalChange} />
      <FlyToPosition position={position} internalChange={internalChange} />
      <Marker
        position={[position.lat, position.lon]}
        draggable
        eventHandlers={{
          dragend(e) {
            const { lat, lng } = e.target.getLatLng()
            handleInternalChange({ lat, lon: lng })
          },
        }}
      />
    </MapContainer>
  )
}
