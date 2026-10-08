"""Cálculos agregados: series anuales, tasas por 100.000 hab., dashboard y comparación territorial.

Ninguna función devuelve registros individuales: todo sale agrupado.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from .repositorio import Repositorio

DIMENSIONES = ("anio_hecho", "mes_hecho", "grupo_edad_quinquenal", "ciclo_vital", "sexo",
               "estado_civil", "escolaridad", "razon_suicidio", "localidad")
MAX_DIMENSIONES = 4  # limitar cruces evita que una combinación muy fina apunte a una persona
INDICADORES = ("tasa_100k", "casos", "variacion_pct")


def anio_ultimo_completo(anios: pd.Series) -> int:
    maximo = int(anios.max())
    return maximo - 1 if maximo >= date.today().year else maximo


def serie_anual(repo: Repositorio, id_municipio: str) -> pd.DataFrame:
    """Columnas: anio, casos, poblacion, tasa_100k, completo."""
    municipio = repo.obtener("municipios", id_municipio)
    if municipio is None:
        raise KeyError(id_municipio)
    poblacion = {int(a): p for a, p in municipio.get("poblacion_por_anio", {}).items()}

    if id_municipio == "bogota_dc":
        casos = repo.casos()
        conteo = casos.groupby("anio_hecho").size()
        ultimo = anio_ultimo_completo(casos["anio_hecho"])
        serie = pd.DataFrame({"anio": conteo.index.astype(int), "casos": conteo.to_numpy()})
        serie["completo"] = serie["anio"] <= ultimo
    else:
        docs = repo.listar("indicadores_agregados", id_municipio=id_municipio)
        serie = pd.DataFrame([{"anio": d["anio"], "casos": d["casos_suicidio"], "completo": d["anio_completo"],
                               "tasa_intento_100k": d.get("tasa_intento_100k")} for d in docs])

    serie["poblacion"] = serie["anio"].map(poblacion)
    serie["tasa_100k"] = (serie["casos"] / serie["poblacion"] * 100_000).round(2)
    return serie.sort_values("anio").reset_index(drop=True)


def casos_agregados(df: pd.DataFrame, filtros: dict[str, object], agrupar_por: list[str]) -> list[dict]:
    for col, valor in filtros.items():
        if valor is not None:
            df = df[df[col] == valor]
    if not agrupar_por:
        return [{"numero_casos": int(len(df))}]
    agrupado = df.groupby(agrupar_por).size().reset_index(name="numero_casos")
    return agrupado.sort_values(agrupar_por).to_dict("records")


def _distribucion(df: pd.DataFrame, columna: str) -> list[dict]:
    conteo = df[columna].value_counts()
    return [{"categoria": k, "casos": int(v), "pct": round(v / len(df) * 100, 1)} for k, v in conteo.items()]


def resumen(repo: Repositorio, anio_desde: int | None = None, anio_hasta: int | None = None) -> dict:
    casos = repo.casos()
    serie = serie_anual(repo, "bogota_dc")
    completos = serie[serie["completo"]]
    desde = anio_desde or int(completos["anio"].min())
    hasta = anio_hasta or int(completos["anio"].max())
    periodo = casos[(casos["anio_hecho"] >= desde) & (casos["anio_hecho"] <= hasta)]
    tramo = completos[(completos["anio"] >= desde) & (completos["anio"] <= hasta)]
    pico = tramo.loc[tramo["casos"].idxmax()] if len(tramo) else None
    return {
        "municipio": "bogota_dc",
        "periodo": {"desde": desde, "hasta": hasta},
        "kpis": {
            "total_casos": int(len(periodo)),
            "promedio_anual": round(float(tramo["casos"].mean()), 1) if len(tramo) else None,
            "anio_pico": int(pico["anio"]) if pico is not None else None,
            "casos_anio_pico": int(pico["casos"]) if pico is not None else None,
            "tasa_ultimo_anio": float(tramo.iloc[-1]["tasa_100k"]) if len(tramo) else None,
            "pct_hombres": round(float((periodo["sexo"] == "Hombre").mean() * 100), 1) if len(periodo) else None,
        },
        "tendencia": serie.to_dict("records"),
        "por_sexo": _distribucion(periodo, "sexo"),
        "por_ciclo_vital": _distribucion(periodo, "ciclo_vital"),
        "por_grupo_edad": sorted(_distribucion(periodo, "grupo_edad_quinquenal"), key=lambda d: d["categoria"]),
        "por_localidad": _distribucion(periodo, "localidad"),
        "por_razon": _distribucion(periodo[periodo["razon_suicidio"] != "Sin información"], "razon_suicidio")[:10],
        "pct_razon_sin_informacion": round(float((periodo["razon_suicidio"] == "Sin información").mean() * 100), 1)
        if len(periodo) else None,
    }


def comparar(repo: Repositorio, base: str, comparado: str, inicio: int, fin: int, indicador: str) -> dict:
    """resultado = valor(comparado) − valor(base); negativo si el comparado está por debajo del base."""
    if indicador not in INDICADORES:
        raise ValueError(f"Indicador no soportado: {indicador}. Use uno de {INDICADORES}.")
    series = {}
    for mun in (base, comparado):
        s = serie_anual(repo, mun)
        series[mun] = s[(s["anio"] >= inicio) & (s["anio"] <= fin) & s["completo"]].set_index("anio")
    anios = sorted(set(series[base].index) & set(series[comparado].index))
    if not anios:
        raise ValueError("Los municipios no tienen años completos en común dentro del período solicitado.")

    def valor(s: pd.DataFrame) -> float:
        s = s.loc[anios]
        if indicador == "tasa_100k":
            return round(float(s["tasa_100k"].mean()), 2)
        if indicador == "casos":
            return float(s["casos"].sum())
        primero, ultimo = s["tasa_100k"].iloc[0], s["tasa_100k"].iloc[-1]
        return round(float((ultimo - primero) / primero * 100), 2)

    v_base, v_comp = valor(series[base]), valor(series[comparado])
    detalle = [{"anio": int(a),
                "casos_base": int(series[base].at[a, "casos"]), "tasa_base": float(series[base].at[a, "tasa_100k"]),
                "casos_comparado": int(series[comparado].at[a, "casos"]),
                "tasa_comparado": float(series[comparado].at[a, "tasa_100k"])} for a in anios]
    return {"id_municipio_base": base, "id_municipio_comparado": comparado,
            "periodo_inicio": anios[0], "periodo_fin": anios[-1], "indicador": indicador,
            "valor_base": v_base, "valor_comparado": v_comp, "resultado": round(v_comp - v_base, 2),
            "detalle": detalle}
