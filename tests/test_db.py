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


def test_list_facturas_mezcla_sync_y_emision_en_orden(conn):
    # sync guarda fechas ISO (AAAA-MM-DD); insert_factura guarda datetime ISO.
    db.upsert_factura(
        conn,
        punto_venta=3,
        cbte_tipo=11,
        cbte_nro=15,
        cuit_receptor=1,
        importe=1.0,
        concepto=2,
        cae="viejo",
        cae_vto="20171008",
        emitida_en="2017-09-28",
    )
    db.insert_factura(
        conn,
        punto_venta=3,
        cbte_tipo=11,
        cbte_nro=16,
        cuit_receptor=1,
        importe=2.0,
        concepto=2,
        cae="nuevo",
        cae_vto="20260930",
    )
    assert [f["cae"] for f in db.list_facturas(conn)] == ["nuevo", "viejo"]


def test_recibidas_upsert_y_ultima_fecha(conn):
    from arca.db import list_recibidas, ultima_recibida_fecha, upsert_recibida

    assert ultima_recibida_fecha(conn) is None
    base = dict(
        cuit_emisor=30716581973,
        denominacion_emisor="HOGAR STORE SAS",
        cbte_tipo=6,
        punto_venta=100,
        cbte_nro=20912,
        fecha="2026-09-25",
        cae="86394766551705",
        total=114997.02,
    )
    assert upsert_recibida(conn, **base) is True
    assert upsert_recibida(conn, **{**base, "total": 1.0}) is False
    assert upsert_recibida(conn, **{**base, "cbte_nro": 1, "fecha": "2026-09-01"}) is True
    filas = list_recibidas(conn)
    assert [(r["cbte_nro"], r["total"]) for r in filas] == [(20912, 1.0), (1, 114997.02)]
    assert ultima_recibida_fecha(conn) == "2026-09-25"


def test_tabla_nueva_se_agrega_a_db_existente(tmp_path):
    """Una DB creada antes de `recibidas` tiene que ganar la tabla sin perder datos."""
    import sqlite3

    from arca import db as db_mod

    path = tmp_path / "vieja.sqlite3"
    raw = sqlite3.connect(path)
    raw.execute(
        'CREATE TABLE "clientes" ("cuit" INTEGER PRIMARY KEY, "denominacion" VARCHAR(255), '
        '"condicion_iva_id" INTEGER, "condicion_desc" VARCHAR(255), '
        '"consultado_en" VARCHAR(255) NOT NULL)'
    )
    raw.execute("INSERT INTO clientes VALUES (1, 'x', 1, 'y', 'z')")
    raw.commit()
    raw.close()

    conn = db_mod.connect(path)
    try:
        assert db_mod.get_cliente(conn, 1)["denominacion"] == "x"
        assert db_mod.list_recibidas(conn) == []
        assert db_mod.list_facturas(conn) == []
    finally:
        conn.close()
