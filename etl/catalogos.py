"""Documentos de catálogo (roles, fuentes, municipios, indicadores agregados) construidos desde etl/datos.

Los usan tanto el cargador a Firestore como el modo demo de la API, para que ambos tengan la misma forma.
"""
from __future__ import annotations

import json
from pathlib import Path

DATOS = Path(__file__).resolve().parent / "datos"

ROLES = {
    "administrador": {"nombre_rol": "Administrador",
                      "permisos": ["leer", "cargar_datos", "generar_proyeccion", "generar_comparacion",
                                   "exportar_reporte", "gestionar_usuarios"]},
    "analista": {"nombre_rol": "Analista",
                 "permisos": ["leer", "cargar_datos", "generar_proyeccion", "generar_comparacion", "exportar_reporte"]},
    "consulta": {"nombre_rol": "Consulta", "permisos": ["leer", "exportar_reporte"]},
}

FUENTES = {
    "inmlcf_saludata": {
        "nombre": "INMLCF / SaluData — Observatorio de Salud de Bogotá",
        "tipo": "portal de datos abiertos (microdatos anonimizados)",
        "cobertura_temporal": "2015–actualidad",
        "url_referencia": "https://datosabiertos.bogota.gov.co/dataset/tasa-de-suicidio-en-bogota-d-c/"
                          "resource/0f7afde4-7597-41c2-9922-b2b8b5c2e1f8",
    },
    "dane_proyecciones": {
        "nombre": "DANE — Proyecciones de población",
        "tipo": "boletín estadístico",
        "cobertura_temporal": "2015–2026",
        "url_referencia": "https://www.dane.gov.co",
    },
    "zipaquira_sac_1232": {
        "nombre": "Secretaría de Salud de Zipaquirá — Boletines conducta e intento de suicidio (Anexo SAC 1232)",
        "tipo": "boletín epidemiológico (cifras agregadas)",
        "cobertura_temporal": "2020–semana 21 de 2026",
        "url_referencia": "Remitido al equipo en respuesta a solicitud de información (2026)",
    },
}


def leer_json(nombre: str) -> dict:
    return json.loads((DATOS / nombre).read_text(encoding="utf-8"))


def zipaquira() -> dict:
    return leer_json("zipaquira_anexo_sac_1232.json")


def poblacion_bogota() -> dict[int, int]:
    return {int(a): int(p) for a, p in leer_json("poblacion_bogota_dane.json")["poblacion"].items()}


def poblacion_zipaquira() -> dict[int, int]:
    """Población implícita en el boletín: casos / tasa * 100.000."""
    return {f["anio"]: round(f["casos"] / f["tasa_100k"] * 100_000)
            for f in zipaquira()["suicidio_consumado"] if f["tasa_100k"]}


def municipios() -> dict[str, dict]:
    pob_bog, pob_zip = poblacion_bogota(), poblacion_zipaquira()
    return {
        "bogota_dc": {"nombre": "Bogotá D.C.", "departamento": "Bogotá D.C.", "codigo_localidad": "1-21",
                      "poblacion_total": pob_bog[max(pob_bog)],
                      "poblacion_por_anio": {str(a): p for a, p in pob_bog.items()}},
        "zipaquira": {"nombre": "Zipaquirá", "departamento": "Cundinamarca", "codigo_localidad": None,
                      "poblacion_total": pob_zip[max(pob_zip)],
                      "poblacion_por_anio": {str(a): p for a, p in pob_zip.items()},
                      "detalle_boletin": {k: v for k, v in zipaquira().items()
                                          if k in ("intento_suicidio_2025_2026", "conducta_suicida_2025_2026")}},
    }


def indicadores_zipaquira() -> dict[str, dict]:
    """Indicadores agregados por año (colección indicadores_agregados)."""
    z = zipaquira()
    intento = {f["anio"]: f["tasa_100k"] for f in z["intento_suicidio_tasa_100k"]}
    docs = {}
    for f in z["suicidio_consumado"]:
        docs[f"zipaquira_{f['anio']}"] = {
            "id_municipio": "zipaquira", "anio": f["anio"], "casos_suicidio": f["casos"],
            "tasa_suicidio_100k": f["tasa_100k"], "tasa_intento_100k": intento.get(f["anio"]),
            "anio_completo": f["completo"], "id_fuente": "zipaquira_sac_1232",
        }
    return docs
