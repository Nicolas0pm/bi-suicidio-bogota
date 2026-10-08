"""API REST — Sistema BI de suicidio en Bogotá D.C. con comparación con Zipaquirá.

Ejecutar:  uvicorn api.main:app --reload
Documentación interactiva: http://localhost:8000/docs
"""
from __future__ import annotations

import io
import logging
from datetime import datetime, timezone

import pandas as pd
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from etl import limpieza
from etl.catalogos import ROLES
from . import analitica, reportes
from .auth import Usuario, iniciar_sesion, limitar_tasa, renovar_token, requiere, usuario_actual
from .config import config
from .proyeccion import ANIO_FIN_PROYECCION, ANIO_INICIO_PROYECCION, METODOS, proyectar
from .repositorio import repositorio

auditoria = logging.getLogger("auditoria")
if not auditoria.handlers:
    manejador = logging.FileHandler(config.archivo_auditoria, encoding="utf-8")
    manejador.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    auditoria.addHandler(manejador)
    auditoria.setLevel(logging.INFO)

app = FastAPI(title="API BI Suicidio Bogotá D.C. – Zipaquirá", version="1.0.0",
              description="Datos agregados, proyecciones 2030–2040 y comparación territorial. "
                          "Nunca expone registros individuales (Ley 1581 de 2012).")
V1 = "/api/v1"


def auditar(usuario: Usuario, accion: str, detalle: str = "") -> None:
    auditoria.info("usuario=%s rol=%s accion=%s %s", usuario.id_usuario, usuario.id_rol, accion, detalle)


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------- esquemas ----------------
class Login(BaseModel):
    correo: str = Field(min_length=3, max_length=254)
    clave: str = Field(min_length=6)


class Refresh(BaseModel):
    refresh_token: str


class SolicitudProyeccion(BaseModel):
    id_municipio: str = "bogota_dc"
    metodo: str = Field("regresion_lineal", description=" | ".join(METODOS))
    anio_proyectado: int | None = Field(None, ge=ANIO_INICIO_PROYECCION, le=ANIO_FIN_PROYECCION,
                                        description="Si se omite, se proyecta todo 2030–2040.")


class SolicitudComparacion(BaseModel):
    id_municipio_base: str = "bogota_dc"
    id_municipio_comparado: str = "zipaquira"
    periodo_inicio: int = 2020
    periodo_fin: int = 2025
    indicador: str = Field("tasa_100k", description=" | ".join(analitica.INDICADORES))


class SolicitudReporte(BaseModel):
    titulo: str = Field("Reporte BI — Suicidio en Bogotá D.C. y Zipaquirá", max_length=120)
    metodo: str = "regresion_lineal"


class CambioRol(BaseModel):
    id_rol: str


# ---------------- autenticación ----------------
@app.post(f"{V1}/auth/login", tags=["auth"], dependencies=[Depends(limitar_tasa)])
def login(datos: Login):
    return iniciar_sesion(datos.correo, datos.clave)


@app.post(f"{V1}/auth/refresh", tags=["auth"], dependencies=[Depends(limitar_tasa)])
def refresh(datos: Refresh):
    return renovar_token(datos.refresh_token)


@app.get(f"{V1}/auth/yo", tags=["auth"])
def yo(usuario: Usuario = Depends(usuario_actual)):
    return {"id_usuario": usuario.id_usuario, "correo": usuario.correo, "id_rol": usuario.id_rol,
            "permisos": usuario.permisos}


@app.get("/salud", tags=["sistema"])
def salud():
    return {"estado": "ok", "modo": config.modo}


# ---------------- municipios ----------------
@app.get(f"{V1}/municipios", tags=["municipios"])
def municipios(_: Usuario = Depends(requiere("leer"))):
    return [{"id_municipio": m["id"], "nombre": m["nombre"], "departamento": m["departamento"],
             "poblacion_total": m["poblacion_total"]} for m in repositorio().listar("municipios")]


@app.get(f"{V1}/municipios/{{id_municipio}}/indicadores", tags=["municipios"])
def indicadores_municipio(id_municipio: str, _: Usuario = Depends(requiere("leer"))):
    try:
        serie = analitica.serie_anual(repositorio(), id_municipio)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Municipio no encontrado.")
    detalle = repositorio().obtener("municipios", id_municipio).get("detalle_boletin")
    return {"id_municipio": id_municipio, "serie": serie.where(serie.notna(), None).to_dict("records"),
            "detalle_boletin": detalle}


# ---------------- casos (siempre agregados) ----------------
@app.get(f"{V1}/casos", tags=["casos"])
def consultar_casos(
    anio: int | None = None,
    municipio: str = "bogota_dc",
    grupo_edad_quinquenal: str | None = None,
    ciclo_vital: str | None = None,
    sexo: str | None = None,
    localidad: str | None = None,
    agrupar_por: list[str] = Query(["anio_hecho", "grupo_edad_quinquenal", "sexo", "localidad"]),
    _: Usuario = Depends(requiere("leer")),
):
    if municipio != "bogota_dc":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Solo Bogotá D.C. tiene casos desagregados; para Zipaquirá use /municipios/zipaquira/indicadores.")
    invalidas = [d for d in agrupar_por if d not in analitica.DIMENSIONES]
    if invalidas or len(agrupar_por) > analitica.MAX_DIMENSIONES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"agrupar_por admite hasta {analitica.MAX_DIMENSIONES} de: {', '.join(analitica.DIMENSIONES)}")
    filtros = {"anio_hecho": anio, "grupo_edad_quinquenal": grupo_edad_quinquenal, "ciclo_vital": ciclo_vital,
               "sexo": sexo, "localidad": localidad}
    resultados = analitica.casos_agregados(repositorio().casos(), filtros, agrupar_por)
    return {"total": len(resultados), "resultados": resultados}


@app.get(f"{V1}/casos/{{id_agregado}}", tags=["casos"])
def detalle_casos(id_agregado: str, _: Usuario = Depends(requiere("leer"))):
    """id_agregado = '<año>_<localidad>' (p. ej. 2023_kennedy) o '<año>_bogota' para toda la ciudad."""
    try:
        anio_txt, lugar = id_agregado.split("_", 1)
        anio = int(anio_txt)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Formato esperado: <año>_<localidad>, p. ej. 2023_kennedy")
    df = repositorio().casos()
    df = df[df["anio_hecho"] == anio]
    if lugar != "bogota":
        df = df[df["id_localidad"] == lugar]
    if df.empty:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No hay casos para ese año y localidad.")
    return {"id": id_agregado, "anio_hecho": anio, "numero_casos": len(df),
            **{f"por_{c}": df[c].value_counts().to_dict() for c in ("sexo", "ciclo_vital", "mes_hecho")}}


@app.post(f"{V1}/casos", tags=["casos"], status_code=status.HTTP_201_CREATED)
async def cargar_casos(archivo: UploadFile = File(..., description="CSV original de Datos Abiertos Bogotá"),
                       usuario: Usuario = Depends(requiere("cargar_datos"))):
    contenido = await archivo.read()
    try:
        crudo = pd.read_csv(io.BytesIO(contenido), sep=";", encoding="utf-8-sig", dtype=str)
        limpio = limpieza.limpiar(crudo)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"El archivo no tiene el formato esperado: {e}")
    n = repositorio().reemplazar_casos(limpio)
    auditar(usuario, "cargar_casos", f"filas_fuente={len(crudo)} casos={n}")
    return {"filas_fuente": len(crudo), "casos_cargados": n, "duplicados_eliminados": len(crudo) - n}


# ---------------- proyecciones ----------------
@app.get(f"{V1}/proyecciones", tags=["proyecciones"])
def listar_proyecciones(municipio: str | None = None, _: Usuario = Depends(requiere("leer"))):
    filtros = {"id_municipio": municipio} if municipio else {}
    docs = repositorio().listar("proyecciones", **filtros)
    return sorted(docs, key=lambda d: (d.get("fecha_generacion", ""), d["anio_proyectado"]), reverse=True)


@app.post(f"{V1}/proyecciones", tags=["proyecciones"], status_code=status.HTTP_201_CREATED)
def generar_proyeccion(datos: SolicitudProyeccion, usuario: Usuario = Depends(requiere("generar_proyeccion"))):
    repo = repositorio()
    try:
        serie = analitica.serie_anual(repo, datos.id_municipio)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Municipio no encontrado.")
    historico = serie[serie["completo"]].set_index("anio")["casos"]
    try:
        marco, descripcion = proyectar(historico, datos.metodo)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    anios = [datos.anio_proyectado] if datos.anio_proyectado else range(ANIO_INICIO_PROYECCION, ANIO_FIN_PROYECCION + 1)
    fecha, resultados = ahora(), []
    for anio in anios:
        fila = marco.loc[anio]
        doc = {"id_municipio": datos.id_municipio, "anio_proyectado": int(anio),
               "valor_estimado": round(float(fila["media"]), 1),
               "intervalo_confianza_inf": round(float(fila["inf"]), 1),
               "intervalo_confianza_sup": round(float(fila["sup"]), 1),
               "metodo": datos.metodo, "modelo": descripcion,
               "id_usuario_generador": usuario.id_usuario, "fecha_generacion": fecha}
        id_doc = repo.guardar("proyecciones", doc, f"p_{anio}_{datos.id_municipio}_{datos.metodo}")
        resultados.append({"id_proyeccion": id_doc, **doc})
    auditar(usuario, "generar_proyeccion", f"municipio={datos.id_municipio} metodo={datos.metodo}")
    return {"id_municipio": datos.id_municipio, "metodo": datos.metodo, "modelo": descripcion,
            "historico": [{"anio": int(a), "casos": int(c)} for a, c in historico.items()],
            "resultados": resultados}


# ---------------- dashboard ----------------
@app.get(f"{V1}/dashboard/resumen", tags=["dashboard"])
def dashboard_resumen(anio_desde: int | None = None, anio_hasta: int | None = None,
                      _: Usuario = Depends(requiere("leer"))):
    return analitica.resumen(repositorio(), anio_desde, anio_hasta)


# ---------------- comparaciones ----------------
@app.get(f"{V1}/comparaciones", tags=["comparaciones"])
def listar_comparaciones(_: Usuario = Depends(requiere("leer"))):
    return sorted(repositorio().listar("comparaciones_regionales"), key=lambda d: d.get("fecha_generacion", ""),
                  reverse=True)


@app.post(f"{V1}/comparaciones", tags=["comparaciones"], status_code=status.HTTP_201_CREATED)
def generar_comparacion(datos: SolicitudComparacion, usuario: Usuario = Depends(requiere("generar_comparacion"))):
    try:
        resultado = analitica.comparar(repositorio(), datos.id_municipio_base, datos.id_municipio_comparado,
                                       datos.periodo_inicio, datos.periodo_fin, datos.indicador)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Municipio no encontrado.")
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    doc = {**resultado, "id_usuario_generador": usuario.id_usuario, "fecha_generacion": ahora()}
    id_doc = repositorio().guardar("comparaciones_regionales", doc)
    auditar(usuario, "generar_comparacion", f"id={id_doc} indicador={datos.indicador}")
    return {"id_comparacion": id_doc, **doc}


# ---------------- reportes ----------------
@app.post(f"{V1}/reportes", tags=["reportes"], status_code=status.HTTP_201_CREATED)
def crear_reporte(datos: SolicitudReporte, usuario: Usuario = Depends(requiere("exportar_reporte"))):
    if datos.metodo not in METODOS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Método no soportado. Use uno de {METODOS}.")
    doc = {"titulo": datos.titulo, "metodo": datos.metodo, "id_usuario": usuario.id_usuario,
           "fecha_generacion": ahora()}
    id_doc = repositorio().guardar("reportes", doc)
    return {"id_reporte": id_doc, **doc}


@app.get(f"{V1}/reportes/{{id_reporte}}/export", tags=["reportes"])
def exportar_reporte(id_reporte: str, usuario: Usuario = Depends(requiere("exportar_reporte"))):
    doc = repositorio().obtener("reportes", id_reporte)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reporte no encontrado.")
    pdf = reportes.generar_pdf(repositorio(), doc["titulo"], doc.get("metodo", "regresion_lineal"))
    auditar(usuario, "exportar_reporte", f"id={id_reporte}")
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="reporte_{id_reporte}.pdf"'})


# ---------------- usuarios (solo administrador) ----------------
@app.get(f"{V1}/usuarios", tags=["usuarios"])
def listar_usuarios(_: Usuario = Depends(requiere("gestionar_usuarios"))):
    # firebase_uid no se expone (diccionario de datos, sección 10.3)
    return [{"id_usuario": u["id"], "nombre": u.get("nombre"), "correo": u.get("correo"), "id_rol": u["id_rol"]}
            for u in repositorio().listar("usuarios")]


@app.patch(f"{V1}/usuarios/{{id_usuario}}/rol", tags=["usuarios"])
def cambiar_rol(id_usuario: str, datos: CambioRol, request: Request,
                usuario: Usuario = Depends(requiere("gestionar_usuarios"))):
    if datos.id_rol not in ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Rol inválido. Use uno de {list(ROLES)}.")
    if repositorio().obtener("usuarios", id_usuario) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado.")
    repositorio().actualizar("usuarios", id_usuario, {"id_rol": datos.id_rol})
    auditar(usuario, "cambiar_rol", f"objetivo={id_usuario} nuevo_rol={datos.id_rol}")
    return {"id_usuario": id_usuario, "id_rol": datos.id_rol}
