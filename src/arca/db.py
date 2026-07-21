"""Estado local en SQLite: clientes (situación tributaria cacheada) y facturas emitidas."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS clientes (
    cuit INTEGER PRIMARY KEY,
    denominacion TEXT,
    condicion_iva_id INTEGER,
    condicion_desc TEXT,
    consultado_en TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facturas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    punto_venta INTEGER NOT NULL,
    cbte_tipo INTEGER NOT NULL,
    cbte_nro INTEGER NOT NULL,
    cuit_receptor INTEGER NOT NULL,
    importe REAL NOT NULL,
    concepto INTEGER NOT NULL,
    cae TEXT NOT NULL,
    cae_vto TEXT NOT NULL,
    emitida_en TEXT NOT NULL
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def get_cliente(conn: sqlite3.Connection, cuit: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM clientes WHERE cuit = ?", (cuit,)).fetchone()


def upsert_cliente(
    conn: sqlite3.Connection,
    cuit: int,
    denominacion: str,
    condicion_iva_id: int,
    condicion_desc: str,
    consultado_en: datetime | None = None,
) -> None:
    consultado_en = consultado_en or datetime.now(UTC)
    conn.execute(
        """INSERT INTO clientes
           (cuit, denominacion, condicion_iva_id, condicion_desc, consultado_en)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(cuit) DO UPDATE SET
             denominacion = excluded.denominacion,
             condicion_iva_id = excluded.condicion_iva_id,
             condicion_desc = excluded.condicion_desc,
             consultado_en = excluded.consultado_en""",
        (cuit, denominacion, condicion_iva_id, condicion_desc, consultado_en.isoformat()),
    )
    conn.commit()


def list_clientes(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM clientes ORDER BY denominacion").fetchall()


def insert_factura(
    conn: sqlite3.Connection,
    *,
    punto_venta: int,
    cbte_tipo: int,
    cbte_nro: int,
    cuit_receptor: int,
    importe: float,
    concepto: int,
    cae: str,
    cae_vto: str,
) -> None:
    conn.execute(
        """INSERT INTO facturas
           (punto_venta, cbte_tipo, cbte_nro, cuit_receptor,
            importe, concepto, cae, cae_vto, emitida_en)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            punto_venta,
            cbte_tipo,
            cbte_nro,
            cuit_receptor,
            importe,
            concepto,
            cae,
            cae_vto,
            datetime.now(UTC).isoformat(),
        ),
    )
    conn.commit()


def list_facturas(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM facturas ORDER BY emitida_en DESC").fetchall()
