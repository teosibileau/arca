from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

URLS = {
    "homo": {
        "wsaa": "https://wsaahomo.afip.gov.ar/ws/services/LoginCms?WSDL",
        "wsfe": "https://wswhomo.afip.gov.ar/wsfev1/service.asmx?WSDL",
        "padron": "https://awshomo.afip.gov.ar/sr-padron/webservices/personaServiceA5?WSDL",
    },
    "prod": {
        "wsaa": "https://wsaa.afip.gov.ar/ws/services/LoginCms?WSDL",
        "wsfe": "https://servicios1.afip.gov.ar/wsfev1/service.asmx?WSDL",
        "padron": "https://aws.afip.gov.ar/sr-padron/webservices/personaServiceA5?WSDL",
    },
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ARCA_", env_file=".env")

    cuit: int
    cert_path: Path
    key_path: Path
    env: Literal["homo", "prod"] = "homo"
    punto_venta: int = 1
    data_dir: Path = Path("data")

    @property
    def urls(self) -> dict[str, str]:
        return URLS[self.env]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "arca.sqlite3"
