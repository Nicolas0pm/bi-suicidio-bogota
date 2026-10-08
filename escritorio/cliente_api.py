"""Cliente HTTP de la API. Los tokens solo viven en memoria: nada se escribe en la memoria USB."""
from __future__ import annotations

import time

import requests


class ErrorApi(Exception):
    pass


class ClienteApi:
    def __init__(self, url_base: str) -> None:
        self.url = url_base.rstrip("/") + "/api/v1"
        self.sesion = requests.Session()
        self.id_token: str | None = None
        self.refresh_token: str | None = None
        self.expira = 0.0
        self.perfil: dict = {}

    # ----- sesión -----
    def iniciar_sesion(self, correo: str, clave: str) -> dict:
        datos = self._pedir("POST", "/auth/login", json={"correo": correo, "clave": clave}, autenticar=False)
        self._guardar_tokens(datos)
        self.perfil = self.get("/auth/yo")
        return self.perfil

    def cerrar_sesion(self) -> None:
        self.id_token = self.refresh_token = None
        self.perfil = {}

    def puede(self, permiso: str) -> bool:
        return permiso in self.perfil.get("permisos", [])

    def _guardar_tokens(self, datos: dict) -> None:
        self.id_token, self.refresh_token = datos["id_token"], datos["refresh_token"]
        self.expira = time.time() + int(datos.get("expira_en", 3600)) - 60

    def _renovar_si_hace_falta(self) -> None:
        if self.refresh_token and time.time() >= self.expira:
            self._guardar_tokens(self._pedir("POST", "/auth/refresh", json={"refresh_token": self.refresh_token},
                                             autenticar=False))

    # ----- llamadas -----
    def _pedir(self, metodo: str, ruta: str, autenticar: bool = True, **kwargs):
        if autenticar:
            self._renovar_si_hace_falta()
            kwargs.setdefault("headers", {})["Authorization"] = f"Bearer {self.id_token}"
        try:
            r = self.sesion.request(metodo, self.url + ruta, timeout=60, **kwargs)
        except requests.ConnectionError:
            raise ErrorApi("No hay conexión con la API. Verifique su conexión a internet y la URL del servidor.")
        except requests.Timeout:
            raise ErrorApi("La API tardó demasiado en responder.")
        if r.status_code >= 400:
            try:
                detalle = r.json().get("detail", r.text)
            except ValueError:
                detalle = r.text
            raise ErrorApi(f"Error {r.status_code}: {detalle}")
        return r.content if r.headers.get("content-type", "").startswith("application/pdf") else r.json()

    def get(self, ruta: str, **params):
        return self._pedir("GET", ruta, params=params)

    def post(self, ruta: str, cuerpo: dict | None = None):
        return self._pedir("POST", ruta, json=cuerpo or {})

    def patch(self, ruta: str, cuerpo: dict):
        return self._pedir("PATCH", ruta, json=cuerpo)
