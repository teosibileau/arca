# arca

Emisión de Factura C para monotributistas directo contra los web services de ARCA (WSAA + WSFEv1), sin pasar por el portal ni por intermediarios.

## Setup

```sh
uv sync
cp .env.example .env   # completar con tus datos
```

### Certificado digital (una sola vez)

Requiere [ahoy](https://github.com/ahoy-cli/ahoy) (`brew install ahoy`).

1. `ahoy csr` genera la clave privada y el CSR usando el `ARCA_CUIT` del `.env`.

2. En el portal de ARCA, entrar a **Administrador de Certificados Digitales**, crear un alias y subir el `.csr`. Descargar el certificado y guardarlo en `ARCA_CERT_PATH` (default `certs/arca.crt`).

3. En **Administrador de Relaciones de Clave Fiscal**, autorizar ese alias para DOS servicios:
   - **Facturación Electrónica** (`wsfe`)
   - **Consulta de Constancia de Inscripción** (`ws_sr_constancia_inscripcion`)

4. Para cada uno de esos servicios:
   - **Nueva Relación**
   - En "Servicio" tocar **Buscar** (aparecen los logos de organismos)
   - Logo de **ARCA**
   - Rama **WebServices** (no "Servicios Interactivos")
   - Elegir el servicio en la lista alfabética
   - En "Representante" elegir **Computador Fiscal** y el alias del certificado

   Sin la segunda relación, `facturar` y `padron` fallan con "Computador no autorizado a acceder al servicio".

5. Dar de alta un punto de venta para web services (Comprobantes en línea, ABM de puntos de venta) y ponerlo en `ARCA_PUNTO_VENTA`.

6. `ahoy verify-cert` chequea que el certificado corresponda a la clave y muestra el vencimiento; después `ahoy status` valida contra ARCA.

Para el ambiente de homologación (`ARCA_ENV=homo`) el certificado se gestiona en el portal de homologación y no emite facturas reales. Probá ahí primero.

## Uso

```sh
uv run arca status      # verifica conectividad, auth y último comprobante
uv run arca facturar    # emite una Factura C (pregunta lo que falte)
uv run arca facturar --cuit 30111222333 --importe 150000
uv run arca historial   # facturas emitidas, guardadas localmente
uv run arca sync        # trae de ARCA las facturas que faltan en el historial local
uv run arca padron 30111222333   # tabla con la situación tributaria del CUIT (condición de IVA, domicilio, actividades, impuestos)
```

`sync` consulta comprobante por comprobante (`FECompConsultar`) desde el último guardado hasta el último autorizado en ARCA, así el historial incluye también lo emitido por otros medios (portal, Facturante, etc.). `--todo` reconsulta desde el 1 y actualiza los ya guardados.

`facturar` muestra un resumen (número, receptor, concepto, importe, ambiente) y pide confirmación antes de emitir; `--si` la saltea para uso scripteado. Cachea la situación tributaria del receptor por 30 días en `data/arca.sqlite3` (gitignoreado); `--refresh` fuerza la reconsulta al padrón, y `padron` también actualiza ese cache.

## Tests

```sh
uv run pytest
```

Los tests son unitarios y no tocan la red: la firma WSAA se prueba con un certificado self-signed generado en el momento.
