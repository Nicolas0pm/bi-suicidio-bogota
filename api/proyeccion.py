"""Modelo estadístico de proyección de casos anuales (2030–2040) con intervalos de confianza."""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.exponential_smoothing.ets import ETSModel

METODOS = ("regresion_lineal", "ARIMA", "suavizado_exponencial")
ANIO_INICIO_PROYECCION = 2030
ANIO_FIN_PROYECCION = 2040


def _regresion_lineal(serie: pd.Series, anios: np.ndarray, alfa: float) -> pd.DataFrame:
    x = sm.add_constant(serie.index.to_numpy(dtype=float))
    modelo = sm.OLS(serie.to_numpy(dtype=float), x).fit()
    pred = modelo.get_prediction(sm.add_constant(anios.astype(float), has_constant="add"))
    marco = pred.summary_frame(alpha=alfa)
    return pd.DataFrame({"media": marco["mean"], "inf": marco["obs_ci_lower"], "sup": marco["obs_ci_upper"]})


def _arima(serie: pd.Series, pasos: int, alfa: float) -> tuple[pd.DataFrame, str]:
    y = pd.Series(serie.to_numpy(dtype=float))
    candidatos = [((1, 0, 0), "ct"), ((0, 1, 1), "t"), ((1, 1, 0), "t"), ((0, 1, 0), "t")]
    mejor = None
    for orden, tendencia in candidatos:
        try:
            ajuste = ARIMA(y, order=orden, trend=tendencia).fit()
        except Exception:  # noqa: BLE001 — algunos órdenes no convergen con series cortas
            continue
        if mejor is None or ajuste.aic < mejor[0].aic:
            mejor = (ajuste, orden)
    if mejor is None:
        raise ValueError("No fue posible ajustar un modelo ARIMA a la serie.")
    ajuste, orden = mejor
    marco = ajuste.get_forecast(pasos).summary_frame(alpha=alfa)
    resultado = pd.DataFrame({"media": marco["mean"], "inf": marco["mean_ci_lower"], "sup": marco["mean_ci_upper"]})
    return resultado.reset_index(drop=True), f"ARIMA{orden}"


def _suavizado_exponencial(serie: pd.Series, pasos: int, alfa: float) -> pd.DataFrame:
    y = pd.Series(serie.to_numpy(dtype=float))
    ajuste = ETSModel(y, error="add", trend="add", damped_trend=True).fit(disp=False)
    marco = ajuste.get_prediction(start=len(y), end=len(y) + pasos - 1).summary_frame(alpha=alfa)
    return pd.DataFrame({"media": marco["mean"], "inf": marco["pi_lower"], "sup": marco["pi_upper"]}).reset_index(drop=True)


def proyectar(serie: pd.Series, metodo: str, anio_fin: int = ANIO_FIN_PROYECCION,
              confianza: float = 0.95) -> tuple[pd.DataFrame, str]:
    """Proyecta una serie anual (índice = año, valor = número de casos) hasta `anio_fin`.

    Devuelve un DataFrame indexado por año con columnas media/inf/sup y una descripción del modelo.
    """
    if metodo not in METODOS:
        raise ValueError(f"Método no soportado: {metodo}. Use uno de {METODOS}.")
    serie = serie.sort_index().astype(float)
    if len(serie) < 5:
        raise ValueError("Se necesitan al menos 5 años completos para proyectar.")
    ultimo = int(serie.index.max())
    anios = np.arange(ultimo + 1, anio_fin + 1)
    alfa = 1 - confianza

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if metodo == "regresion_lineal":
            marco, descripcion = _regresion_lineal(serie, anios, alfa), "Regresión lineal (OLS)"
        elif metodo == "ARIMA":
            marco, descripcion = _arima(serie, len(anios), alfa)
        else:
            marco, descripcion = _suavizado_exponencial(serie, len(anios), alfa), "Holt amortiguado (ETS A,Ad,N)"

    marco.index = anios
    marco = marco.clip(lower=0)  # no existen casos negativos
    return marco, descripcion
