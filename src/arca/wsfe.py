"""Cliente WSFEv1: consulta de comprobantes y autorización de Factura C (CAE)."""

from dataclasses import dataclass
from datetime import date

FACTURA_C = 11
DOC_TIPO_CUIT = 80
CONCEPTO_PRODUCTOS = 1
CONCEPTO_SERVICIOS = 2
CONCEPTO_AMBOS = 3


@dataclass
class FacturaC:
    punto_venta: int
    cbte_nro: int
    doc_tipo: int
    doc_nro: int
    importe: float
    concepto: int
    condicion_iva_receptor: int
    fecha: date
    fecha_serv_desde: date | None = None
    fecha_serv_hasta: date | None = None
    fecha_vto_pago: date | None = None


def _fch(d: date) -> str:
    return d.strftime("%Y%m%d")


def build_fecae_request(factura: FacturaC) -> dict:
    """Arma el FECAERequest para una Factura C (sin IVA discriminado)."""
    det = {
        "Concepto": factura.concepto,
        "DocTipo": factura.doc_tipo,
        "DocNro": factura.doc_nro,
        "CbteDesde": factura.cbte_nro,
        "CbteHasta": factura.cbte_nro,
        "CbteFch": _fch(factura.fecha),
        "ImpTotal": round(factura.importe, 2),
        "ImpTotConc": 0,
        "ImpNeto": round(factura.importe, 2),
        "ImpOpEx": 0,
        "ImpTrib": 0,
        "ImpIVA": 0,
        "MonId": "PES",
        "MonCotiz": 1,
        "CondicionIVAReceptorId": factura.condicion_iva_receptor,
    }
    if factura.concepto in (CONCEPTO_SERVICIOS, CONCEPTO_AMBOS):
        det["FchServDesde"] = _fch(factura.fecha_serv_desde or factura.fecha)
        det["FchServHasta"] = _fch(factura.fecha_serv_hasta or factura.fecha)
        det["FchVtoPago"] = _fch(factura.fecha_vto_pago or factura.fecha)
    return {
        "FeCabReq": {"CantReg": 1, "PtoVta": factura.punto_venta, "CbteTipo": FACTURA_C},
        "FeDetReq": {"FECAEDetRequest": [det]},
    }


def parse_fecae_response(response) -> dict:
    """Extrae resultado, CAE y observaciones de la respuesta de FECAESolicitar."""
    if response.Errors:
        errores = [f"{e.Code}: {e.Msg}" for e in response.Errors.Err]
        raise WsfeError("; ".join(errores))
    det = response.FeDetResp.FECAEDetResponse[0]
    obs = []
    if getattr(det, "Observaciones", None):
        obs = [f"{o.Code}: {o.Msg}" for o in det.Observaciones.Obs]
    return {
        "resultado": det.Resultado,
        "cae": det.CAE or None,
        "cae_vto": det.CAEFchVto or None,
        "observaciones": obs,
    }


class WsfeError(Exception):
    pass


class Wsfe:
    def __init__(self, settings, wsaa):
        self.settings = settings
        self.wsaa = wsaa
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from arca.transport import make_client

            self._client = make_client(self.settings.urls["wsfe"])
        return self._client

    @property
    def auth(self) -> dict:
        ta = self.wsaa.get_ta("wsfe")
        return {"Token": ta["token"], "Sign": ta["sign"], "Cuit": self.settings.cuit}

    def dummy(self) -> dict:
        r = self.client.service.FEDummy()
        return {"app": r.AppServer, "db": r.DbServer, "auth": r.AuthServer}

    def puntos_venta(self) -> list[dict]:
        r = self.client.service.FEParamGetPtosVenta(Auth=self.auth)
        if not r.ResultGet:
            return []
        return [
            {"nro": p.Nro, "modo": p.EmisionTipo, "bloqueado": p.Bloqueado != "N"}
            for p in r.ResultGet.PtoVenta
        ]

    def ultimo_autorizado(self) -> int:
        r = self.client.service.FECompUltimoAutorizado(
            Auth=self.auth, PtoVta=self.settings.punto_venta, CbteTipo=FACTURA_C
        )
        return r.CbteNro

    def autorizar(self, factura: FacturaC) -> dict:
        request = build_fecae_request(factura)
        response = self.client.service.FECAESolicitar(Auth=self.auth, FeCAEReq=request)
        result = parse_fecae_response(response)
        if result["resultado"] != "A":
            raise WsfeError(f"Comprobante rechazado: {'; '.join(result['observaciones']) or 'sin detalle'}")
        return result
