import base64
import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

from arca.wsaa import Wsaa, build_tra, parse_login_response, sign_tra


def test_build_tra_structure():
    now = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)
    root = ET.fromstring(build_tra("wsfe", now=now))
    assert root.tag == "loginTicketRequest"
    assert root.findtext("service") == "wsfe"
    gen = datetime.fromisoformat(root.findtext("./header/generationTime"))
    exp = datetime.fromisoformat(root.findtext("./header/expirationTime"))
    assert gen < now < exp


def test_sign_tra_produces_base64_der(cert_and_key):
    cert_path, key_path = cert_and_key
    cms = sign_tra(build_tra("wsfe"), cert_path, key_path)
    der = base64.b64decode(cms)
    assert der[0] == 0x30  # SEQUENCE: DER válido


def test_parse_login_response():
    xml = """<loginTicketResponse>
      <header><expirationTime>2026-07-21T23:59:59-03:00</expirationTime></header>
      <credentials><token>tok</token><sign>sig</sign></credentials>
    </loginTicketResponse>"""
    ta = parse_login_response(xml)
    assert ta == {"token": "tok", "sign": "sig", "expiration": "2026-07-21T23:59:59-03:00"}


def _wsaa(tmp_path):
    return Wsaa(Mock(data_dir=tmp_path, env="homo"))


def _cache(tmp_path, expiration):
    ta = {"token": "cacheado", "sign": "s", "expiration": expiration.isoformat()}
    (tmp_path / "ta_wsfe_homo.json").write_text(json.dumps(ta))
    return ta


def test_get_ta_vigente_no_reloguea(tmp_path):
    ta = _cache(tmp_path, datetime.now(UTC) + timedelta(hours=2))
    w = _wsaa(tmp_path)
    with patch.object(Wsaa, "_login", side_effect=AssertionError("no debería loguear")):
        assert w.get_ta("wsfe") == ta


def test_get_ta_vencido_reloguea_y_actualiza_cache(tmp_path):
    _cache(tmp_path, datetime.now(UTC) - timedelta(hours=1))
    nuevo = {"token": "nuevo", "sign": "s", "expiration": "2099-01-01T00:00:00+00:00"}
    w = _wsaa(tmp_path)
    with patch.object(Wsaa, "_login", return_value=nuevo):
        assert w.get_ta("wsfe") == nuevo
    assert json.loads((tmp_path / "ta_wsfe_homo.json").read_text()) == nuevo


def test_get_ta_sin_cache_loguea(tmp_path):
    nuevo = {"token": "nuevo", "sign": "s", "expiration": "2099-01-01T00:00:00+00:00"}
    w = _wsaa(tmp_path)
    with patch.object(Wsaa, "_login", return_value=nuevo) as login:
        assert w.get_ta("wsfe") == nuevo
    login.assert_called_once_with("wsfe")
