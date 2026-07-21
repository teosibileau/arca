"""Estado local en SQLite via oxyde: clientes (situación tributaria cacheada) y facturas."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from oxyde import Field, Model, create_tables, db, execute_raw, get_connection


class Cliente(Model):
    cuit: int = Field(db_pk=True)
    denominacion: str | None = None
    condicion_iva_id: int | None = None
    condicion_desc: str | None = None
    consultado_en: str = ""

    class Meta:
        is_table = True
        table_name = "clientes"


class Factura(Model):
    id: int | None = Field(default=None, db_pk=True)
    punto_venta: int
    cbte_tipo: int
    cbte_nro: int
    cuit_receptor: int
    importe: float
    concepto: int
    cae: str
    cae_vto: str
    emitida_en: str

    class Meta:
        is_table = True
        table_name = "facturas"


class Connection:
    """Puente sync sobre la API async de oxyde.

    Un event loop propio que vive lo que dura la sesión: asyncio.run por
    operación crearía y destruiría el loop del pool en cada llamada.
    """

    def __init__(self, path: Path):
        self._loop = asyncio.new_event_loop()
        path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.run(self._init(path))

    async def _init(self, path: Path) -> None:
        await db.disconnect_all()
        await db.init(default=f"sqlite:///{path}")
        # create_tables no es idempotente (sin IF NOT EXISTS): solo en DB nueva.
        existentes = await execute_raw(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN (?, ?)",
            [Cliente.Meta.table_name, Factura.Meta.table_name],
        )
        if len(existentes) < 2:
            await create_tables(await get_connection("default"))

    def run(self, coro):
        return self._loop.run_until_complete(coro)

    def close(self) -> None:
        self.run(db.disconnect_all())
        self._loop.close()


def connect(path: Path) -> Connection:
    return Connection(path)


def get_cliente(conn: Connection, cuit: int) -> dict | None:
    cliente = conn.run(Cliente.objects.get_or_none(cuit=cuit))
    return cliente.model_dump() if cliente else None


def upsert_cliente(
    conn: Connection,
    cuit: int,
    denominacion: str,
    condicion_iva_id: int,
    condicion_desc: str,
    consultado_en: datetime | None = None,
) -> None:
    consultado_en = consultado_en or datetime.now(UTC)
    conn.run(
        Cliente.objects.update_or_create(
            cuit=cuit,
            defaults={
                "denominacion": denominacion,
                "condicion_iva_id": condicion_iva_id,
                "condicion_desc": condicion_desc,
                "consultado_en": consultado_en.isoformat(),
            },
        )
    )


def list_clientes(conn: Connection) -> list[dict]:
    clientes = conn.run(Cliente.objects.order_by("denominacion").all())
    return [c.model_dump() for c in clientes]


def insert_factura(
    conn: Connection,
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
    conn.run(
        Factura.objects.create(
            punto_venta=punto_venta,
            cbte_tipo=cbte_tipo,
            cbte_nro=cbte_nro,
            cuit_receptor=cuit_receptor,
            importe=importe,
            concepto=concepto,
            cae=cae,
            cae_vto=cae_vto,
            emitida_en=datetime.now(UTC).isoformat(),
        )
    )


def list_facturas(conn: Connection) -> list[dict]:
    facturas = conn.run(Factura.objects.order_by("-emitida_en").all())
    return [f.model_dump() for f in facturas]
