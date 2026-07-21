"""Situación tributaria del receptor via ws_sr_constancia_inscripcion, con cache en SQLite."""

from datetime import UTC, datetime, timedelta

from arca import db

SERVICE = "ws_sr_constancia_inscripcion"
CACHE_TTL = timedelta(days=30)

# Condición frente al IVA del receptor (RG 5616), según lo que devuelve el padrón.
COND_IVA_RESPONSABLE_INSCRIPTO = 1
COND_IVA_EXENTO = 4
COND_IVA_CONSUMIDOR_FINAL = 5
COND_IVA_MONOTRIBUTO = 6


def _condicion_from_persona(persona) -> tuple[int, str]:
    """Mapea la respuesta del padrón a la condición de IVA del receptor."""
    if getattr(persona, "datosMonotributo", None):
        return COND_IVA_MONOTRIBUTO, "Responsable Monotributo"
    regimen = getattr(persona, "datosRegimenGeneral", None)
    impuestos = {i.idImpuesto for i in getattr(regimen, "impuesto", [])} if regimen else set()
    if 30 in impuestos:  # IVA
        return COND_IVA_RESPONSABLE_INSCRIPTO, "IVA Responsable Inscripto"
    if 32 in impuestos:  # IVA exento
        return COND_IVA_EXENTO, "IVA Sujeto Exento"
    return COND_IVA_CONSUMIDOR_FINAL, "Consumidor Final"


def _denominacion(persona) -> str:
    datos = persona.datosGenerales
    if getattr(datos, "razonSocial", None):
        return datos.razonSocial
    return f"{getattr(datos, 'nombre', '') or ''} {getattr(datos, 'apellido', '') or ''}".strip()


class Padron:
    def __init__(self, settings, wsaa):
        self.settings = settings
        self.wsaa = wsaa
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from arca.transport import make_client

            self._client = make_client(self.settings.urls["padron"])
        return self._client

    def consultar(self, cuit: int) -> dict:
        ta = self.wsaa.get_ta(SERVICE)
        r = self.client.service.getPersona(
            token=ta["token"], sign=ta["sign"], cuitRepresentada=self.settings.cuit, idPersona=cuit
        )
        persona = r.persona
        condicion_id, condicion_desc = _condicion_from_persona(persona)
        return {
            "cuit": cuit,
            "denominacion": _denominacion(persona),
            "condicion_iva_id": condicion_id,
            "condicion_desc": condicion_desc,
        }


def get_cliente(
    conn, cuit: int, padron: Padron, refresh: bool = False, now: datetime | None = None
) -> dict:
    """Devuelve el cliente desde cache si es fresco; si no, consulta el padrón y actualiza."""
    now = now or datetime.now(UTC)
    if not refresh:
        row = db.get_cliente(conn, cuit)
        if row and now - datetime.fromisoformat(row["consultado_en"]) < CACHE_TTL:
            return dict(row)
    datos = padron.consultar(cuit)
    db.upsert_cliente(
        conn,
        cuit=cuit,
        denominacion=datos["denominacion"],
        condicion_iva_id=datos["condicion_iva_id"],
        condicion_desc=datos["condicion_desc"],
        consultado_en=now,
    )
    return {**datos, "consultado_en": now.isoformat()}
