# ☀️ SolarVento

Calculadora web de autoconsumo solar fotovoltaico. Introduce una ubicación (buscador o clic en el mapa) y los parámetros de tu instalación, y obtén:

- **Horas de sol pico (HSP)** diarias medias e irradiación mensual/anual
- **Inclinación y azimut óptimos** para la ubicación
- **Producción estimada** (kWh/mes y kWh/año) según la potencia instalada
- **Comparativa** entre los ángulos óptimos y los reales de tu tejado (% de pérdida)
- **Importación de facturas de la luz** (PDF, **foto JPG/PNG** o a mano) para derivar tu consumo
  anual, tu precio real €/kWh y una curva mensual estimada incluso con 2-3 meses separados. Si
  configuras OpenAI, el backend analiza el PDF o la imagen completos antes de caer al extractor
  local multi-idioma (las fotos requieren OpenAI). Máximo 10 subidas por IP.
- **Informe descargable** (imprimir → guardar como PDF) en dos variantes: *informativo* (resumen
  para el usuario final) e *instalador* (dosier técnico completo para pedir presupuesto).
- **Coste estimado de la instalación** (por kWp, configurable) si no lo conoces
- **Ahorro económico anual** con compensación de excedentes (modelo español, con tope mensual) y
  **amortización simple**
- **Análisis de baterías**: simulación horaria de autoconsumo (producción PVGIS contra un perfil
  residencial) que compara escenarios sin batería / 5 kWh / 10 kWh y recomienda si compensa
- **Nº de paneles recomendados** y superficie de tejado necesaria
- **Gráficas de consumo/gasto mensual** y de día tipo: producción frente a consumo hora a hora

Datos de radiación: [PVGIS v5.2](https://re.jrc.ec.europa.eu/pvg_tools/es/) (Comisión Europea, sin API key). Geocoding: [Nominatim](https://nominatim.org/) (OpenStreetMap). Las llamadas a PVGIS se hacen desde el backend (PVGIS no permite CORS) y se cachean en SQLite por coordenadas redondeadas a 2 decimales con TTL largo.

## Estructura

```
backend/    FastAPI (Python 3.12+, gestionado con uv)
  app/      código de la API (endpoints, cliente PVGIS, cálculos, caché)
  tests/    pytest (unitarios + integración real contra PVGIS)
frontend/   React + Vite + Tailwind (Leaflet para el mapa, Recharts para gráficas)
Dockerfile  build multi-stage (frontend → estáticos servidos por FastAPI)
```

### Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/solar-estimate` | Cálculo completo (producción, HSP, óptimos, economía, paneles, baterías) |
| `POST` | `/api/parse-bill` | Extrae kWh, importe y periodo de una factura (PDF o imagen); 10/IP |
| `GET` | `/api/optimal-angles?lat&lon` | Solo ángulos óptimos y producción por kWp |
| `GET` | `/api/geocode?q=` | Búsqueda de direcciones (Nominatim, 1 req/s) |
| `GET` | `/api/health` | Estado del servicio |

Convención de azimut (la de PVGIS): `0 = Sur, 90 = Oeste, −90 = Este, ±180 = Norte`.

## Desarrollo

Requisitos: [uv](https://docs.astral.sh/uv/) y Node 20+.

```bash
# Backend (puerto 8000)
cd backend
uv sync --all-groups
uv run uvicorn app.main:app --reload --port 8000

# Frontend con hot-reload (proxy /api → localhost:8000)
cd frontend
npm install
npm run dev
```

Abre la URL que indica Vite (por defecto `http://localhost:5173`).

### Configuración

Copia `.env.example` a `backend/.env` y ajusta si hace falta (precio kWh por defecto, TTL de caché, User-Agent…). Todos los valores tienen defaults razonables.

Para activar el análisis IA de facturas PDF, añade `SOLVENTO_OPENAI_API_KEY` o `OPENAI_API_KEY`
en `backend/.env`. El modelo por defecto es `SOLVENTO_OPENAI_BILL_PARSER_MODEL=gpt-5.5`;
puedes cambiarlo sin tocar código. La clave se usa solo en el backend y nunca se envía al
navegador. `/api/health` indica `bill_parser: "openai"` cuando está activo y `"local"` cuando
solo se usa el extractor de texto.

### Tests

```bash
cd backend
uv run pytest                  # unitarios (PVGIS mockeado)
uv run pytest -m integration   # integración real contra PVGIS (Santiago de Compostela)
```

## Producción

FastAPI sirve el build del frontend como estáticos si existe `frontend/dist`:

```bash
cd frontend && npm run build
cd ../backend && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

El host y el puerto deben venir del entorno de despliegue (en Taller, usa los que inyecta el panel):

```bash
uv run uvicorn app.main:app --host "$HOST" --port "$PORT"
```

### Docker

```bash
docker build -t solvento .
docker run -p 8000:8000 -v solvento-cache:/data solvento
```

La imagen es multi-stage (Node compila el frontend, Python ejecuta la API) y persiste la caché de PVGIS en el volumen `/data`. `HOST` y `PORT` son configurables por variable de entorno.

## Notas de cálculo

- **HSP**: `H(i)_d` de PVGIS — irradiación diaria media sobre el plano del generador (kWh/m² ≈ horas de sol pico).
- **% pérdida vs óptimo**: `(producción_óptima − producción_usuario) / producción_óptima`.
- **Facturas**: el precio medio €/kWh sale del cargo variable de energía de las facturas, separado
  del total final con potencia, impuestos y alquileres. Si OpenAI está configurado, el backend usa
  la Responses API para completar el contexto del documento; en PDFs con texto extraíble mantiene
  el extractor local como fuente principal de kWh e importes. El país detectado en la factura
  actualiza el selector de país de la plataforma. Si
  aportas meses concretos, por ejemplo enero, julio y septiembre, esos meses se normalizan a mes
  completo y el resto del año se estima con el perfil residencial; con 12 meses se usa la
  estacionalidad real del usuario.
- **Simulación horaria** (cuando se conoce el consumo): producción horaria media por mes de PVGIS
  `seriescalc` (año de referencia 2020) contra un perfil de consumo residencial español (valle
  nocturno, punta de tarde-noche). Batería con eficiencia de ida y vuelta del 90%.
- **Ahorro anual**: autoconsumo a precio de compra + excedentes compensados (default 0,06 €/kWh)
  con el tope mensual de la compensación simplificada (la factura de energía no queda negativa).
- **Baterías**: se recomienda la capacidad con mejor payback marginal si baja de ~10 años (vida
  útil típica); si no, se indica que no compensa.
- **Coste estimado**: media de mercado del país ajustada por tamaño (las instalaciones pequeñas
  cuestan más por kWp; curva calibrada con datos reales, exponente 0,3 sobre 5 kWp de referencia)
  y presentada como rango típico de presupuestos (−12 % / +15 %), siempre dentro de la banda de
  mercado. Las baterías se ajustan igual por capacidad (10 kWh de referencia). Sin subvenciones.
- **Amortización**: retorno simple `coste / ahorro anual`, sin inflación ni degradación.
- **Paneles recomendados**: `⌈(consumo / kWh-por-kWp-local) × 1000 / W-panel⌉` (~2,2 m²/panel +15% de margen).

> ⚠️ Es una estimación orientativa para decidir si pedir presupuestos, no un estudio técnico.

## Límites de uso

| Endpoint | Por equipo (IP) | Global diario |
|---|---|---|
| `/api/parse-bill` (facturas → OpenAI) | 10/día | 100/día |
| `/api/solar-estimate` (→ PVGIS) | 60/día | 1000/día |

Configurables por `.env` (`SOLVENTO_UPLOAD_RATELIMIT_*`, `SOLVENTO_ESTIMATE_RATELIMIT_*`).
Ventana deslizante de 24 h persistida en SQLite; al superar el límite la API responde 429
con un mensaje claro.

## Anuncios (AdSense)

La web lleva tres huecos de anuncio (cabecera, entre resultados, pie) que **no renderizan
nada** hasta que se configuran en el build:

```bash
VITE_ADSENSE_CLIENT=ca-pub-XXXXXXXXXXXXXXXX \
VITE_ADSENSE_SLOT_TOP=1111111111 \
VITE_ADSENSE_SLOT_RESULTS=2222222222 \
VITE_ADSENSE_SLOT_FOOTER=3333333333 \
npm run build
```

Pasos cuando esté en su dominio definitivo: (1) alta del dominio en AdSense, (2) crear
`frontend/public/ads.txt` con la línea que da AdSense, (3) rebuild con las variables de
arriba. Los anuncios se excluyen automáticamente de los informes impresos.

## Dominio propio

El build usa el prefijo `/solvento/` (así se publica hoy tras el funnel). Para servirla
en la raíz de un dominio propio: `SOLVENTO_BASE=/ npm run build`. El backend acepta
las rutas con y sin prefijo, así que no hay que tocar nada más.
