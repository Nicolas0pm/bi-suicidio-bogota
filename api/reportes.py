"""Exportación de reportes en PDF (solo cifras agregadas)."""
from __future__ import annotations

import io
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

from . import analitica  # noqa: E402
from .proyeccion import ANIO_INICIO_PROYECCION, proyectar  # noqa: E402
from .repositorio import Repositorio  # noqa: E402

AZUL, NARANJA, GRIS = "#2a6fb0", "#d9822b", "#888888"


def _pagina_texto(pdf: PdfPages, titulo: str, lineas: list[str]) -> None:
    fig = plt.figure(figsize=(8.27, 11.69))
    fig.text(0.08, 0.92, titulo, fontsize=18, weight="bold")
    for i, linea in enumerate(lineas):
        fig.text(0.08, 0.86 - i * 0.03, linea, fontsize=11)
    pdf.savefig(fig)
    plt.close(fig)


def generar_pdf(repo: Repositorio, titulo: str, metodo: str = "regresion_lineal") -> bytes:
    res = analitica.resumen(repo)
    k = res["kpis"]
    serie = analitica.serie_anual(repo, "bogota_dc")
    completos = serie[serie["completo"]].set_index("anio")["casos"]
    proy_completa, descripcion = proyectar(completos, metodo)
    proy = proy_completa.loc[ANIO_INICIO_PROYECCION:]
    comp = analitica.comparar(repo, "bogota_dc", "zipaquira", 2015, 2100, "tasa_100k")

    buffer = io.BytesIO()
    with PdfPages(buffer) as pdf:
        _pagina_texto(pdf, titulo, [
            f"Generado: {datetime.now():%Y-%m-%d %H:%M}",
            "Fuente: INMLCF / SaluData (Bogotá D.C.); Secretaría de Salud de Zipaquirá (Anexo SAC 1232).",
            "Todas las cifras son agregadas; el reporte no contiene registros individuales.",
            "",
            f"Período analizado (Bogotá): {res['periodo']['desde']}–{res['periodo']['hasta']}",
            f"Total de casos de suicidio consumado: {k['total_casos']}",
            f"Promedio anual: {k['promedio_anual']} casos",
            f"Año con más casos: {k['anio_pico']} ({k['casos_anio_pico']} casos)",
            f"Tasa del último año completo: {k['tasa_ultimo_anio']} por 100.000 hab.",
            f"Proporción de hombres: {k['pct_hombres']} %",
            f"Razón del suicidio sin información: {res['pct_razon_sin_informacion']} % de los casos",
            "",
            f"Proyección ({descripcion}):",
            *[f"   {a}: {r.media:.0f} casos (IC 95 %: {r.inf:.0f} – {r.sup:.0f})" for a, r in proy.iterrows()],
            "",
            f"Comparación {comp['periodo_inicio']}–{comp['periodo_fin']} (tasa media por 100.000 hab.):",
            f"   Bogotá D.C.: {comp['valor_base']}   |   Zipaquirá: {comp['valor_comparado']}"
            f"   |   diferencia: {comp['resultado']:+}",
        ])

        fig, ejes = plt.subplots(2, 1, figsize=(8.27, 11.69))
        ejes[0].plot(completos.index, completos.values, "o-", color=AZUL, label="Histórico")
        ejes[0].plot(proy_completa.index, proy_completa["media"], "--", color=NARANJA, label="Proyección")
        ejes[0].fill_between(proy_completa.index, proy_completa["inf"], proy_completa["sup"], color=NARANJA,
                             alpha=0.2, label="IC 95 %")
        ejes[0].set_title("Bogotá D.C. — casos de suicidio por año")
        ejes[0].legend()
        ejes[0].grid(alpha=0.3)
        anios = [d["anio"] for d in comp["detalle"]]
        ejes[1].plot(anios, [d["tasa_base"] for d in comp["detalle"]], "o-", color=AZUL, label="Bogotá D.C.")
        ejes[1].plot(anios, [d["tasa_comparado"] for d in comp["detalle"]], "s-", color=GRIS, label="Zipaquirá")
        ejes[1].set_title("Tasa de suicidio por 100.000 habitantes")
        ejes[1].legend()
        ejes[1].grid(alpha=0.3)
        fig.tight_layout(pad=3)
        pdf.savefig(fig)
        plt.close(fig)

        fig, ejes = plt.subplots(2, 1, figsize=(8.27, 11.69))
        ciclo = res["por_ciclo_vital"]
        ejes[0].barh([d["categoria"] for d in ciclo], [d["casos"] for d in ciclo], color=AZUL)
        ejes[0].set_title("Casos por ciclo vital")
        loc = res["por_localidad"][:12][::-1]
        ejes[1].barh([d["categoria"] for d in loc], [d["casos"] for d in loc], color=AZUL)
        ejes[1].set_title("Casos por localidad (12 con más casos)")
        fig.tight_layout(pad=3)
        pdf.savefig(fig)
        plt.close(fig)
    return buffer.getvalue()
