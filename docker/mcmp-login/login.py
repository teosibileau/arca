"""Login con clave fiscal y apertura de Mis Comprobantes. Deja las cookies en /out.

Flujo, tal como lo hace el portal:
  1. auth.afip.gob.ar: CUIT, después clave.
  2. GET portal/api/servicios/{cuit}/servicio/mcmp/autorizacion -> {token, sign}
  3. POST de formulario con token y sign a fes.afip.gob.ar/mcmp/jsp/index.do
  4. GET setearContribuyente.do?idContribuyente=0 (el CUIT propio)
Si falla, deja mcmp_login_error.png y .html para diagnosticar.
"""

import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

CUIT = os.environ["ARCA_CUIT"]
CLAVE = os.environ["ARCA_CLAVE_FISCAL"]
OUT = Path("/out")
MCMP = "https://fes.afip.gob.ar/mcmp/jsp/"


def log(msg):
    print(f"[mcmp-login] {msg}", flush=True)


with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context()
    page = ctx.new_page()
    try:
        log("login en auth.afip.gob.ar")
        page.goto("https://auth.afip.gob.ar/contribuyente_/login.xhtml")
        page.fill("#F1\\:username", CUIT)
        page.click("#F1\\:btnSiguiente")
        page.fill("#F1\\:password", CLAVE)
        page.click("#F1\\:btnIngresar")
        page.wait_for_url("**/portal/app/**", timeout=60000)
        page.wait_for_load_state("networkidle")

        log("pidiendo token de acceso a mcmp")
        tok = page.evaluate(
            f"""async () => {{
                const r = await fetch('/portal/api/servicios/{CUIT}/servicio/mcmp/autorizacion');
                return {{status: r.status, body: await r.text()}};
            }}"""
        )
        if tok["status"] != 200:
            raise RuntimeError(f"token mcmp: HTTP {tok['status']} {tok['body'][:300]}")
        tok = json.loads(tok["body"])

        log("abriendo Mis Comprobantes")
        mc = ctx.new_page()
        mc.set_content(
            f"""<form id=f method=POST action="{MCMP}index.do">
            <input name=token value='{tok["token"]}'>
            <input name=sign value='{tok["sign"]}'></form>"""
        )
        with mc.expect_navigation():
            mc.evaluate("document.getElementById('f').submit()")
        mc.goto(f"{MCMP}setearContribuyente.do?idContribuyente=0")
        if "Mis Comprobantes" not in mc.title():
            raise RuntimeError(f"no se abrió Mis Comprobantes (título: {mc.title()!r})")

        cookies = [c for c in ctx.cookies() if "fes.afip.gob.ar" in c["domain"]]
        (OUT / "mcmp_cookies.json").write_text(json.dumps(cookies, indent=1))
        log(f"ok, {len(cookies)} cookies guardadas")
    except Exception as e:
        cur = mc if "mc" in dir() else page
        log(f"ERROR en {cur.url}: {e}")
        cur.screenshot(path=str(OUT / "mcmp_login_error.png"), full_page=True)
        (OUT / "mcmp_login_error.html").write_text(cur.content())
        sys.exit(1)
    finally:
        browser.close()
