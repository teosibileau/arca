"""Transporte HTTP para los web services de ARCA.

Los servidores de ARCA negocian TLS con parámetros DH que OpenSSL 3 rechaza
por default (DH_KEY_TOO_SMALL), así que se baja el security level a 1 solo
para estas conexiones.
"""

from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context


class LegacySSLAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def make_client(wsdl_url: str):
    from zeep import Client
    from zeep.transports import Transport

    session = Session()
    session.mount("https://", LegacySSLAdapter())
    return Client(wsdl_url, transport=Transport(session=session))
