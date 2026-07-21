from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

from arca import padron


def _padron_mock():
    p = Mock()
    p.consultar.return_value = {
        "cuit": 30111222333,
        "denominacion": "ACME SA",
        "condicion_iva_id": 1,
        "condicion_desc": "IVA Responsable Inscripto",
    }
    return p


def test_cache_fresco_no_consulta(conn):
    p = _padron_mock()
    now = datetime(2026, 7, 21, tzinfo=UTC)
    padron.get_cliente(conn, 30111222333, p, now=now)
    assert p.consultar.call_count == 1

    padron.get_cliente(conn, 30111222333, p, now=now + timedelta(days=10))
    assert p.consultar.call_count == 1


def test_cache_vencido_reconsulta(conn):
    p = _padron_mock()
    now = datetime(2026, 7, 21, tzinfo=UTC)
    padron.get_cliente(conn, 30111222333, p, now=now)
    padron.get_cliente(conn, 30111222333, p, now=now + timedelta(days=31))
    assert p.consultar.call_count == 2


def test_refresh_fuerza_reconsulta(conn):
    p = _padron_mock()
    now = datetime(2026, 7, 21, tzinfo=UTC)
    padron.get_cliente(conn, 30111222333, p, now=now)
    padron.get_cliente(conn, 30111222333, p, refresh=True, now=now)
    assert p.consultar.call_count == 2
