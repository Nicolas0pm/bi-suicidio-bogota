import os

os.environ["MODO"] = "demo"
os.environ["LIMITE_LOGIN_POR_MINUTO"] = "1000"

import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402
from etl import limpieza  # noqa: E402

cliente = TestClient(app)


def token(rol: str) -> dict:
    r = cliente.post("/api/v1/auth/login", json={"correo": f"{rol}@demo.local", "clave": "demo1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['id_token']}"}


def test_limpieza_elimina_duplicados_de_bogota():
    crudo = limpieza.leer_fuente()
    limpio = limpieza.limpiar(crudo)
    assert len(limpio) * 2 == len(crudo)
    assert (limpio["codigo_localidad"] != 0).all()
    assert "Soltero (a)" not in set(limpio["estado_civil"])
    assert "Sin Información" not in set(limpio["escolaridad"])


def test_sin_token_401_y_clave_mala_401():
    assert cliente.get("/api/v1/municipios").status_code == 401
    r = cliente.post("/api/v1/auth/login", json={"correo": "consulta@demo.local", "clave": "incorrecta"})
    assert r.status_code == 401


def test_refresh():
    r = cliente.post("/api/v1/auth/login", json={"correo": "consulta@demo.local", "clave": "demo1234"})
    r2 = cliente.post("/api/v1/auth/refresh", json={"refresh_token": r.json()["refresh_token"]})
    assert r2.status_code == 200
    # un id_token no sirve como refresh token
    assert cliente.post("/api/v1/auth/refresh", json={"refresh_token": r.json()["id_token"]}).status_code == 401


def test_casos_agregados():
    r = cliente.get("/api/v1/casos", params={"anio": 2023, "agrupar_por": ["sexo"]}, headers=token("consulta"))
    assert r.status_code == 200
    total = sum(x["numero_casos"] for x in r.json()["resultados"])
    assert total == 439
    assert cliente.get("/api/v1/casos", params={"agrupar_por": ["id_caso"]},
                       headers=token("consulta")).status_code == 400


def test_detalle_agregado():
    r = cliente.get("/api/v1/casos/2023_kennedy", headers=token("consulta"))
    assert r.status_code == 200 and r.json()["numero_casos"] > 0
    assert cliente.get("/api/v1/casos/2023_noexiste", headers=token("consulta")).status_code == 404


def test_dashboard():
    r = cliente.get("/api/v1/dashboard/resumen", headers=token("consulta"))
    k = r.json()["kpis"]
    assert k["total_casos"] == 4088 and k["anio_pico"] == 2023


@pytest.mark.parametrize("metodo", ["regresion_lineal", "ARIMA", "suavizado_exponencial"])
def test_proyeccion(metodo):
    r = cliente.post("/api/v1/proyecciones", json={"metodo": metodo}, headers=token("analista"))
    assert r.status_code == 201, r.text
    res = r.json()["resultados"]
    assert [p["anio_proyectado"] for p in res] == list(range(2030, 2041))
    assert all(p["intervalo_confianza_inf"] <= p["valor_estimado"] <= p["intervalo_confianza_sup"] for p in res)


def test_consulta_no_puede_proyectar_ni_ver_usuarios():
    h = token("consulta")
    assert cliente.post("/api/v1/proyecciones", json={}, headers=h).status_code == 403
    assert cliente.get("/api/v1/usuarios", headers=h).status_code == 403


def test_comparacion_bogota_zipaquira():
    r = cliente.post("/api/v1/comparaciones", json={"periodo_inicio": 2020, "periodo_fin": 2025},
                     headers=token("analista"))
    assert r.status_code == 201, r.text
    c = r.json()
    assert [d["anio"] for d in c["detalle"]] == list(range(2020, 2026))
    assert c["resultado"] == pytest.approx(c["valor_comparado"] - c["valor_base"], abs=0.01)
    assert len(cliente.get("/api/v1/comparaciones", headers=token("consulta")).json()) >= 1


def test_reporte_pdf():
    h = token("consulta")
    rep = cliente.post("/api/v1/reportes", json={}, headers=h).json()
    pdf = cliente.get(f"/api/v1/reportes/{rep['id_reporte']}/export", headers=h)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


def test_admin_cambia_rol_y_no_expone_uid():
    h = token("administrador")
    usuarios = cliente.get("/api/v1/usuarios", headers=h).json()
    assert all("firebase_uid" not in u for u in usuarios)
    assert cliente.patch("/api/v1/usuarios/demo_consulta/rol", json={"id_rol": "jefe"}, headers=h).status_code == 400
    assert cliente.patch("/api/v1/usuarios/demo_consulta/rol", json={"id_rol": "consulta"}, headers=h).status_code == 200


def test_carga_csv_por_api():
    with open(limpieza.ARCHIVO_FUENTE, "rb") as f:
        r = cliente.post("/api/v1/casos", files={"archivo": ("s.csv", f, "text/csv")}, headers=token("analista"))
    assert r.status_code == 201, r.text
    assert r.json()["duplicados_eliminados"] == r.json()["casos_cargados"]
    assert isinstance(pd.read_csv(limpieza.ARCHIVO_SALIDA), pd.DataFrame)


def test_proyeccion_con_anios_elegidos():
    cuerpo = {"metodo": "regresion_lineal", "anio_desde": 2028, "anio_hasta": 2033,
              "historico_desde": 2018, "historico_hasta": 2025}
    r = cliente.post("/api/v1/proyecciones", json=cuerpo, headers=token("analista"))
    assert r.status_code == 201, r.text
    datos = r.json()
    assert [p["anio_proyectado"] for p in datos["resultados"]] == list(range(2028, 2034))
    assert [h["anio"] for h in datos["historico"]] == list(range(2018, 2026))
    assert datos["historico_desde"] == 2018 and datos["resultados"][0]["historico_hasta"] == 2025


def test_proyeccion_un_solo_anio_sigue_funcionando():
    r = cliente.post("/api/v1/proyecciones", json={"anio_proyectado": 2035}, headers=token("analista"))
    assert r.status_code == 201
    assert [p["anio_proyectado"] for p in r.json()["resultados"]] == [2035]


@pytest.mark.parametrize("cuerpo", [
    {"anio_desde": 2040, "anio_hasta": 2030},                      # rango al revés
    {"anio_desde": 2024, "anio_hasta": 2030},                      # empieza dentro del histórico
    {"historico_desde": 2023, "historico_hasta": 2025},            # menos de 5 años de base
    {"historico_desde": 2030, "historico_hasta": 2035},            # sin años históricos
])
def test_proyeccion_anios_invalidos(cuerpo):
    assert cliente.post("/api/v1/proyecciones", json=cuerpo, headers=token("analista")).status_code == 400


def test_proyeccion_no_pasa_de_2060():
    r = cliente.post("/api/v1/proyecciones", json={"anio_hasta": 2070}, headers=token("analista"))
    assert r.status_code == 422
