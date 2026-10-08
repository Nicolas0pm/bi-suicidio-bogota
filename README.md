# Sistema BI — Suicidio en Bogotá D.C. (2015–2025), proyección 2030–2040 y comparación con Zipaquirá

Este es el prototipo académico descrito en el documento del proyecto. Tiene cuatro capas:

| Capa | Carpeta | Tecnología |
|---|---|---|
| Presentación (app portable para USB) | `escritorio/` | Python + Tkinter + matplotlib, empaquetado con PyInstaller |
| Lógica de negocio (API REST) | `api/` | FastAPI, autenticación JWT con Firebase Authentication, RBAC |
| Persistencia | `etl/cargar_firestore.py`, `firestore.rules` | Firebase Firestore |
| ETL y modelado | `etl/`, `api/proyeccion.py` | pandas, statsmodels (regresión lineal, ARIMA, Holt) |

La app de escritorio **no guarda datos en la USB**. Solo lleva el `.exe` y un `config.json` con la URL de la API.
Para iniciar sesión y ver los datos necesita internet.

## Hallazgo importante en los datos de Bogotá

En el recurso "Suicidio consumado" de Datos Abiertos Bogotá, **cada caso aparece dos veces**. Una fila trae la
localidad real (códigos 1–21) y otra trae "Bogotá" (código 0). Los dos grupos coinciden fila por fila (se verificó
año por año y columna por columna). El ETL elimina las filas con código 0.

| Indicador 2015–2025 | Contando las filas tal cual vienen | Casos reales |
|---|---|---|
| Total de casos | 8.176 | **4.088** |
| Promedio anual | 743 | **372** |
| Año pico | 2023 (878) | **2023 (439)** |

**Hay que corregir estas cifras en el documento** (secciones 10 y 10.3). Los porcentajes por sexo y por ciclo vital
no cambian.

## Datos de Zipaquirá

Las cifras de Zipaquirá se transcribieron del Anexo SAC 1232 (boletines de la Secretaría de Salud, corte 5 de junio
de 2026) a `etl/datos/zipaquira_anexo_sac_1232.json`. Incluye la tasa de suicidio y los casos de 2020 a 2026
(2026 solo el primer semestre), la tasa de intento de suicidio y el perfil de intento y conducta suicida. Como el
boletín trae cifras ya agregadas, la comparación se hace sobre indicadores por año. Estos se guardan en la
colección `indicadores_agregados`.

> ⚠️ `etl/datos/poblacion_bogota_dane.json` contiene **proyecciones DANE aproximadas** que se usan como denominador
> de la tasa de Bogotá. Verifíquelas con la serie oficial antes de la entrega. Las tasas cambian de inmediato al
> editar ese archivo.

## 1. Probar todo en modo demo (sin Firebase)

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt          # Windows: .venv\Scripts\pip ...
.venv/bin/python -m etl.limpieza                   # genera etl/salida/casos_bogota.csv
.venv/bin/uvicorn api.main:app --reload            # API en http://localhost:8000/docs
```

En otra terminal:

```bash
.venv/bin/pip install -r escritorio/requirements.txt
.venv/bin/python escritorio/app.py
```

Usuarios de prueba: `administrador@demo.local`, `analista@demo.local` y `consulta@demo.local`. La contraseña es
`DEMO_CLAVE` (por defecto `demo1234`).

Para correr las pruebas: `.venv/bin/python -m pytest -q`

## 2. Modo producción con Firebase

1. En la consola de Firebase, cree el proyecto. Active **Authentication → Correo/contraseña** y **Firestore**.
2. Descargue la llave de cuenta de servicio (Configuración → Cuentas de servicio). **No la suba a GitHub.**
3. Copie `.env.example` a `.env` y configure `MODO=firebase`, `FIREBASE_CREDENCIALES` y `FIREBASE_WEB_API_KEY`.
4. Cree su usuario en Authentication y cargue la base de datos:
   ```bash
   .venv/bin/python -m etl.cargar_firestore --admin su_correo@ejemplo.com
   ```
5. Publique las reglas: `firebase deploy --only firestore:rules` (o péguelas en la consola).
6. Despliegue la API con HTTPS, por ejemplo en Render o Cloud Run con el `Dockerfile` incluido. Las variables
   del `.env` se configuran como variables de entorno del servicio, y la llave de servicio como *secret file*.
7. Ponga la URL pública de la API en `escritorio/config.json` (`api_url`).

## 3. Generar el ejecutable para la memoria USB

**Opción A: GitHub Actions.** Cada push a `main` que cambie `escritorio/` ejecuta el workflow
`Construir ejecutable portable`. Descargue el artefacto `BI_Suicidio_USB` (pestaña Actions) y copie la carpeta a la
USB.

**Opción B: un PC con Windows y Python.** Ejecute `escritorio\construir_windows.bat` y copie
`escritorio\dist\BI_Suicidio\` a la USB.

La carpeta contiene `BI_Suicidio.exe`, `config.json` y `LEEME.txt`. No se instala nada en el equipo.

## Endpoints (`/api/v1`)

| Método | Ruta | Permiso |
|---|---|---|
| POST | `/auth/login`, `/auth/refresh` | público (con límite de intentos) |
| GET | `/auth/yo` | autenticado |
| GET | `/municipios`, `/municipios/{id}/indicadores` | leer |
| GET | `/casos?anio=&sexo=&localidad=&agrupar_por=` | leer (solo conteos agregados, máximo 4 dimensiones) |
| GET | `/casos/{año}_{localidad}` | leer (agregado del año y la localidad, p. ej. `2023_kennedy`) |
| POST | `/casos` (CSV de la fuente) | cargar_datos (analista, administrador) |
| GET/POST | `/proyecciones` | leer / generar_proyeccion |
| GET | `/dashboard/resumen` | leer |
| GET/POST | `/comparaciones` | leer / generar_comparacion |
| POST | `/reportes`; GET `/reportes/{id}/export` (PDF) | exportar_reporte |
| GET | `/usuarios`; PATCH `/usuarios/{id}/rol` | gestionar_usuarios (administrador) |

Las operaciones de escritura se registran en `auditoria.log`.

### Diferencias con el documento (para actualizarlo)

- Se agregaron `GET /auth/yo`, `GET /municipios/{id}/indicadores` y `POST /reportes` (hay que crear el reporte
  antes de exportarlo).
- Se agregó la colección `indicadores_agregados` para las cifras agregadas de Zipaquirá. `municipios` guarda
  `poblacion_por_anio`.
- El id de cada documento de `usuarios` es el `firebase_uid` (así lo necesitan las reglas de Firestore).
- `GET /casos/{id}` devuelve un agregado por año y localidad, nunca un caso individual.
