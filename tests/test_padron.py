from types import SimpleNamespace as NS
from unittest.mock import Mock

from arca.padron import (
    Padron,
    _actividades,
    _condicion_from_persona,
    _denominacion,
    _domicilio,
    _impuestos,
)


def _persona(mono=None, impuestos=None):
    rg = NS(impuesto=[NS(idImpuesto=i) for i in impuestos]) if impuestos is not None else None
    return NS(datosMonotributo=mono, datosRegimenGeneral=rg)


def test_condicion_monotributo_tiene_prioridad():
    assert _condicion_from_persona(_persona(mono=NS(), impuestos=[30])) == (
        6,
        "Responsable Monotributo",
    )


def test_condicion_impuesto_30_es_responsable_inscripto():
    assert _condicion_from_persona(_persona(impuestos=[218, 30])) == (
        1,
        "IVA Responsable Inscripto",
    )


def test_condicion_impuesto_32_es_exento():
    assert _condicion_from_persona(_persona(impuestos=[32])) == (4, "IVA Sujeto Exento")


def test_condicion_default_es_consumidor_final():
    assert _condicion_from_persona(_persona(impuestos=[])) == (5, "Consumidor Final")
    assert _condicion_from_persona(_persona()) == (5, "Consumidor Final")


def test_denominacion_prefiere_razon_social():
    persona = NS(datosGenerales=NS(razonSocial="ACME SA", nombre="X", apellido="Y"))
    assert _denominacion(persona) == "ACME SA"


def test_denominacion_arma_nombre_y_apellido():
    persona = NS(datosGenerales=NS(razonSocial=None, nombre="MARIA", apellido="DUFFY"))
    assert _denominacion(persona) == "MARIA DUFFY"


def test_denominacion_tolera_campos_nulos():
    persona = NS(datosGenerales=NS(razonSocial=None, nombre=None, apellido="DUFFY"))
    assert _denominacion(persona) == "DUFFY"


def _act(id_, desc):
    return NS(idActividad=id_, descripcionActividad=desc)


def test_actividades_principal_primero_y_sin_duplicados():
    mono = NS(
        actividadMonotributista=_act(620100, "CONSULTORES"),
        actividad=[_act(731009, "PUBLICIDAD")],
    )
    rg = NS(actividad=[_act(620100, "CONSULTORES")])
    persona = NS(datosMonotributo=mono, datosRegimenGeneral=rg)
    assert _actividades(persona) == ["620100  CONSULTORES", "731009  PUBLICIDAD"]


def test_actividades_sin_ramas_devuelve_vacio():
    assert _actividades(NS(datosMonotributo=None, datosRegimenGeneral=None)) == []


def test_impuestos_prefiere_rama_monotributo():
    mono = NS(impuesto=[NS(descripcionImpuesto="MONOTRIBUTO", estadoImpuesto="AC", periodo=202401)])
    rg = NS(impuesto=[NS(descripcionImpuesto="IVA", estadoImpuesto="AC", periodo=201408)])
    persona = NS(datosMonotributo=mono, datosRegimenGeneral=rg)
    assert _impuestos(persona) == [
        {"descripcion": "MONOTRIBUTO", "estado": "AC", "periodo": 202401}
    ]


def test_impuestos_sin_ramas_devuelve_vacio():
    assert _impuestos(NS(datosMonotributo=None, datosRegimenGeneral=None)) == []


def test_domicilio_arma_partes_y_decodifica_html():
    datos = NS(
        domicilioFiscal=NS(
            direccion="CAMINO DE LOS PA&#209;ILES 0",
            localidad=None,
            datoAdicional="LAS GOLONDRINAS",
            descripcionProvincia="CHUBUT",
            codPostal="8431",
        )
    )
    assert _domicilio(datos) == "CAMINO DE LOS PAÑILES 0, LAS GOLONDRINAS, CHUBUT, 8431"


def test_domicilio_ausente_devuelve_none():
    assert _domicilio(NS(domicilioFiscal=None)) is None


def _padron_con_respuesta(respuesta):
    p = Padron(Mock(cuit=20299528015), Mock(**{"get_ta.return_value": {"token": "t", "sign": "s"}}))
    p._client = Mock()
    p._client.service.getPersona.return_value = respuesta
    return p


def _persona_mono():
    return NS(
        datosGenerales=NS(razonSocial="ACME SA", nombre=None, apellido=None),
        datosMonotributo=NS(),
        datosRegimenGeneral=None,
    )


def test_consultar_desenvuelve_persona_de_homologacion():
    p = _padron_con_respuesta(NS(persona=_persona_mono()))
    assert p.consultar(30111222333)["denominacion"] == "ACME SA"


def test_consultar_acepta_respuesta_plana_de_produccion():
    p = _padron_con_respuesta(_persona_mono())
    d = p.consultar(30111222333)
    assert d["denominacion"] == "ACME SA"
    assert d["condicion_iva_id"] == 6
