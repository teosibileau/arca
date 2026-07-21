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
