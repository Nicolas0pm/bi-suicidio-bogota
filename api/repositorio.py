"""Acceso a datos: Firebase Firestore (producción) o memoria del servidor (modo demo).

En ambos casos los datos viven en el servidor; la aplicación de escritorio nunca guarda datos en la USB.
"""
from __future__ import annotations

import threading
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from etl import catalogos
from .config import config


class Repositorio(ABC):
    def __init__(self) -> None:
        self._casos: pd.DataFrame | None = None
        self._casos_cargados_en = 0.0
        self._lock = threading.Lock()

    # ----- casos (cacheados: Firestore cobra por lectura y la colección cambia muy poco) -----
    def casos(self) -> pd.DataFrame:
        with self._lock:
            vencido = time.time() - self._casos_cargados_en > config.cache_segundos
            if self._casos is None or vencido:
                self._casos = self._leer_casos()
                self._casos_cargados_en = time.time()
            return self._casos

    def reemplazar_casos(self, df: pd.DataFrame) -> int:
        with self._lock:
            self._escribir_casos(df)
            self._casos, self._casos_cargados_en = df.copy(), time.time()
        return len(df)

    @abstractmethod
    def _leer_casos(self) -> pd.DataFrame: ...

    @abstractmethod
    def _escribir_casos(self, df: pd.DataFrame) -> None: ...

    # ----- documentos genéricos -----
    @abstractmethod
    def obtener(self, coleccion: str, id_doc: str) -> dict | None: ...

    @abstractmethod
    def listar(self, coleccion: str, **filtros: Any) -> list[dict]: ...

    @abstractmethod
    def guardar(self, coleccion: str, doc: dict, id_doc: str | None = None) -> str: ...

    @abstractmethod
    def actualizar(self, coleccion: str, id_doc: str, cambios: dict) -> None: ...

    def usuario_por_uid(self, firebase_uid: str) -> dict | None:
        encontrados = self.listar("usuarios", firebase_uid=firebase_uid)
        return encontrados[0] if encontrados else None


class RepositorioMemoria(Repositorio):
    """Modo demo: catálogos y casos desde etl/, resultados generados en memoria del servidor."""

    def __init__(self) -> None:
        super().__init__()
        self._docs: dict[str, dict[str, dict]] = {
            "roles": {k: dict(v) for k, v in catalogos.ROLES.items()},
            "fuentes_datos": {k: dict(v) for k, v in catalogos.FUENTES.items()},
            "municipios": catalogos.municipios(),
            "indicadores_agregados": catalogos.indicadores_zipaquira(),
            "usuarios": {
                f"demo_{rol}": {"nombre": f"Usuario {rol}", "correo": f"{rol}@demo.local",
                             "firebase_uid": f"demo_{rol}", "id_rol": rol}
                for rol in catalogos.ROLES
            },
            "proyecciones": {}, "comparaciones_regionales": {}, "reportes": {},
        }

    def _leer_casos(self) -> pd.DataFrame:
        if not config.ruta_casos.exists():
            from etl import limpieza
            limpieza.main()
        return pd.read_csv(config.ruta_casos)

    def _escribir_casos(self, df: pd.DataFrame) -> None:
        pass  # en demo los casos cargados solo viven en memoria hasta reiniciar el servidor

    def obtener(self, coleccion, id_doc):
        doc = self._docs.get(coleccion, {}).get(id_doc)
        return {"id": id_doc, **doc} if doc else None

    def listar(self, coleccion, **filtros):
        return [{"id": k, **v} for k, v in self._docs.get(coleccion, {}).items()
                if all(v.get(c) == valor for c, valor in filtros.items())]

    def guardar(self, coleccion, doc, id_doc=None):
        id_doc = id_doc or uuid.uuid4().hex[:12]
        self._docs.setdefault(coleccion, {})[id_doc] = dict(doc)
        return id_doc

    def actualizar(self, coleccion, id_doc, cambios):
        self._docs[coleccion][id_doc].update(cambios)


class RepositorioFirestore(Repositorio):
    def __init__(self) -> None:
        super().__init__()
        import firebase_admin
        from firebase_admin import credentials, firestore

        if not firebase_admin._apps:
            cred = credentials.Certificate(config.firebase_credenciales) if config.firebase_credenciales \
                else credentials.ApplicationDefault()
            firebase_admin.initialize_app(cred)
        self.db = firestore.client()

    def _leer_casos(self) -> pd.DataFrame:
        filas = [{"id_caso": d.id, **d.to_dict()} for d in self.db.collection("registros_casos").stream()]
        return pd.DataFrame(filas)

    def _escribir_casos(self, df: pd.DataFrame) -> None:
        coleccion = self.db.collection("registros_casos")
        nuevos = set(df["id_caso"])
        lote, n = self.db.batch(), 0
        for doc in coleccion.list_documents():
            if doc.id not in nuevos:
                lote.delete(doc)
                n += 1
                if n % 450 == 0:
                    lote.commit()
                    lote = self.db.batch()
        for fila in df.to_dict("records"):
            id_caso = fila.pop("id_caso")
            lote.set(coleccion.document(id_caso), {k: (v.item() if hasattr(v, "item") else v) for k, v in fila.items()})
            n += 1
            if n % 450 == 0:  # Firestore admite máximo 500 operaciones por lote
                lote.commit()
                lote = self.db.batch()
        lote.commit()

    def obtener(self, coleccion, id_doc):
        snap = self.db.collection(coleccion).document(id_doc).get()
        return {"id": snap.id, **snap.to_dict()} if snap.exists else None

    def listar(self, coleccion, **filtros):
        from google.cloud.firestore_v1.base_query import FieldFilter

        consulta = self.db.collection(coleccion)
        for campo, valor in filtros.items():
            consulta = consulta.where(filter=FieldFilter(campo, "==", valor))
        return [{"id": d.id, **d.to_dict()} for d in consulta.stream()]

    def guardar(self, coleccion, doc, id_doc=None):
        ref = self.db.collection(coleccion).document(id_doc) if id_doc else self.db.collection(coleccion).document()
        ref.set(doc)
        return ref.id

    def actualizar(self, coleccion, id_doc, cambios):
        self.db.collection(coleccion).document(id_doc).update(cambios)


_repo: Repositorio | None = None


def repositorio() -> Repositorio:
    global _repo
    if _repo is None:
        _repo = RepositorioFirestore() if config.modo == "firebase" else RepositorioMemoria()
    return _repo
