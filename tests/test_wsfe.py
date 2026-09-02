from datetime import date
from unittest.mock import Mock

import pytest

from arca.wsfe import (
    CONCEPTO_PRODUCTOS,
    CONCEPTO_SERVICIOS,
    FacturaC,
    Wsfe,
    WsfeError,
    build_fecae_request,
    parse_fecae_response,
    parse_fecompconsultar_response,
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
    det = build_fecae_request(_factura(concepto=CONCEPTO_PRODUCTOS))["FeDetReq"]["FECAEDetRequest"][
        0
    ]
    assert "FchServDesde" not in det


def _consultar_response(**kw):
    r = Mock(Errors=None)
    r.ResultGet = Mock(
        CbteDesde=15,
        CbteFch="20170928",
        DocTipo=80,
        DocNro=27045612916,
        ImpTotal=150000.0,
        Concepto=2,
        CodAutorizacion="67395569265454",
        FchVto="20171008",
        Resultado="A",
        **kw,
    )
    return r


def test_consultar_normaliza_comprobante():
    f = parse_fecompconsultar_response(_consultar_response())
    assert f["cbte_nro"] == 15
    assert f["fecha"] == "2017-09-28"
    assert f["doc_nro"] == 27045612916
    assert f["importe"] == 150000.0
    assert f["cae"] == "67395569265454"
    assert f["cae_vto"] == "20171008"


def test_consultar_inexistente_devuelve_none():
    r = Mock()
    r.Errors.Err = [Mock(Code=602, Msg="No existen datos")]
    assert parse_fecompconsultar_response(r) is None


def test_consultar_otro_error_levanta():
    r = Mock()
    r.Errors.Err = [Mock(Code=600, Msg="Token invalido")]
    with pytest.raises(WsfeError, match="600"):
        parse_fecompconsultar_response(r)


def _fecae_response(resultado="A", cae="75001234567890", obs=None, errors=None):
    det = Mock(Resultado=resultado, CAE=cae, CAEFchVto="20260930" if cae else None)
    det.Observaciones = Mock(Obs=[Mock(Code=c, Msg=m) for c, m in obs]) if obs else None
    r = Mock(Errors=Mock(Err=[Mock(Code=c, Msg=m) for c, m in errors]) if errors else None)
    r.FeDetResp.FECAEDetResponse = [det]
    return r


def test_parse_fecae_aprobada():
    out = parse_fecae_response(_fecae_response())
    assert out == {
        "resultado": "A",
        "cae": "75001234567890",
        "cae_vto": "20260930",
        "observaciones": [],
    }


def test_parse_fecae_rechazada_junta_observaciones():
    out = parse_fecae_response(
        _fecae_response(resultado="R", cae=None, obs=[(10018, "CUIT receptor inválido")])
    )
    assert out["resultado"] == "R"
    assert out["cae"] is None
    assert out["cae_vto"] is None
    assert out["observaciones"] == ["10018: CUIT receptor inválido"]


def test_parse_fecae_errores_globales_levanta():
    with pytest.raises(WsfeError, match="600"):
        parse_fecae_response(_fecae_response(errors=[(600, "Token invalido")]))


def test_autorizar_rechazada_levanta_con_observaciones():
    wsaa = Mock()
    wsaa.get_ta.return_value = {"token": "t", "sign": "s"}
    w = Wsfe(Mock(cuit=20299528015), wsaa)
    w._client = Mock()
    w._client.service.FECAESolicitar.return_value = _fecae_response(
        resultado="R", cae=None, obs=[(10018, "CUIT receptor inválido")]
    )
    factura = _factura(concepto=CONCEPTO_PRODUCTOS)
    with pytest.raises(WsfeError, match="10018"):
        w.autorizar(factura)
