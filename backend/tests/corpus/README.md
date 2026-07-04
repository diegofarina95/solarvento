# Corpus de regresión de ingesta de facturas

El extractor LLM es una caja negra que puede DERIVAR cuando el modelo se
actualiza. Este corpus es la red de seguridad automática.

## Estructura

Cada factura es una carpeta con dos ficheros:

- `contract.json` — el CONTRATO extraído (lo que `OpenAIBillParser.extract_contract`
  devolvió para esa factura). Es la salida cruda del modelo (raw_text por campo).
  Se guarda para poder re-ejecutar la parte determinista (Layer 3) en CI sin
  llamar al modelo de pago en cada run.
- `ground_truth.json` — la verdad, etiquetada a mano: consumo anual, split por
  periodo, potencia, tarifa, periodo, dirección, y `expected_outcome`
  (`compute` o `review`).

Opcionalmente, la factura original (`bill.pdf` / `bill.jpg`) para poder
RE-CAPTURAR el `contract.json` cuando el modelo cambie (detección de deriva):
`python -m tests.corpus.recapture` (script a añadir) vuelve a llamar al modelo y
actualiza los `contract.json`; el harness compara contra ground truth.

## Harness

`tests/test_corpus.py` pasa cada `contract.json` por el pipeline determinista
(`bill_normalise.contract_to_bill`), clasifica el resultado y falla el CI si hay
CUALQUIER factura *wrong-but-computed* (calculada con un valor equivocado): eso es
un fallo duro. `review` cuando la verdad esperaba `review` es correcto (seguro).

## Debe crecer con facturas REALES

Sembrado con dos fixtures conocidos (LuzNorte, A Estrada) y un caso de revisión.
DEBE ampliarse con facturas reales de comercializadoras (Iberdrola, Endesa,
Naturgy, Octopus, una cooperativa): los layouts sintéticos y limpios son
justo lo que dio falsa confianza. Para añadir una: captura su `contract.json`
con el extractor y etiqueta su `ground_truth.json` a mano.
