from unittest.mock import Mock, patch

from typer.testing import CliRunner

from arca import db
from arca.cli import _pick_cuit, app

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
        result = runner.invoke(
            app, ["facturar", "--cuit", "30111222333", "--importe", "1000"], input="y\n"
        )

    assert result.exit_code == 0, result.output
    assert "¿Emitir la factura?" in result.output
    assert "CAE 999" in result.output
    facturas = db.list_facturas(ctx[1])
    assert len(facturas) == 1
    assert facturas[0]["cbte_nro"] == 8


def test_facturar_cancelado_no_emite(tmp_path):
    wsfe = Mock()
    wsfe.ultimo_autorizado.return_value = 7
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
        result = runner.invoke(
            app, ["facturar", "--cuit", "30111222333", "--importe", "1000"], input="n\n"
        )
    assert result.exit_code == 1
    assert "Cancelado" in result.output
    wsfe.autorizar.assert_not_called()
    assert db.list_facturas(ctx[1]) == []


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


def test_pick_cuit_con_cache_ofrece_clientes_y_otro(tmp_path):
    _, conn, _, _ = _context(tmp_path)
    db.upsert_cliente(conn, 30111222333, "ACME SA", 1, "IVA Responsable Inscripto")
    select = Mock()
    select.return_value.ask.return_value = "30111222333"
    with patch("arca.cli.questionary.select", select):
        assert _pick_cuit(conn) == 30111222333
    choices = select.call_args.kwargs["choices"]
    titles = [c.title for c in choices]
    assert any("ACME SA" in t for t in titles)
    assert titles[-1] == "Otro CUIT…"


def test_pick_cuit_sin_cache_pide_texto(tmp_path):
    _, conn, _, _ = _context(tmp_path)
    text = Mock()
    text.return_value.ask.return_value = "20111111112"
    with patch("arca.cli.questionary.text", text):
        assert _pick_cuit(conn) == 20111111112


def test_historial_formatea_lineas(tmp_path):
    ctx = _context(tmp_path)
    db.upsert_factura(
        ctx[1],
        punto_venta=3,
        cbte_tipo=11,
        cbte_nro=15,
        cuit_receptor=27045612916,
        importe=150000.0,
        concepto=2,
        cae="67395569265454",
        cae_vto="20171008",
        emitida_en="2017-09-28",
    )
    with patch("arca.cli._context", return_value=ctx):
        result = runner.invoke(app, ["historial"])
    assert result.exit_code == 0
    assert (
        "2017-09-28  0003-00000015  CUIT 27045612916  $150000.00  CAE 67395569265454"
        in result.output
    )
