import base64
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

from arca.wsaa import build_tra, parse_login_response, sign_tra


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
