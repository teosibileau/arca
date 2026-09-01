"""CLI: facturar, historial, sync, padron y status."""

from datetime import date

import questionary
import typer

from arca import db
from arca import padron as padron_mod
from arca.config import Settings
from arca.wsaa import Wsaa
from arca.wsfe import CONCEPTO_SERVICIOS, DOC_TIPO_CUIT, FACTURA_C, FacturaC, Wsfe

app = typer.Typer(help="Factura C contra los web services de ARCA.")


def _context():
    settings = Settings()
    wsaa = Wsaa(settings)
    return (
        settings,
        db.connect(settings.db_path),
        Wsfe(settings, wsaa),
        padron_mod.Padron(settings, wsaa),
    )


def _pick_cuit(conn) -> int:
    clientes = db.list_clientes(conn)
    choices = [
        questionary.Choice(
            title=f"{c['cuit']} · {c['denominacion']} ({c['condicion_desc']})", value=str(c["cuit"])
        )
        for c in clientes
    ]
    if choices:
        choices.append(questionary.Choice(title="Otro CUIT…", value=""))
        answer = questionary.select("CUIT del cliente:", choices=choices).ask()
        if answer:
            return int(answer)
    return int(
        questionary.text("CUIT del cliente:", validate=lambda v: v.isdigit() and len(v) == 11).ask()
    )


@app.command()
def facturar(
    cuit: int | None = typer.Option(None, help="CUIT del receptor (si falta, se pregunta)."),
    importe: float | None = typer.Option(None, help="Importe total en pesos."),
    concepto: int = typer.Option(CONCEPTO_SERVICIOS, help="1=Productos, 2=Servicios, 3=Ambos."),
    refresh: bool = typer.Option(
        False, "--refresh", help="Fuerza reconsulta del padrón (ignora cache)."
    ),
):
    """Emite una Factura C y guarda el CAE en el historial local."""
    settings, conn, wsfe, padron = _context()

    if cuit is None:
        cuit = _pick_cuit(conn)
    if importe is None:
        importe = float(
            questionary.text(
                "Importe total ($):", validate=lambda v: v.replace(".", "", 1).isdigit()
            ).ask()
        )

    cliente = padron_mod.get_cliente(conn, cuit, padron, refresh=refresh)
    typer.echo(f"Receptor: {cliente['denominacion']} · {cliente['condicion_desc']}")

    cbte_nro = wsfe.ultimo_autorizado() + 1
    factura = FacturaC(
        punto_venta=settings.punto_venta,
        cbte_nro=cbte_nro,
        doc_tipo=DOC_TIPO_CUIT,
        doc_nro=cuit,
        importe=importe,
        concepto=concepto,
        condicion_iva_receptor=cliente["condicion_iva_id"],
        fecha=date.today(),
    )
    result = wsfe.autorizar(factura)
    db.insert_factura(
        conn,
        punto_venta=settings.punto_venta,
        cbte_tipo=FACTURA_C,
        cbte_nro=cbte_nro,
        cuit_receptor=cuit,
        importe=importe,
        concepto=concepto,
        cae=result["cae"],
        cae_vto=result["cae_vto"],
    )
    nro = f"{settings.punto_venta:04d}-{cbte_nro:08d}"
    typer.secho(
        f"Factura C {nro} autorizada. CAE {result['cae']} (vto {result['cae_vto']})",
        fg=typer.colors.GREEN,
    )


@app.command()
def historial():
    """Lista las facturas emitidas guardadas localmente."""
    _, conn, _, _ = _context()
    facturas = db.list_facturas(conn)
    if not facturas:
        typer.echo("Sin facturas emitidas todavía.")
        return
    for f in facturas:
        typer.echo(
            f"{f['emitida_en'][:10]}  {f['punto_venta']:04d}-{f['cbte_nro']:08d}  "
            f"CUIT {f['cuit_receptor']}  ${f['importe']:.2f}  CAE {f['cae']}"
        )


@app.command()
def padron(
    cuit: int = typer.Argument(help="CUIT a consultar."),
    refresh: bool = typer.Option(
        False, "--refresh", help="Fuerza reconsulta del padrón (ignora cache)."
    ),
):
    """Consulta la situación tributaria de un CUIT (cache local de 30 días)."""
    _, conn, _, padron = _context()
    cliente = padron_mod.get_cliente(conn, cuit, padron, refresh=refresh)
    typer.echo(
        f"{cliente['cuit']}  {cliente['denominacion']}  "
        f"{cliente['condicion_desc']} (id {cliente['condicion_iva_id']})"
    )


@app.command()
def sync(
    todo: bool = typer.Option(
        False, "--todo", help="Reconsulta desde el comprobante 1 (actualiza los ya guardados)."
    ),
):
    """Trae de ARCA las Facturas C del punto de venta y las guarda en el historial local."""
    settings, conn, wsfe, _ = _context()
    ultimo = wsfe.ultimo_autorizado()
    desde = 1 if todo else db.ultimo_local(conn, settings.punto_venta, FACTURA_C) + 1
    if desde > ultimo:
        typer.echo(f"Historial al día (último comprobante en ARCA: {ultimo}).")
        return

    nuevas = 0
    for nro in range(desde, ultimo + 1):
        f = wsfe.consultar(nro)
        if f is None:
            typer.echo(f"{settings.punto_venta:04d}-{nro:08d}  no existe en ARCA, salteado")
            continue
        created = db.upsert_factura(
            conn,
            punto_venta=settings.punto_venta,
            cbte_tipo=FACTURA_C,
            cbte_nro=nro,
            cuit_receptor=f["doc_nro"],
            importe=f["importe"],
            concepto=f["concepto"],
            cae=f["cae"],
            cae_vto=f["cae_vto"],
            emitida_en=f["fecha"],
        )
        nuevas += created
        typer.echo(
            f"{f['fecha']}  {settings.punto_venta:04d}-{nro:08d}  "
            f"CUIT {f['doc_nro']}  ${f['importe']:.2f}  CAE {f['cae']}"
        )
    typer.secho(
        f"Sincronizadas {ultimo - desde + 1} facturas ({nuevas} nuevas).", fg=typer.colors.GREEN
    )


@app.command()
def status():
    """Verifica conectividad y autenticación contra ARCA."""
    settings, _, wsfe, _ = _context()
    servers = wsfe.dummy()
    typer.echo(f"Ambiente: {settings.env} · servidores: {servers}")
    puntos = wsfe.puntos_venta()
    if puntos:
        for p in puntos:
            typer.echo(
                f"PV {p['nro']:04d}  modo {p['modo']}{'  [BLOQUEADO]' if p['bloqueado'] else ''}"
            )
    else:
        typer.echo("Sin puntos de venta habilitados para web services.")
    ultimo = wsfe.ultimo_autorizado()
    typer.echo(f"Último comprobante autorizado (PV {settings.punto_venta}, Factura C): {ultimo}")


if __name__ == "__main__":
    app()
