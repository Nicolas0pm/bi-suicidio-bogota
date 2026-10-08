"""Carga inicial de Firebase Firestore con los catálogos, los casos limpios de Bogotá y los indicadores de Zipaquirá.

Uso (requiere FIREBASE_CREDENCIALES en .env apuntando a la llave de cuenta de servicio):
    python -m etl.cargar_firestore
    python -m etl.cargar_firestore --admin correo@ejemplo.com   # además asigna rol administrador a ese usuario
"""
from __future__ import annotations

import argparse

from etl import catalogos, limpieza


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin", help="Correo de un usuario ya creado en Firebase Authentication")
    args = parser.parse_args()

    import os
    os.environ["MODO"] = "firebase"
    from api.repositorio import RepositorioFirestore

    repo = RepositorioFirestore()
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
