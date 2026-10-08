"""ETL — Extracción y limpieza del recurso "Suicidio consumado" (Datos Abiertos Bogotá / SaluData).

Uso:
    python -m etl.limpieza                # descarga (si no existe) y genera etl/salida/casos_bogota.csv

Reglas de limpieza aplicadas:
  1. Se eliminan las filas con COD_LOCALIDAD = 0 ("Bogotá"): en la fuente son un duplicado
     exacto de las filas desagregadas por localidad (cada caso aparece dos veces).
  2. Se estandarizan categorías escritas con variaciones de formato
     ("Soltero (a)" -> "Soltero(a)", "Sin Información" -> "Sin información", etc.).
  3. Se renombran las columnas al modelo lógico (sección 10.2) y se asigna un id_caso técnico.
"""
from __future__ import annotations

import re
import unicodedata
import urllib.request
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent
ARCHIVO_FUENTE = RAIZ / "datos" / "suicidio_consumado_bogota.csv"
ARCHIVO_SALIDA = RAIZ / "salida" / "casos_bogota.csv"
URL_FUENTE = (
    "https://datosabiertos.bogota.gov.co/dataset/2b8464e3-3aca-4dcd-91a1-93dd06ddabbb/"
    "resource/0f7afde4-7597-41c2-9922-b2b8b5c2e1f8/download/osb_saludmental_suicidio_consumado_.csv"
)

COLUMNAS = {
    "ANO_DEL_HECHO": "anio_hecho",
    "MES_DEL_HECHO": "mes_hecho",
    "GRUPO_DE_EDAD_QUINQUENAL_": "grupo_edad_quinquenal",
    "CICLO_VITAL": "ciclo_vital",
    "SEXO_DE_LA_VICTIMA": "sexo",
    "ESTADO_CIVIL": "estado_civil",
    "ESCOLARIDAD": "escolaridad",
    "PERTENENCIA_GRUPAL": "pertenencia_grupal",
    "RAZON_DEL_SUICIDIO": "razon_suicidio",
    "COD_LOCALIDAD": "codigo_localidad",
    "LOCALIDAD_DEL_HECHO": "localidad",
}

ESTADO_CIVIL = {
    "soltero(a)": "Soltero(a)",
    "casado(a)": "Casado(a)",
    "viudo(a)": "Viudo(a)",
    "union libre": "Unión libre",
    "separado(a), divorciado(a)": "Separado(a), divorciado(a)",
    "separado(a)": "Separado(a), divorciado(a)",
    "sin informacion": "Sin información",
    "no aplica": "No aplica",
}

ESCOLARIDAD = {
    "educacion inicial y educacion preescolar": "Preescolar",
    "preescolar": "Preescolar",
    "educacion basica primaria": "Básica primaria",
    "basica primaria": "Básica primaria",
    "educacion basica secundaria o secundaria baja": "Básica secundaria",
    "basica secundaria": "Básica secundaria",
    "educacion media o secundaria alta": "Media (secundaria alta)",
    "educacion tecnica profesional y tecnologica": "Técnica / tecnológica",
    "tecnologica": "Técnica / tecnológica",
    "universitario": "Universitaria / profesional",
    "profesional": "Universitaria / profesional",
    "especializacion, maestria o equivalente": "Posgrado",
    "doctorado o equivalente": "Posgrado",
    "sin escolaridad": "Sin escolaridad",
    "ninguna": "Sin escolaridad",
    "sin informacion": "Sin información",
}

RAZON = {
    "conflicto con pareja o ex-pareja": "Conflicto con pareja o expareja",
    "conflicto con pareja o ex pareja": "Conflicto con pareja o expareja",
    "conflicto con pareja o expareja": "Conflicto con pareja o expareja",
    "abuso de sustancia y alcohol": "Abuso de sustancias y alcohol",
    "abuso de sustancias y alcohol": "Abuso de sustancias y alcohol",
    "escolares - educativas": "Escolares / educativas",
    "escolares / educativas": "Escolares / educativas",
    "escolares/educativas": "Escolares / educativas",
    "maltrato fisico - sexual - psicologico": "Maltrato físico - sexual - psicológico",
    "sin informacion": "Sin información",
}

MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
         "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


def clave(texto: str) -> str:
    """Normaliza un texto para compararlo: minúsculas, sin tildes, sin espacios dentro de '( a )'."""
    sin_tildes = "".join(c for c in unicodedata.normalize("NFD", str(texto)) if unicodedata.category(c) != "Mn")
    t = re.sub(r"\s+", " ", sin_tildes.strip().lower())
    return re.sub(r"\s*\(\s*a\s*\)", "(a)", t)


def estandarizar(serie: pd.Series, mapa: dict[str, str]) -> pd.Series:
    return serie.map(lambda v: mapa.get(clave(v), str(v).strip()))


def slug(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", clave(texto)).strip("_")


def descargar(destino: Path = ARCHIVO_FUENTE) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    if not destino.exists():
        print(f"Descargando {URL_FUENTE} ...")
        urllib.request.urlretrieve(URL_FUENTE, destino)
    return destino


def leer_fuente(ruta: Path = ARCHIVO_FUENTE) -> pd.DataFrame:
    return pd.read_csv(ruta, sep=";", encoding="utf-8-sig", dtype=str)


def limpiar(crudo: pd.DataFrame) -> pd.DataFrame:
    df = crudo.rename(columns=COLUMNAS)[list(COLUMNAS.values())].copy()
    for c in df.columns:
        df[c] = df[c].fillna("Sin información").str.strip()

    df["anio_hecho"] = pd.to_numeric(df["anio_hecho"], errors="coerce").astype("Int64")
    df["codigo_localidad"] = pd.to_numeric(df["codigo_localidad"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["anio_hecho", "codigo_localidad"])

    # Regla 1: "Bogotá" (código 0) duplica todos los casos que ya vienen por localidad.
    df = df[df["codigo_localidad"] != 0]

    df["estado_civil"] = estandarizar(df["estado_civil"], ESTADO_CIVIL)
    df["escolaridad"] = estandarizar(df["escolaridad"], ESCOLARIDAD)
    df["razon_suicidio"] = estandarizar(df["razon_suicidio"], RAZON)
    df["mes_hecho"] = df["mes_hecho"].map(lambda m: m.capitalize() if m.capitalize() in MESES else "Sin información")
    df["sexo"] = df["sexo"].str.capitalize()

    df["id_municipio"] = "bogota_dc"
    df["id_localidad"] = df["localidad"].map(slug)
    df["id_fuente"] = "inmlcf_saludata"
    df = df.sort_values(["anio_hecho", "codigo_localidad", "mes_hecho"]).reset_index(drop=True)
    df.insert(0, "id_caso", [f"bog_{a}_{i:05d}" for i, a in enumerate(df["anio_hecho"], start=1)])
    return df


def main() -> None:
    crudo = leer_fuente(descargar())
    limpio = limpiar(crudo)
    ARCHIVO_SALIDA.parent.mkdir(parents=True, exist_ok=True)
    limpio.to_csv(ARCHIVO_SALIDA, index=False, encoding="utf-8")
    print(f"Filas fuente: {len(crudo)} | casos únicos: {len(limpio)} -> {ARCHIVO_SALIDA}")
    print(limpio.groupby("anio_hecho").size().to_string())


if __name__ == "__main__":
    main()
