import json
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from arca import mcmp
from arca.config import Settings

FIXTURE = Path(__file__).parent / "fixtures" / "mcmp_lista_resultados.json"


def _settings(tmp_path, clave="secreta"):
    return Settings(
        cuit=20111111112,
        cert_path=tmp_path / "c",
        key_path=tmp_path / "k",
        data_dir=tmp_path,
        clave_fiscal=clave,
        _env_file=None,
    )


def _resp(payload, ok=True):
    r = Mock()
    if ok:
        r.json.return_value = payload
    else:
        r.json.side_effect = ValueError("no json")
    return r


def test_parse_fila_mapea_columnas_posicionales():
    fila = json.loads(FIXTURE.read_text())["datos"]["data"][0]
    r = mcmp.parse_fila(fila)
    assert r == {
        "cuit_emisor": 30716581973,
        "denominacion_emisor": "HOGAR STORE SAS",
        "cbte_tipo": 6,
        "punto_venta": 100,
        "cbte_nro": 20912,
        "fecha": "2026-09-25",
        "cae": "86394766551705",
        "moneda": "PES",
        "cotizacion": 1.0,
        "neto_gravado": 0.0,
        "neto_no_gravado": 0.0,
        "exento": 0.0,
        "otros_tributos": 0.0,
        "iva": 0.0,
        "total": 114997.02,
    }


def test_rango_por_defecto_solapa_siete_dias():
    assert mcmp.rango_por_defecto("2026-09-25", hoy=date(2026, 9, 27)) == (
        date(2026, 9, 18),
        date(2026, 9, 27),
    )
    with pytest.raises(ValueError, match="--desde"):
        mcmp.rango_por_defecto(None)


def test_recibidas_genera_consulta_y_pollea_hasta_procesada(tmp_path):
    settings = _settings(tmp_path)
    settings.mcmp_cookies_path.write_text(
        json.dumps([{"name": "JSESSIONID", "value": "x", "domain": "fes.afip.gob.ar", "path": "/"}])
    )
    listo = json.loads(FIXTURE.read_text())
    pendiente = {
        "estado": "ok",
        "recordsTotal": 0,
        "datos": {"consulta": {"estado": "PE"}, "data": []},
    }
    session = Mock()
    session.get.side_effect = [
        _resp({"estado": "ok", "datos": {"idConsulta": "42", "estado": "PE"}}),
        _resp({"estado": "ok", "datos": {"serverSide": False}}),
        _resp(pendiente),
        _resp(listo),
    ]
    m = mcmp.Mcmp(settings, session=session)
    with patch("arca.mcmp.time.sleep"):
        filas = m.recibidas(date(2026, 9, 1), date(2026, 9, 27))

    assert [f["cbte_nro"] for f in filas] == [20912]
    gen = session.get.call_args_list[0].kwargs["params"]
    assert gen == {
        "f": "generarConsulta",
        "t": "R",
        "fechaEmision": "01/09/2026 - 27/09/2026",
        "cuitConsultada": 20111111112,
    }
    assert session.get.call_args_list[1].kwargs["params"] == {"f": "estimarResultados", "id": "42"}
    assert session.get.call_args_list[2].kwargs["params"] == {"f": "listaResultados", "id": "42"}
    session.cookies.set.assert_called_once_with(
        "JSESSIONID", "x", domain="fes.afip.gob.ar", path="/"
    )


def test_recibidas_reloguea_una_vez_si_la_sesion_vencio(tmp_path):
    settings = _settings(tmp_path)
    settings.mcmp_cookies_path.write_text("[]")
    session = Mock()
    session.get.side_effect = [
        _resp(None, ok=False),  # HTML de login: sesión vencida
        _resp({"estado": "ok", "datos": {"idConsulta": "1", "estado": "PE"}}),
        _resp({"estado": "ok", "datos": {"serverSide": False}}),
        _resp(json.loads(FIXTURE.read_text())),
    ]
    m = mcmp.Mcmp(settings, session=session)
    with patch.object(m, "login") as login:
        filas = m.recibidas(date(2026, 9, 1), date(2026, 9, 27))
    login.assert_called_once()
    assert len(filas) == 1


def test_recibidas_sin_cookies_hace_login_primero(tmp_path):
    settings = _settings(tmp_path)
    m = mcmp.Mcmp(settings, session=Mock())
    with patch.object(m, "login") as login, patch.object(m, "_consultar", return_value=[]):
        m.recibidas(date(2026, 9, 1), date(2026, 9, 27))
    login.assert_called_once()


def test_login_sin_clave_fiscal_falla_claro(tmp_path):
    m = mcmp.Mcmp(_settings(tmp_path, clave=None))
    with pytest.raises(mcmp.LoginFallido, match="ARCA_CLAVE_FISCAL"):
        m.login()


def test_login_corre_docker_y_carga_cookies(tmp_path):
    settings = _settings(tmp_path)

    def fake_run(cmd, **kw):
        if cmd[:2] == ["docker", "cp"]:
            settings.mcmp_cookies_path.write_text(
                json.dumps(
                    [
                        {
                            "name": "SESSION_TOKEN",
                            "value": "t",
                            "domain": ".fes.afip.gob.ar",
                            "path": "/",
                        }
                    ]
                )
            )
        return Mock(returncode=0)

    m = mcmp.Mcmp(settings)
    with patch("arca.mcmp.subprocess.run", side_effect=fake_run) as run:
        m.login()
    docker_run = next(c.args[0] for c in run.call_args_list if c.args[0][:2] == ["docker", "run"])
    assert "ARCA_CLAVE_FISCAL=secreta" in docker_run
    assert m.session.cookies.get("SESSION_TOKEN") == "t"


def test_login_fallido_apunta_al_screenshot(tmp_path):
    settings = _settings(tmp_path)

    def fake_run(cmd, **kw):
        return Mock(returncode=1 if cmd[:2] == ["docker", "run"] else 0)

    m = mcmp.Mcmp(settings)
    with (
        patch("arca.mcmp.subprocess.run", side_effect=fake_run),
        pytest.raises(mcmp.LoginFallido, match="mcmp_login_error.png"),
    ):
        m.login()
