from pathlib import Path

from arca.config import Settings


def _settings(**kw):
    base = dict(cuit=20299528015, cert_path="c.crt", key_path="c.key", _env_file=None)
    return Settings(**{**base, **kw})


def test_ambiente_default_es_homologacion():
    s = _settings()
    assert s.env == "homo"
    assert "homo" in s.urls["wsaa"]


def test_urls_de_produccion():
    urls = _settings(env="prod").urls
    assert all("homo" not in u for u in urls.values())
    assert set(urls) == {"wsaa", "wsfe", "padron"}


def test_db_path_cuelga_de_data_dir():
    s = _settings(data_dir=Path("/x/datos"))
    assert s.db_path == Path("/x/datos/arca.sqlite3")
