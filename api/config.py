"""Configuración de la API, leída de variables de entorno (nunca credenciales en el código)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _cargar_env(ruta: Path = RAIZ / ".env") -> None:
    """Carga un archivo .env sencillo (CLAVE=valor) sin pisar variables ya definidas."""
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#") and "=" in linea:
            clave, valor = linea.split("=", 1)
            os.environ.setdefault(clave.strip(), valor.strip().strip('"'))


_cargar_env()


@dataclass(frozen=True)
class Config:
    # "firebase" (Firestore + Firebase Authentication) o "demo" (datos locales en el servidor, usuarios de prueba)
    modo: str = field(default_factory=lambda: os.getenv("MODO", "demo").lower())
    firebase_credenciales: str = field(default_factory=lambda: os.getenv("FIREBASE_CREDENCIALES", ""))
    firebase_web_api_key: str = field(default_factory=lambda: os.getenv("FIREBASE_WEB_API_KEY", ""))
    demo_secreto: str = field(default_factory=lambda: os.getenv("DEMO_SECRETO", "cambie-este-secreto-en-produccion"))
    demo_clave: str = field(default_factory=lambda: os.getenv("DEMO_CLAVE", "demo1234"))
    cache_segundos: int = field(default_factory=lambda: int(os.getenv("CACHE_SEGUNDOS", "600")))
    limite_login_por_minuto: int = field(default_factory=lambda: int(os.getenv("LIMITE_LOGIN_POR_MINUTO", "10")))
    archivo_auditoria: str = field(default_factory=lambda: os.getenv("ARCHIVO_AUDITORIA", str(RAIZ / "auditoria.log")))
    ruta_casos: Path = RAIZ / "etl" / "salida" / "casos_bogota.csv"
    ruta_poblacion: Path = RAIZ / "etl" / "datos" / "poblacion_bogota_dane.json"
    ruta_zipaquira: Path = RAIZ / "etl" / "datos" / "zipaquira_anexo_sac_1232.json"


config = Config()
