"""Carga inicial de Firebase Firestore con los catálogos, los casos limpios de Bogotá y los indicadores de Zipaquirá.

Uso (requiere FIREBASE_CREDENCIALES en .env apuntando a la llave de cuenta de servicio):
    python -m etl.cargar_firestore
    python -m etl.cargar_firestore --admin correo@ejemplo.com   # además asigna rol administrador a ese usuario
"""
from __future__ import annotations

import argparse
import json

from etl import catalogos, limpieza


def asegurar_web_api_key() -> None:
    """Si .env no tiene FIREBASE_WEB_API_KEY, registra una app web y guarda su clave (no es secreta)."""
    import os
    from pathlib import Path

    if os.getenv("FIREBASE_WEB_API_KEY"):
        return
    import time

    import firebase_admin
    from google.auth.transport.requests import AuthorizedSession

    from api.config import config

    cred = firebase_admin.get_app().credential.get_credential()
    sesion = AuthorizedSession(cred.with_scopes(["https://www.googleapis.com/auth/cloud-platform"]))
    base = f"https://firebase.googleapis.com/v1beta1/projects/{json.load(open(config.firebase_credenciales))['project_id']}"
    apps = sesion.get(f"{base}/webApps").json().get("apps", [])
    if not apps:
        operacion = sesion.post(f"{base}/webApps", json={"displayName": "app-escritorio-usb"}).json()
        while not operacion.get("done"):  # la creación es asíncrona
            time.sleep(2)
            operacion = sesion.get(f"https://firebase.googleapis.com/v1beta1/{operacion['name']}").json()
        apps = [operacion["response"]]
    clave = sesion.get(f"{base}/webApps/{apps[0]['appId']}/config").json()["apiKey"]
    env = Path(__file__).resolve().parent.parent / ".env"
    lineas = [l for l in (env.read_text(encoding="utf-8").splitlines() if env.exists() else [])
              if not l.startswith("FIREBASE_WEB_API_KEY=")]
    env.write_text("\n".join(lineas + [f"FIREBASE_WEB_API_KEY={clave}"]) + "\n", encoding="utf-8")
    os.environ["FIREBASE_WEB_API_KEY"] = clave
    print("FIREBASE_WEB_API_KEY guardada en .env")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin", help="Correo de un usuario ya creado en Firebase Authentication")
    args = parser.parse_args()

    import os
    os.environ["MODO"] = "firebase"
    from api.repositorio import RepositorioFirestore

    repo = RepositorioFirestore()
    asegurar_web_api_key()
    for coleccion, docs in {"roles": catalogos.ROLES, "fuentes_datos": catalogos.FUENTES,
                            "municipios": catalogos.municipios(),
                            "indicadores_agregados": catalogos.indicadores_zipaquira()}.items():
        for id_doc, doc in docs.items():
            repo.guardar(coleccion, doc, id_doc)
        print(f"{coleccion}: {len(docs)} documentos")

    casos = limpieza.limpiar(limpieza.leer_fuente(limpieza.descargar()))
    print(f"registros_casos: {repo.reemplazar_casos(casos)} documentos")

    if args.admin:
        from firebase_admin import auth
        cuenta = auth.get_user_by_email(args.admin)
        repo.guardar("usuarios", {"nombre": cuenta.display_name or args.admin, "correo": args.admin,
                                  "firebase_uid": cuenta.uid, "id_rol": "administrador"}, cuenta.uid)
        print(f"usuario administrador registrado: {args.admin}")


if __name__ == "__main__":
    main()
