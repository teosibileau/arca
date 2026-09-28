"""CLI: facturar, historial, sync, recibidas, emitidas, balance, padron y status."""

import json
from datetime import date

import questionary
import typer

from arca import db
from arca import mcmp as mcmp_mod
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
    si: bool = typer.Option(False, "--si", help="Emite sin pedir confirmación."),
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

    nro = f"{settings.punto_venta:04d}-{cbte_nro:08d}"
    concepto_desc = {1: "Productos", 2: "Servicios", 3: "Productos y servicios"}.get(
        concepto, str(concepto)
    )
    typer.echo()
    typer.echo(f"  Factura C {nro} ({settings.env})")
    typer.echo(f"  Receptor: {cuit} · {cliente['denominacion']} · {cliente['condicion_desc']}")
    typer.echo(f"  Concepto: {concepto_desc} · Fecha: {factura.fecha:%d/%m/%Y}")
    typer.echo(f"  Importe:  ${importe:,.2f}")
    typer.echo()
    if not si and not typer.confirm("¿Emitir la factura?"):
        typer.secho("Cancelado, no se emitió nada.", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

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
    typer.secho(
        f"Factura C {nro} autorizada. CAE {result['cae']} (vto {result['cae_vto']})",
        fg=typer.colors.GREEN,
    )


def _linea_recibida(r: dict) -> str:
    return (
        f"{r['fecha']}  T{r['cbte_tipo']:02d} {r['punto_venta']:05d}-{r['cbte_nro']:08d}  "
        f"CUIT {r['cuit_emisor']}  {r['denominacion_emisor'] or '-'}  ${r['total']:.2f}"
    )


@app.command()
def historial(
    recibidas: bool = typer.Option(
        False, "--recibidas", help="Lista los comprobantes recibidos en lugar de los emitidos."
    ),
    as_json: bool = typer.Option(False, "--json", help="Salida en JSON."),
):
    """Lista las facturas emitidas (o recibidas) guardadas localmente."""
    _, conn, _, _ = _context()
    if recibidas:
        filas = db.list_recibidas(conn)
        if as_json:
            typer.echo(json.dumps(filas, ensure_ascii=False, indent=1))
            return
        if not filas:
            typer.echo("Sin comprobantes recibidos todavía. Corré `arca recibidas --desde ...`.")
            return
        for r in filas:
            typer.echo(_linea_recibida(r))
        return

    facturas = db.list_facturas(conn)
    if as_json:
        typer.echo(json.dumps(facturas, ensure_ascii=False, indent=1))
        return
    if not facturas:
        typer.echo("Sin facturas emitidas todavía.")
        return
    for f in facturas:
        typer.echo(
            f"{f['emitida_en'][:10]}  {f['punto_venta']:04d}-{f['cbte_nro']:08d}  "
            f"CUIT {f['cuit_receptor']}  ${f['importe']:.2f}  CAE {f['cae']}"
        )


def _rango(conn, desde, hasta, ultima_fecha) -> tuple[date, date]:
    if desde is None:
        try:
            d, h = mcmp_mod.rango_por_defecto(ultima_fecha)
        except ValueError as e:
            typer.secho(str(e), fg=typer.colors.RED)
            raise typer.Exit(1) from None
    else:
        d, h = date.fromisoformat(desde), date.today()
    if hasta is not None:
        h = date.fromisoformat(hasta)
    return d, h


@app.command()
def emitidas(
    desde: str | None = typer.Option(None, help="Fecha de emisión desde (AAAA-MM-DD)."),
    hasta: str | None = typer.Option(
        None, help="Fecha de emisión hasta (AAAA-MM-DD, default hoy)."
    ),
    as_json: bool = typer.Option(False, "--json", help="Imprime las nuevas en JSON."),
):
    """Trae de Mis Comprobantes lo emitido por cualquier punto de venta y guarda lo que falta.

    Complementa a `sync`, que solo ve el punto de venta de web services."""
    settings, conn, _, _ = _context()
    d, h = _rango(conn, desde, hasta, db.ultima_factura_fecha(conn))
    try:
        filas = mcmp_mod.Mcmp(settings).emitidas(d, h)
    except mcmp_mod.LoginFallido as e:
        typer.secho(str(e), fg=typer.colors.RED)
        raise typer.Exit(1) from None

    nuevas = [
        f
        for f in filas
        if db.insert_factura_si_falta(
            conn,
            punto_venta=f["punto_venta"],
            cbte_tipo=f["cbte_tipo"],
            cbte_nro=f["cbte_nro"],
            cuit_receptor=f["cuit_receptor"],
            importe=f["total"],
            cae=f["cae"],
            emitida_en=f["fecha"],
        )
    ]
    if as_json:
        typer.echo(json.dumps(nuevas, ensure_ascii=False, indent=1))
        return
    for f in nuevas:
        typer.echo(
            f"{f['fecha']}  T{f['cbte_tipo']:02d} {f['punto_venta']:05d}-{f['cbte_nro']:08d}  "
            f"CUIT {f['cuit_receptor']}  {f['denominacion_receptor'] or '-'}  ${f['total']:.2f}"
        )
    typer.secho(
        f"{d} a {h}: {len(filas)} comprobantes emitidos ({len(nuevas)} nuevos).",
        fg=typer.colors.GREEN,
    )


@app.command()
def balance(
    desde: str | None = typer.Option(None, help="Primer mes a mostrar (AAAA-MM)."),
    as_json: bool = typer.Option(False, "--json", help="Salida en JSON."),
):
    """Facturado vs gastos (recibidas) por mes, según el historial local."""
    from rich import box
    from rich.console import Console
    from rich.table import Table

    _, conn, _, _ = _context()
    meses = [m for m in db.totales_por_mes(conn) if desde is None or m["mes"] >= desde]
    if as_json:
        typer.echo(json.dumps(meses, ensure_ascii=False, indent=1))
        return
    if not meses:
        typer.echo("Sin comprobantes guardados. Corré `arca emitidas` y `arca recibidas`.")
        return
    tabla = Table(title="Facturado vs gastos", title_justify="left", box=box.SIMPLE_HEAD)
    for col in ("Mes", "Facturado", "Gastos", "Diferencia", "Emit.", "Recib."):
        tabla.add_column(col, justify="left" if col == "Mes" else "right", no_wrap=True)
    tf = tg = 0.0
    for m in meses:
        tf += m["facturado"]
        tg += m["gastos"]
        tabla.add_row(
            m["mes"],
            f"{m['facturado']:,.2f}",
            f"{m['gastos']:,.2f}",
            f"{m['facturado'] - m['gastos']:,.2f}",
            str(m["emitidas"]),
            str(m["recibidas"]),
        )
    tabla.add_section()
    tabla.add_row("Total", f"{tf:,.2f}", f"{tg:,.2f}", f"{tf - tg:,.2f}", "", "", style="bold")
    Console().print(tabla)


@app.command()
def recibidas(
    desde: str | None = typer.Option(None, help="Fecha de emisión desde (AAAA-MM-DD)."),
    hasta: str | None = typer.Option(
        None, help="Fecha de emisión hasta (AAAA-MM-DD, default hoy)."
    ),
    as_json: bool = typer.Option(False, "--json", help="Imprime las nuevas en JSON."),
):
    """Trae de Mis Comprobantes los comprobantes que nos emitieron y guarda los nuevos."""
    settings, conn, _, _ = _context()
    d, h = _rango(conn, desde, hasta, db.ultima_recibida_fecha(conn))
    try:
        filas = mcmp_mod.Mcmp(settings).recibidas(d, h)
    except mcmp_mod.LoginFallido as e:
        typer.secho(str(e), fg=typer.colors.RED)
        raise typer.Exit(1) from None

    nuevas = [r for r in filas if db.upsert_recibida(conn, **r)]
    if as_json:
        typer.echo(json.dumps(nuevas, ensure_ascii=False, indent=1))
        return
    for r in nuevas:
        typer.echo(_linea_recibida(r))
    typer.secho(
        f"{d} a {h}: {len(filas)} comprobantes recibidos ({len(nuevas)} nuevos).",
        fg=typer.colors.GREEN,
    )


@app.command()
def padron(cuit: int = typer.Argument(help="CUIT a consultar.")):
    """Consulta la situación tributaria de un CUIT en el padrón y actualiza el cache local."""
    from rich.console import Console
    from rich.table import Table

    _, conn, _, padron = _context()
    d = padron.consultar_detalle(cuit)
    db.upsert_cliente(
        conn,
        cuit=cuit,
        denominacion=d["denominacion"],
        condicion_iva_id=d["condicion_iva_id"],
        condicion_desc=d["condicion_desc"],
    )

    tabla = Table(title=f"CUIT {d['cuit']}", show_header=False, title_justify="left")
    tabla.add_column(style="bold")
    tabla.add_column()
    tabla.add_row("Denominación", d["denominacion"])
    tabla.add_row("Condición IVA", f"{d['condicion_desc']} (id {d['condicion_iva_id']})")
    tabla.add_row("Tipo de persona", d["tipo_persona"] or "-")
    tabla.add_row("Estado de clave", d["estado_clave"] or "-")
    tabla.add_row("Domicilio fiscal", d["domicilio"] or "-")
    if d["categoria_monotributo"]:
        tabla.add_row("Cat. monotributo", d["categoria_monotributo"])
    if d["mes_cierre"]:
        tabla.add_row("Mes de cierre", str(d["mes_cierre"]))
    if d["actividades"]:
        tabla.add_row("Actividades", "\n".join(d["actividades"]))
    if d["impuestos"]:
        tabla.add_row(
            "Impuestos",
            "\n".join(
                f"{i['descripcion']} ({i['estado']}"
                + (f", desde {i['periodo']}" if i["periodo"] else "")
                + ")"
                for i in d["impuestos"]
            ),
        )
    Console().print(tabla)


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
