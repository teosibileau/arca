"""Autenticación WSAA: firma del ticket de acceso (TRA) y login."""

import base64
import json
import secrets
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs7

TA_TTL = timedelta(hours=12)


def build_tra(service: str, now: datetime | None = None) -> bytes:
    """Arma el loginTicketRequest XML para un servicio dado."""
    now = now or datetime.now(timezone.utc)
    root = ET.Element("loginTicketRequest", version="1.0")
    header = ET.SubElement(root, "header")
    ET.SubElement(header, "uniqueId").text = str(secrets.randbelow(2**31))
    ET.SubElement(header, "generationTime").text = (now - timedelta(minutes=5)).isoformat(timespec="seconds")
    ET.SubElement(header, "expirationTime").text = (now + TA_TTL).isoformat(timespec="seconds")
    ET.SubElement(root, "service").text = service
    return ET.tostring(root, xml_declaration=True, encoding="UTF-8")


def sign_tra(tra: bytes, cert_path: Path, key_path: Path) -> str:
    """Firma el TRA como CMS (PKCS#7) y lo devuelve en base64."""
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    signed = (
        pkcs7.PKCS7SignatureBuilder()
        .set_data(tra)
        .add_signer(cert, key, hashes.SHA256())
        .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.Binary])
    )
    return base64.b64encode(signed).decode("ascii")


def parse_login_response(xml_response: str) -> dict:
    """Extrae token, sign y expiración del loginTicketResponse."""
    root = ET.fromstring(xml_response)
    return {
        "token": root.findtext("./credentials/token"),
        "sign": root.findtext("./credentials/sign"),
        "expiration": root.findtext("./header/expirationTime"),
    }


class Wsaa:
    """Obtiene y cachea tickets de acceso por servicio."""

    def __init__(self, settings):
        self.settings = settings

    def _cache_path(self, service: str) -> Path:
        return self.settings.data_dir / f"ta_{service}_{self.settings.env}.json"

    def get_ta(self, service: str) -> dict:
        cache = self._cache_path(service)
        if cache.exists():
            ta = json.loads(cache.read_text())
            if datetime.fromisoformat(ta["expiration"]) > datetime.now(timezone.utc) + timedelta(minutes=5):
                return ta
        ta = self._login(service)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(ta))
        return ta

    def _login(self, service: str) -> dict:
        from arca.transport import make_client

        tra = build_tra(service)
        cms = sign_tra(tra, self.settings.cert_path, self.settings.key_path)
        client = make_client(self.settings.urls["wsaa"])
        response = client.service.loginCms(in0=cms)
        return parse_login_response(response)
