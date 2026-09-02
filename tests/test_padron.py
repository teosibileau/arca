from types import SimpleNamespace as NS

from arca.padron import _condicion_from_persona


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
