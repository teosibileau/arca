from datetime import date

import pytest

from arca.wsfe import (
    CONCEPTO_PRODUCTOS,
    CONCEPTO_SERVICIOS,
    FacturaC,
    build_fecae_request,
)


def _factura(**overrides):
    base = dict(
        punto_venta=1,
        cbte_nro=42,
        doc_tipo=80,
        doc_nro=30111222333,
        importe=150000.0,
        concepto=CONCEPTO_SERVICIOS,
        condicion_iva_receptor=1,
        fecha=date(2026, 7, 21),
    )
    return FacturaC(**{**base, **overrides})


def test_factura_c_sin_iva_discriminado():
    req = build_fecae_request(_factura())
    det = req["FeDetReq"]["FECAEDetRequest"][0]
    assert req["FeCabReq"]["CbteTipo"] == 11
    assert det["ImpTotal"] == det["ImpNeto"] == 150000.0
    assert det["ImpIVA"] == 0
    assert det["CondicionIVAReceptorId"] == 1


def test_servicios_incluye_fechas_de_servicio():
    det = build_fecae_request(_factura())["FeDetReq"]["FECAEDetRequest"][0]
    assert det["FchServDesde"] == det["FchServHasta"] == det["FchVtoPago"] == "20260721"


def test_productos_omite_fechas_de_servicio():
    det = build_fecae_request(_factura(concepto=CONCEPTO_PRODUCTOS))["FeDetReq"]["FECAEDetRequest"][0]
    assert "FchServDesde" not in det
