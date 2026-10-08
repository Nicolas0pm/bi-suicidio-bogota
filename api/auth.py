"""Autenticación (Firebase Authentication / JWT) y autorización por roles (RBAC)."""
from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque
from dataclasses import dataclass

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from etl.catalogos import ROLES
from .config import config
from .repositorio import repositorio

IDENTITY_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
SECURETOKEN_URL = "https://securetoken.googleapis.com/v1/token"
DURACION_TOKEN = 3600
DURACION_REFRESH = 7 * 24 * 3600

bearer = HTTPBearer(auto_error=False)


@dataclass
class Usuario:
    id_usuario: str
    firebase_uid: str
    correo: str
    id_rol: str

    @property
    def permisos(self) -> list[str]:
        return ROLES.get(self.id_rol, {}).get("permisos", [])


# ---------------- limitación de tasa (rate limiting) ----------------
_intentos: dict[str, deque] = defaultdict(deque)


def limitar_tasa(request: Request) -> None:
    ip = request.client.host if request.client else "desconocida"
    ventana, ahora = _intentos[ip], time.time()
    while ventana and ahora - ventana[0] > 60:
        ventana.popleft()
    if len(ventana) >= config.limite_login_por_minuto:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Demasiados intentos. Espere un minuto.")
    ventana.append(ahora)


# ---------------- emisión de tokens ----------------
def _token_demo(uid: str, tipo: str, duracion: int) -> str:
    ahora = int(time.time())
    return jwt.encode({"sub": uid, "typ": tipo, "iat": ahora, "exp": ahora + duracion}, config.demo_secreto, "HS256")


def iniciar_sesion(correo: str, clave: str) -> dict:
    if config.modo == "demo":
        usuario = next((u for u in repositorio().listar("usuarios", correo=correo.lower().strip())), None)
        if usuario is None or not hmac.compare_digest(clave, config.demo_clave):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Correo o contraseña incorrectos.")
        uid = usuario["firebase_uid"]
        return {"id_token": _token_demo(uid, "id", DURACION_TOKEN),
                "refresh_token": _token_demo(uid, "refresh", DURACION_REFRESH),
                "expira_en": DURACION_TOKEN, "rol": usuario["id_rol"]}

    respuesta = httpx.post(IDENTITY_URL, params={"key": config.firebase_web_api_key},
                           json={"email": correo, "password": clave, "returnSecureToken": True}, timeout=15)
    if respuesta.status_code != 200:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Correo o contraseña incorrectos.")
    datos = respuesta.json()
    usuario = repositorio().usuario_por_uid(datos["localId"])
    if usuario is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "El usuario no tiene un rol asignado en el sistema.")
    return {"id_token": datos["idToken"], "refresh_token": datos["refreshToken"],
            "expira_en": int(datos["expiresIn"]), "rol": usuario["id_rol"]}


def renovar_token(refresh_token: str) -> dict:
    if config.modo == "demo":
        try:
            datos = jwt.decode(refresh_token, config.demo_secreto, algorithms=["HS256"])
        except jwt.PyJWTError:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token inválido o vencido.")
        if datos.get("typ") != "refresh":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token inválido.")
        return {"id_token": _token_demo(datos["sub"], "id", DURACION_TOKEN),
                "refresh_token": refresh_token, "expira_en": DURACION_TOKEN}

    respuesta = httpx.post(SECURETOKEN_URL, params={"key": config.firebase_web_api_key},
                           data={"grant_type": "refresh_token", "refresh_token": refresh_token}, timeout=15)
    if respuesta.status_code != 200:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token inválido o vencido.")
    datos = respuesta.json()
    return {"id_token": datos["id_token"], "refresh_token": datos["refresh_token"],
            "expira_en": int(datos["expires_in"])}


# ---------------- verificación en cada solicitud ----------------
def _uid_desde_token(token: str) -> str:
    if config.modo == "demo":
        try:
            datos = jwt.decode(token, config.demo_secreto, algorithms=["HS256"])
        except jwt.PyJWTError:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido o vencido.")
        if datos.get("typ") != "id":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido.")
        return datos["sub"]

    from firebase_admin import auth as firebase_auth

    repositorio()  # asegura que firebase_admin esté inicializado
    try:
        return firebase_auth.verify_id_token(token)["uid"]
    except Exception:  # noqa: BLE001 — cualquier fallo de verificación es 401
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido o vencido.")


def usuario_actual(cred: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Usuario:
    if cred is None or cred.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falta el encabezado Authorization: Bearer <token>.")
    uid = _uid_desde_token(cred.credentials)
    doc = repositorio().usuario_por_uid(uid)
    if doc is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "El usuario no tiene un rol asignado en el sistema.")
    return Usuario(id_usuario=doc["id"], firebase_uid=uid, correo=doc.get("correo", ""), id_rol=doc["id_rol"])


def requiere(permiso: str):
    def dependencia(usuario: Usuario = Depends(usuario_actual)) -> Usuario:
        if permiso not in usuario.permisos:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Su rol no tiene permiso para esta operación.")
        return usuario
    return dependencia
