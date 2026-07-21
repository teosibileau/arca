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
   - **Constancia de Inscripción** (`ws_sr_constancia_inscripcion`)

4. Dar de alta un punto de venta para web services (Comprobantes en línea, ABM de puntos de venta) y ponerlo en `ARCA_PUNTO_VENTA`.

5. `ahoy verify-cert` chequea que el certificado corresponda a la clave y muestra el vencimiento; después `ahoy status` valida contra ARCA.

Para el ambiente de homologación (`ARCA_ENV=homo`) el certificado se gestiona en el portal de homologación y no emite facturas reales. Probá ahí primero.

## Uso

```sh
uv run arca status      # verifica conectividad, auth y último comprobante
uv run arca facturar    # emite una Factura C (pregunta lo que falte)
uv run arca facturar --cuit 30111222333 --importe 150000
uv run arca historial   # facturas emitidas, guardadas localmente
```

`facturar` cachea la situación tributaria del receptor por 30 días en `data/arca.sqlite3` (gitignoreado); `--refresh` fuerza la reconsulta al padrón.

## Tests

```sh
uv run pytest
```

Los tests son unitarios y no tocan la red: la firma WSAA se prueba con un certificado self-signed generado en el momento.
