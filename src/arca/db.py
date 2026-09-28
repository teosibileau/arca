"""Estado local en SQLite via oxyde: clientes (situación tributaria cacheada), facturas
emitidas y comprobantes recibidos (Mis Comprobantes)."""

import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from oxyde import Field, Model, db, execute_raw
from oxyde.db.schema import extract_current_schema, migration_compute_diff, migration_to_sql


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


class Recibida(Model):
    """Comprobante que otro contribuyente nos emitió, según Mis Comprobantes."""

    id: int | None = Field(default=None, db_pk=True)
    cuit_emisor: int
    denominacion_emisor: str | None = None
    cbte_tipo: int
    punto_venta: int
    cbte_nro: int
    fecha: str  # ISO (YYYY-MM-DD)
    cae: str | None = None
    moneda: str = "PES"
    cotizacion: float = 1.0
    neto_gravado: float = 0.0
    neto_no_gravado: float = 0.0
    exento: float = 0.0
    otros_tributos: float = 0.0
    iva: float = 0.0
    total: float = 0.0

    class Meta:
        is_table = True
        table_name = "recibidas"


TABLAS = (Cliente, Factura, Recibida)


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
        await self._crear_tablas_faltantes()

    async def _crear_tablas_faltantes(self) -> None:
        """oxyde.create_tables no es idempotente (sin IF NOT EXISTS), así que se
        generan sus mismos CREATE TABLE y se ejecutan solo los de tablas ausentes."""
        filas = await execute_raw("SELECT name FROM sqlite_master WHERE type = 'table'")
        existentes = {list(f.values())[0] for f in filas}
        faltantes = {m.Meta.table_name for m in TABLAS} - existentes
        if not faltantes:
            return
        vacio = json.dumps({"version": 1, "tables": {}})
        actual = json.dumps(extract_current_schema(dialect="sqlite"))
        for sql in migration_to_sql(migration_compute_diff(vacio, actual), "sqlite"):
            m = re.match(r'CREATE TABLE "(\w+)"', sql)
            if m and m.group(1) in faltantes:
                await execute_raw(sql)

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


def upsert_factura(
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
    emitida_en: str,
) -> bool:
    """Inserta o actualiza por (punto_venta, cbte_tipo, cbte_nro). True si era nueva."""
    _, created = conn.run(
        Factura.objects.update_or_create(
            punto_venta=punto_venta,
            cbte_tipo=cbte_tipo,
            cbte_nro=cbte_nro,
            defaults={
                "cuit_receptor": cuit_receptor,
                "importe": importe,
                "concepto": concepto,
                "cae": cae,
                "cae_vto": cae_vto,
                "emitida_en": emitida_en,
            },
        )
    )
    return created


def ultimo_local(conn: Connection, punto_venta: int, cbte_tipo: int) -> int:
    """Mayor número de comprobante guardado localmente (0 si no hay ninguno)."""
    facturas = conn.run(
        Factura.objects.filter(punto_venta=punto_venta, cbte_tipo=cbte_tipo)
        .order_by("-cbte_nro")
        .all()
    )
    return facturas[0].cbte_nro if facturas else 0


def list_facturas(conn: Connection) -> list[dict]:
    facturas = conn.run(Factura.objects.order_by("-emitida_en", "-cbte_nro").all())
    return [f.model_dump() for f in facturas]


def upsert_recibida(conn: Connection, **campos) -> bool:
    """Upsert por (cuit_emisor, cbte_tipo, punto_venta, cbte_nro). True si era nueva."""
    clave = {k: campos.pop(k) for k in ("cuit_emisor", "cbte_tipo", "punto_venta", "cbte_nro")}
    _, created = conn.run(Recibida.objects.update_or_create(**clave, defaults=campos))
    return created


def ultima_recibida_fecha(conn: Connection) -> str | None:
    """Fecha ISO del comprobante recibido más reciente, o None si no hay ninguno."""
    filas = conn.run(Recibida.objects.order_by("-fecha").all())
    return filas[0].fecha if filas else None


def list_recibidas(conn: Connection) -> list[dict]:
    filas = conn.run(Recibida.objects.order_by("-fecha", "-cbte_nro").all())
    return [r.model_dump() for r in filas]
