from arca import db


def test_upsert_y_lectura_de_cliente(conn):
    db.upsert_cliente(conn, 30111222333, "ACME SA", 1, "IVA Responsable Inscripto")
    row = db.get_cliente(conn, 30111222333)
    assert row["denominacion"] == "ACME SA"

    db.upsert_cliente(conn, 30111222333, "ACME S.A.", 1, "IVA Responsable Inscripto")
    assert db.get_cliente(conn, 30111222333)["denominacion"] == "ACME S.A."
    assert len(db.list_clientes(conn)) == 1


def test_historial_de_facturas(conn):
    db.insert_factura(
        conn,
        punto_venta=1,
        cbte_tipo=11,
        cbte_nro=1,
        cuit_receptor=30111222333,
        importe=1000.0,
        concepto=2,
        cae="1234567890",
        cae_vto="20260731",
    )
    facturas = db.list_facturas(conn)
    assert len(facturas) == 1
    assert facturas[0]["cae"] == "1234567890"


def test_upsert_factura_es_idempotente(conn):
    base = dict(
        punto_venta=3,
        cbte_tipo=11,
        cbte_nro=15,
        cuit_receptor=27045612916,
        concepto=2,
        cae="67395569265454",
        cae_vto="20171008",
        emitida_en="2017-09-28",
    )
    assert db.upsert_factura(conn, importe=1.0, **base) is True
    assert db.upsert_factura(conn, importe=150000.0, **base) is False
    facturas = db.list_facturas(conn)
    assert len(facturas) == 1
    assert facturas[0]["importe"] == 150000.0


def test_ultimo_local_por_punto_de_venta(conn):
    assert db.ultimo_local(conn, 3, 11) == 0
    for nro in (2, 7, 5):
        db.upsert_factura(
            conn,
            punto_venta=3,
            cbte_tipo=11,
            cbte_nro=nro,
            cuit_receptor=1,
            importe=1.0,
            concepto=2,
            cae="x",
            cae_vto="20260101",
            emitida_en="2026-01-01",
        )
    assert db.ultimo_local(conn, 3, 11) == 7
    assert db.ultimo_local(conn, 5, 11) == 0
