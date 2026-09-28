"""Login y consulta reales contra el portal. Solo corre con ARCA_CLAVE_FISCAL en el entorno:

ARCA_CLAVE_FISCAL=... uv run pytest -m live
"""

import os
from datetime import date, timedelta

import pytest

from arca.config import Settings
from arca.mcmp import Mcmp

pytestmark = pytest.mark.live


@pytest.mark.skipif(not os.environ.get("ARCA_CLAVE_FISCAL"), reason="sin ARCA_CLAVE_FISCAL")
def test_login_y_consulta_reales(tmp_path):
    settings = Settings(data_dir=tmp_path)
    m = Mcmp(settings)
    m.login()
    assert settings.mcmp_cookies_path.exists()
    hoy = date.today()
    filas = m.recibidas(hoy - timedelta(days=30), hoy)
    assert isinstance(filas, list)
    for r in filas:
        assert r["cuit_emisor"] > 0 and r["fecha"] <= hoy.isoformat()
