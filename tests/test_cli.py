from unittest.mock import Mock, patch

from typer.testing import CliRunner

from arca import db
from arca.cli import app

runner = CliRunner()


def _context(tmp_path, wsfe=None, padron=None):
    settings = Mock(punto_venta=1, env="homo", db_path=tmp_path / "cli.sqlite3")
    conn = db.connect(settings.db_path)
    return settings, conn, wsfe or Mock(), padron or Mock()


def test_facturar_emite_y_guarda(tmp_path):
    wsfe = Mock()
    wsfe.ultimo_autorizado.return_value = 7
    wsfe.autorizar.return_value = {
        "resultado": "A",
        "cae": "999",
        "cae_vto": "20260731",
        "observaciones": [],
    }
    ctx = _context(tmp_path, wsfe=wsfe)
    cliente = {
        "denominacion": "ACME SA",
        "condicion_desc": "IVA Responsable Inscripto",
        "condicion_iva_id": 1,
    }

    with (
        patch("arca.cli._context", return_value=ctx),
        patch("arca.padron.get_cliente", return_value=cliente),
    ):
        result = runner.invoke(app, ["facturar", "--cuit", "30111222333", "--importe", "1000"])

    assert result.exit_code == 0, result.output
    assert "CAE 999" in result.output
    facturas = db.list_facturas(ctx[1])
    assert len(facturas) == 1
    assert facturas[0]["cbte_nro"] == 8


def test_historial_vacio(tmp_path):
    with patch("arca.cli._context", return_value=_context(tmp_path)):
        result = runner.invoke(app, ["historial"])
    assert result.exit_code == 0
    assert "Sin facturas" in result.output


def test_status(tmp_path):
    wsfe = Mock()
    wsfe.dummy.return_value = {"app": "OK", "db": "OK", "auth": "OK"}
    wsfe.puntos_venta.return_value = [{"nro": 3, "modo": "CAE - Monotributo", "bloqueado": False}]
    wsfe.ultimo_autorizado.return_value = 12
    with patch("arca.cli._context", return_value=_context(tmp_path, wsfe=wsfe)):
        result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "12" in result.output


def _factura_arca(nro):
    return {
        "cbte_nro": nro,
        "fecha": f"2026-01-{nro:02d}",
        "doc_tipo": 80,
        "doc_nro": 30111222333,
        "importe": 1000.0 * nro,
        "concepto": 2,
        "cae": f"cae{nro}",
        "cae_vto": "20260131",
        "resultado": "A",
    }


def test_sync_trae_solo_lo_que_falta(tmp_path):
    wsfe = Mock()
    wsfe.ultimo_autorizado.return_value = 3
    wsfe.consultar.side_effect = lambda nro: None if nro == 2 else _factura_arca(nro)
    ctx = _context(tmp_path, wsfe=wsfe)

    with patch("arca.cli._context", return_value=ctx):
        result = runner.invoke(app, ["sync"])
    assert result.exit_code == 0, result.output
    assert "salteado" in result.output
    assert "2 nuevas" in result.output
    assert [f["cbte_nro"] for f in db.list_facturas(ctx[1])] == [3, 1]

    wsfe.consultar.reset_mock()
    with patch("arca.cli._context", return_value=ctx):
        result = runner.invoke(app, ["sync"])
    assert "al día" in result.output
    wsfe.consultar.assert_not_called()

    with patch("arca.cli._context", return_value=ctx):
        result = runner.invoke(app, ["sync", "--todo"])
    assert "0 nuevas" in result.output
    assert wsfe.consultar.call_count == 3


def test_padron_imprime_tabla_y_actualiza_cache(tmp_path):
    padron = Mock()
    padron.consultar_detalle.return_value = {
        "cuit": 30111222333,
        "denominacion": "ACME SA",
        "condicion_desc": "IVA Responsable Inscripto",
        "condicion_iva_id": 1,
        "tipo_persona": "JURIDICA",
        "estado_clave": "ACTIVO",
        "mes_cierre": 5,
        "domicilio": "ARIAS 1639, CABA, 1429",
        "categoria_monotributo": None,
        "actividades": ["731009  SERVICIOS DE PUBLICIDAD N.C.P."],
        "impuestos": [{"descripcion": "IIBB", "estado": "AC", "periodo": 201408}],
    }
    ctx = _context(tmp_path, padron=padron)
    with patch("arca.cli._context", return_value=ctx):
        result = runner.invoke(app, ["padron", "30111222333"])
    assert result.exit_code == 0, result.output
    for esperado in ("ACME SA", "JURIDICA", "PUBLICIDAD", "IIBB", "ACTIVO"):
        assert esperado in result.output
    assert db.get_cliente(ctx[1], 30111222333)["denominacion"] == "ACME SA"
