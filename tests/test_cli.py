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
