"""Mis Comprobantes (comprobantes recibidos) vía el portal con clave fiscal.

No hay web service: el portal es una app JSP con endpoints AJAX que devuelven JSON.
El login necesita un browser y corre en un container (docker/mcmp-login); acá se
usan las cookies que deja y se replica la consulta que hace la página:

  ajax.do?f=generarConsulta&t=R&fechaEmision=dd/mm/aaaa - dd/mm/aaaa&cuitConsultada=...
      -> {"datos": {"idConsulta": ..., "estado": "PE"}}
  ajax.do?f=estimarResultados&id=...   (dispara el procesamiento; sin esto queda en PE)
  ajax.do?f=listaResultados&id=...
      -> {"datos": {"consulta": {"estado": "PE"|"PR"|"TE"|"ER", ...}, "data": [[...], ...]}}

Las filas son posicionales; los índices salen de las constantes rowXxx del JS de
comprobantesRecibidos.do. Los índices impares intermedios son versiones "styled"
para pantalla y se ignoran.
"""

import json
import subprocess
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from requests import Session

from arca.config import Settings

BASE = "https://fes.afip.gob.ar/mcmp/jsp/"
LOGIN_IMAGE = "arca-mcmp-login"
LOGIN_DIR = Path(__file__).resolve().parent.parent.parent / "docker" / "mcmp-login"
SOLAPAMIENTO = timedelta(days=7)
# El WAF delante de fes.afip.gob.ar deja colgada la conexión si el User-Agent no es de browser.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": BASE + "comprobantesRecibidos.do",
}

# Posiciones en cada fila de listaResultados (ver docstring).
COL = {
    "fecha": 0,
    "cbte_tipo": 1,
    "punto_venta": 3,
    "cbte_nro": 4,
    "cae": 8,
    "cuit_emisor": 11,  # rowNroDocEmisor; rowCUITEmisor (9) viene null
    "denominacion_emisor": 12,
    "cotizacion": 16,
    "moneda": 17,
    "neto_gravado": 40,
    "neto_no_gravado": 42,
    "exento": 44,
    "otros_tributos": 46,
    "iva": 48,
    "total": 50,
}


class SesionVencida(Exception):
    """El portal devolvió algo que no es JSON: la sesión expiró o nunca existió."""


class LoginFallido(Exception):
    pass


def _num(v) -> float:
    return float(v) if v not in (None, "") else 0.0


def parse_fila(fila: list) -> dict:
    """Convierte una fila posicional de listaResultados en un dict de Recibida."""
    fecha = datetime.strptime(fila[COL["fecha"]], "%d/%m/%Y").date().isoformat()
    return {
        "cuit_emisor": int(fila[COL["cuit_emisor"]]),
        "denominacion_emisor": fila[COL["denominacion_emisor"]],
        "cbte_tipo": int(fila[COL["cbte_tipo"]]),
        "punto_venta": int(fila[COL["punto_venta"]]),
        "cbte_nro": int(fila[COL["cbte_nro"]]),
        "fecha": fecha,
        "cae": fila[COL["cae"]],
        "moneda": "PES" if fila[COL["moneda"]] in ("$", None) else fila[COL["moneda"]],
        "cotizacion": _num(fila[COL["cotizacion"]]) or 1.0,
        "neto_gravado": _num(fila[COL["neto_gravado"]]),
        "neto_no_gravado": _num(fila[COL["neto_no_gravado"]]),
        "exento": _num(fila[COL["exento"]]),
        "otros_tributos": _num(fila[COL["otros_tributos"]]),
        "iva": _num(fila[COL["iva"]]),
        "total": _num(fila[COL["total"]]),
    }


def rango_por_defecto(ultima_fecha: str | None, hoy: date | None = None) -> tuple[date, date]:
    """Desde la última recibida guardada menos el solapamiento, hasta hoy."""
    hoy = hoy or date.today()
    if ultima_fecha is None:
        raise ValueError("sin recibidas guardadas: indicá --desde para la primera consulta")
    return date.fromisoformat(ultima_fecha) - SOLAPAMIENTO, hoy


class Mcmp:
    def __init__(self, settings: Settings, session: Session | None = None):
        self.settings = settings
        self.session = session or Session()
        self.session.headers.update(HEADERS)

    # --- sesión -----------------------------------------------------------

    def cargar_cookies(self) -> bool:
        path = self.settings.mcmp_cookies_path
        if not path.exists():
            return False
        for c in json.loads(path.read_text()):
            self.session.cookies.set(c["name"], c["value"], domain=c["domain"], path=c["path"])
        return True

    def login(self) -> None:
        """Corre el container de login y carga las cookies que deja en data/."""
        if not self.settings.clave_fiscal:
            raise LoginFallido("falta ARCA_CLAVE_FISCAL en .env")
        out = self.settings.data_dir.resolve()
        out.mkdir(parents=True, exist_ok=True)
        name = "arca-mcmp-login-run"
        subprocess.run(
            ["docker", "build", "-q", "-t", LOGIN_IMAGE, str(LOGIN_DIR)],
            check=True,
            capture_output=True,
        )
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        # Sin bind mount: no todos los runtimes (Colima) comparten cualquier directorio.
        run = subprocess.run(
            [
                "docker", "run", "--name", name,
                "-e", f"ARCA_CUIT={self.settings.cuit}",
                "-e", f"ARCA_CLAVE_FISCAL={self.settings.clave_fiscal}",
                LOGIN_IMAGE,
            ],
        )  # fmt: skip
        subprocess.run(
            ["docker", "cp", f"{name}:/out/.", str(out)], check=True, capture_output=True
        )
        subprocess.run(["docker", "rm", name], capture_output=True)
        if run.returncode != 0:
            raise LoginFallido(
                f"el login falló, mirá {out / 'mcmp_login_error.png'} para ver dónde quedó"
            )
        self.session.cookies.clear()
        self.cargar_cookies()

    # --- consulta ---------------------------------------------------------

    def _ajax(self, **params) -> dict:
        r = self.session.get(BASE + "ajax.do", params=params, timeout=30)
        try:
            data = r.json()
        except ValueError:
            raise SesionVencida() from None
        if data.get("estado") != "ok":
            raise RuntimeError(f"mcmp {params.get('f')}: {data}")
        return data

    def _consultar(self, desde: date, hasta: date) -> list[dict]:
        rango = f"{desde:%d/%m/%Y} - {hasta:%d/%m/%Y}"
        gen = self._ajax(
            f="generarConsulta", t="R", fechaEmision=rango, cuitConsultada=self.settings.cuit
        )
        id_consulta = gen["datos"]["idConsulta"]
        # Sin esta llamada la consulta queda en PE indefinidamente, aunque ya tenga data.
        self._ajax(f="estimarResultados", id=id_consulta)
        # Estados de la consulta: PE pendiente, PR procesando, TE terminada, ER error.
        # Con PR ya suele venir la data completa; se acepta apenas coincide con recordsTotal.
        limite = time.monotonic() + 180
        while time.monotonic() < limite:
            res = self._ajax(f="listaResultados", id=id_consulta)
            consulta = res["datos"]["consulta"]
            if consulta["estado"] == "ER":
                raise RuntimeError(f"mcmp: {consulta['error']}")
            data = res["datos"]["data"]
            if consulta["estado"] != "PE" and len(data) == res.get("recordsTotal"):
                return [parse_fila(f) for f in data]
            if consulta["estado"] == "TE":
                raise RuntimeError(
                    f"mcmp: la consulta terminó con {res.get('recordsTotal')} resultados "
                    f"pero devolvió {len(data)} (paginado server-side no soportado)"
                )
            time.sleep(2)
        raise RuntimeError("mcmp: la consulta no terminó de procesarse en 3 minutos")

    def recibidas(self, desde: date, hasta: date) -> list[dict]:
        """Comprobantes recibidos en el rango. Renueva la sesión una vez si venció."""
        if not self.cargar_cookies():
            self.login()
        try:
            return self._consultar(desde, hasta)
        except SesionVencida:
            self.login()
            return self._consultar(desde, hasta)
