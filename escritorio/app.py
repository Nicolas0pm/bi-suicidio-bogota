"""Aplicación de escritorio portable — BI Suicidio Bogotá D.C. vs. Zipaquirá.

Se ejecuta desde una memoria USB sin instalar nada (empaquetada con PyInstaller).
Solo se lee config.json (URL de la API) junto al ejecutable; los datos se consultan en línea y no se guardan en la USB.

Desarrollo:  python escritorio/app.py
"""
from __future__ import annotations

import json
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import matplotlib

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from cliente_api import ClienteApi, ErrorApi  # noqa: E402

AZUL, NARANJA, GRIS, VERDE = "#2a6fb0", "#d9822b", "#7a7a7a", "#2e8b57"
METODOS = {"Regresión lineal": "regresion_lineal", "ARIMA": "ARIMA", "Suavizado exponencial (Holt)": "suavizado_exponencial"}
INDICADORES = {"Tasa media por 100.000 hab.": "tasa_100k", "Total de casos": "casos",
               "Variación % de la tasa": "variacion_pct"}
URL_POR_DEFECTO = "http://localhost:8000"


def carpeta_programa() -> Path:
    """Carpeta del .exe (en la USB) o del script en desarrollo."""
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def leer_config() -> dict:
    try:
        return json.loads((carpeta_programa() / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"api_url": URL_POR_DEFECTO}


def carpeta_documentos() -> Path:
    for candidata in (Path.home() / "Documents", Path.home() / "Documentos", Path.home()):
        if candidata.exists():
            return candidata
    return Path.home()


class Grafico(ttk.Frame):
    def __init__(self, padre, ancho=8, alto=4.5):
        super().__init__(padre)
        self.figura = Figure(figsize=(ancho, alto), dpi=100, layout="constrained")
        self.lienzo = FigureCanvasTkAgg(self.figura, master=self)
        self.lienzo.get_tk_widget().pack(fill="both", expand=True)

    def nuevo(self, filas=1, columnas=1):
        self.figura.clear()
        return self.figura.subplots(filas, columnas)

    def dibujar(self):
        self.lienzo.draw_idle()


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("BI Suicidio — Bogotá D.C. y Zipaquirá")
        self.geometry("1150x760")
        self.minsize(900, 600)
        estilo = ttk.Style(self)
        if "clam" in estilo.theme_names():
            estilo.theme_use("clam")
        estilo.configure("KPI.TLabel", font=("Segoe UI", 18, "bold"), foreground=AZUL)
        estilo.configure("Titulo.TLabel", font=("Segoe UI", 16, "bold"))
        estilo.configure("Nota.TLabel", foreground=GRIS)

        self.config_app = leer_config()
        self.api: ClienteApi | None = None
        self.contenedor = ttk.Frame(self)
        self.contenedor.pack(fill="both", expand=True)
        self.protocol("WM_DELETE_WINDOW", self.salir)
        self.pantalla_login()

    # ---------------- utilidades ----------------
    def limpiar(self):
        for w in self.contenedor.winfo_children():
            w.destroy()

    def en_segundo_plano(self, tarea, al_terminar, al_fallar=None):
        """Ejecuta llamadas de red sin congelar la ventana."""
        self.config(cursor="watch")

        def correr():
            try:
                resultado = tarea()
            except Exception as e:  # noqa: BLE001
                self.after(0, lambda err=e: (self.config(cursor=""), (al_fallar or self.error)(err)))
            else:
                self.after(0, lambda: (self.config(cursor=""), al_terminar(resultado)))
        threading.Thread(target=correr, daemon=True).start()

    def error(self, e: Exception):
        messagebox.showerror("Error", str(e) if isinstance(e, ErrorApi) else f"Error inesperado: {e}")

    def salir(self):
        if self.api:
            self.api.cerrar_sesion()
        self.destroy()

    # ---------------- login ----------------
    def pantalla_login(self):
        self.limpiar()
        marco = ttk.Frame(self.contenedor, padding=30)
        marco.place(relx=0.5, rely=0.45, anchor="center")
        ttk.Label(marco, text="Sistema BI — Suicidio en Bogotá D.C.", style="Titulo.TLabel").grid(columnspan=2, pady=(0, 4))
        ttk.Label(marco, text="Comparación con Zipaquirá · Proyección 2030–2040", style="Nota.TLabel").grid(
            columnspan=2, pady=(0, 20))

        variables = {"correo": tk.StringVar(), "clave": tk.StringVar(),
                     "url": tk.StringVar(value=self.config_app.get("api_url", URL_POR_DEFECTO))}
        for fila, (texto, clave, oculto) in enumerate(
                [("Correo", "correo", False), ("Contraseña", "clave", True), ("Servidor (API)", "url", False)], start=2):
            ttk.Label(marco, text=texto).grid(row=fila, column=0, sticky="e", padx=6, pady=5)
            entrada = ttk.Entry(marco, textvariable=variables[clave], width=38, show="•" if oculto else "")
            entrada.grid(row=fila, column=1, pady=5)
            if clave == "correo":
                entrada.focus_set()

        estado = ttk.Label(marco, text="", style="Nota.TLabel")
        estado.grid(row=6, columnspan=2, pady=(10, 0))

        def entrar(*_):
            correo, clave = variables["correo"].get().strip(), variables["clave"].get()
            if not correo or not clave:
                estado.config(text="Escriba su correo y contraseña.")
                return
            self.api = ClienteApi(variables["url"].get().strip() or URL_POR_DEFECTO)
            estado.config(text="Conectando…")
            boton.state(["disabled"])

            def fallo(e):
                boton.state(["!disabled"])
                estado.config(text="")
                self.error(e)
            self.en_segundo_plano(lambda: self.api.iniciar_sesion(correo, clave), lambda _: self.pantalla_principal(),
                                  fallo)

        boton = ttk.Button(marco, text="Iniciar sesión", command=entrar)
        boton.grid(row=5, columnspan=2, pady=(15, 0), sticky="ew")
        self.bind("<Return>", entrar)
        ttk.Label(marco, text="Requiere conexión a internet. No se guarda ningún dato en este equipo ni en la USB.",
                  style="Nota.TLabel").grid(row=7, columnspan=2, pady=(20, 0))

    # ---------------- principal ----------------
    def pantalla_principal(self):
        self.unbind("<Return>")
        self.limpiar()
        barra = ttk.Frame(self.contenedor, padding=(10, 6))
        barra.pack(fill="x")
        p = self.api.perfil
        ttk.Label(barra, text=f"{p.get('correo')} · rol: {p.get('id_rol')}", style="Nota.TLabel").pack(side="left")
        ttk.Button(barra, text="Cerrar sesión", command=self.cerrar_sesion).pack(side="right")

        pestanas = ttk.Notebook(self.contenedor)
        pestanas.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        PestanaResumen(pestanas, self)
        PestanaDemografia(pestanas, self)
        PestanaProyeccion(pestanas, self)
        PestanaComparacion(pestanas, self)
        PestanaReportes(pestanas, self)
        if self.api.puede("gestionar_usuarios"):
            PestanaUsuarios(pestanas, self)

    def cerrar_sesion(self):
        self.api.cerrar_sesion()
        self.api = None
        self.pantalla_login()


class Pestana(ttk.Frame):
    titulo = ""

    def __init__(self, notebook: ttk.Notebook, app: App):
        super().__init__(notebook, padding=12)
        self.app = app
        notebook.add(self, text=self.titulo)
        self.construir()
        self.cargar()

    def construir(self): ...

    def cargar(self): ...


class PestanaResumen(Pestana):
    titulo = "Resumen"

    def construir(self):
        self.kpis = ttk.Frame(self)
        self.kpis.pack(fill="x")
        self.grafico = Grafico(self)
        self.grafico.pack(fill="both", expand=True, pady=(10, 0))
        self.nota = ttk.Label(self, style="Nota.TLabel")
        self.nota.pack(anchor="w")

    def cargar(self):
        self.app.en_segundo_plano(lambda: self.app.api.get("/dashboard/resumen"), self.mostrar)

    def mostrar(self, r):
        k = r["kpis"]
        tarjetas = [("Casos " + f"{r['periodo']['desde']}–{r['periodo']['hasta']}", f"{k['total_casos']:,}".replace(",", ".")),
                    ("Promedio anual", f"{k['promedio_anual']}"),
                    ("Año pico", f"{k['anio_pico']} ({k['casos_anio_pico']})"),
                    ("Tasa último año / 100 mil", f"{k['tasa_ultimo_anio']}"),
                    ("Hombres", f"{k['pct_hombres']} %")]
        for i, (etiqueta, valor) in enumerate(tarjetas):
            caja = ttk.LabelFrame(self.kpis, text=etiqueta, padding=10)
            caja.grid(row=0, column=i, padx=5, sticky="nsew")
            self.kpis.columnconfigure(i, weight=1)
            ttk.Label(caja, text=valor, style="KPI.TLabel").pack()

        tendencia = r["tendencia"]
        eje = self.grafico.nuevo()
        completos = [t for t in tendencia if t["completo"]]
        parcial = [t for t in tendencia if not t["completo"]]
        eje.bar([t["anio"] for t in completos], [t["casos"] for t in completos], color=AZUL, label="Casos (año completo)")
        if parcial:
            eje.bar([t["anio"] for t in parcial], [t["casos"] for t in parcial], color=AZUL, alpha=0.35,
                    label="Año en curso (parcial)")
        eje.set_ylabel("Casos")
        eje.set_title("Suicidio consumado en Bogotá D.C. por año")
        eje.grid(axis="y", alpha=0.3)
        eje2 = eje.twinx()
        eje2.plot([t["anio"] for t in completos], [t["tasa_100k"] for t in completos], "o-", color=NARANJA,
                  label="Tasa por 100 mil")
        eje2.set_ylabel("Tasa por 100.000 hab.")
        eje2.set_ylim(bottom=0)
        lineas = eje.get_legend_handles_labels()
        lineas2 = eje2.get_legend_handles_labels()
        eje.legend(lineas[0] + lineas2[0], lineas[1] + lineas2[1], loc="lower left")
        self.grafico.dibujar()
        self.nota.config(text="Fuente: INMLCF / SaluData. Se eliminaron los registros 'Bogotá' (código 0), "
                              "que en la fuente duplican los casos por localidad.")


class PestanaDemografia(Pestana):
    titulo = "Distribución"

    def construir(self):
        self.grafico = Grafico(self, alto=6)
        self.grafico.pack(fill="both", expand=True)
        self.nota = ttk.Label(self, style="Nota.TLabel")
        self.nota.pack(anchor="w")

    def cargar(self):
        self.app.en_segundo_plano(lambda: self.app.api.get("/dashboard/resumen"), self.mostrar)

    def mostrar(self, r):
        (a, b), (c, d) = self.grafico.nuevo(2, 2)
        sexo = r["por_sexo"]
        a.pie([s["casos"] for s in sexo], labels=[s["categoria"] for s in sexo], autopct="%1.1f%%",
              colors=[AZUL, NARANJA, GRIS][:len(sexo)])
        a.set_title("Sexo")
        ciclo = sorted(r["por_ciclo_vital"], key=lambda x: x["categoria"])
        b.barh([x["categoria"] for x in ciclo], [x["casos"] for x in ciclo], color=AZUL)
        b.set_title("Ciclo vital")
        loc = [x for x in r["por_localidad"] if x["categoria"] != "Localidad Desconocida"][:10][::-1]
        c.barh([x["categoria"] for x in loc], [x["casos"] for x in loc], color=AZUL)
        c.set_title("10 localidades con más casos")
        razon = r["por_razon"][:7][::-1]
        d.barh([x["categoria"][:32] for x in razon], [x["casos"] for x in razon], color=NARANJA)
        d.set_title("Razón registrada (sin contar 'Sin información')")
        for eje in (b, c, d):
            eje.tick_params(labelsize=8)
        self.grafico.dibujar()
        self.nota.config(text=f"El {r['pct_razon_sin_informacion']} % de los casos no tiene razón registrada: "
                              "interprete esa gráfica con cautela.")


class PestanaProyeccion(Pestana):
    titulo = "Proyección 2030–2040"

    def construir(self):
        controles = ttk.Frame(self)
        controles.pack(fill="x")
        ttk.Label(controles, text="Municipio:").pack(side="left")
        self.municipio = ttk.Combobox(controles, values=["bogota_dc", "zipaquira"], state="readonly", width=12)
        self.municipio.set("bogota_dc")
        self.municipio.pack(side="left", padx=(4, 14))
        ttk.Label(controles, text="Método:").pack(side="left")
        self.metodo = ttk.Combobox(controles, values=list(METODOS), state="readonly", width=28)
        self.metodo.set("Regresión lineal")
        self.metodo.pack(side="left", padx=4)
        for combo in (self.municipio, self.metodo):
            combo.bind("<<ComboboxSelected>>", lambda _: self.cargar())
        self.boton = ttk.Button(controles, text="Generar proyección", command=self.generar)
        self.boton.pack(side="left", padx=10)
        if not self.app.api.puede("generar_proyeccion"):
            self.boton.state(["disabled"])
            ttk.Label(controles, text="(su rol solo puede ver proyecciones ya generadas)", style="Nota.TLabel").pack(side="left")

        cuerpo = ttk.Panedwindow(self, orient="horizontal")
        cuerpo.pack(fill="both", expand=True, pady=(10, 0))
        self.grafico = Grafico(cuerpo)
        cuerpo.add(self.grafico, weight=3)
        self.tabla = ttk.Treeview(cuerpo, columns=("anio", "valor", "inf", "sup"), show="headings", height=12)
        for col, texto, ancho in [("anio", "Año", 60), ("valor", "Estimado", 80), ("inf", "IC 95 % inf.", 90),
                                  ("sup", "IC 95 % sup.", 90)]:
            self.tabla.heading(col, text=texto)
            self.tabla.column(col, width=ancho, anchor="center")
        cuerpo.add(self.tabla, weight=1)
        self.nota = ttk.Label(self, style="Nota.TLabel", wraplength=1000, justify="left")
        self.nota.pack(anchor="w", pady=(6, 0))

    def cargar(self):
        def tarea():
            mun = self.municipio.get()
            serie = self.app.api.get(f"/municipios/{mun}/indicadores")["serie"]
            guardadas = self.app.api.get("/proyecciones", municipio=mun)
            return serie, guardadas
        self.app.en_segundo_plano(tarea, self.mostrar_guardadas)

    def mostrar_guardadas(self, datos):
        serie, guardadas = datos
        historico = [{"anio": s["anio"], "casos": s["casos"]} for s in serie if s["completo"]]
        metodo = METODOS[self.metodo.get()]
        resultados = sorted([g for g in guardadas if g["metodo"] == metodo], key=lambda g: g["anio_proyectado"])
        # quedarse con la generación más reciente de cada año
        por_anio = {}
        for g in sorted(resultados, key=lambda g: g.get("fecha_generacion", "")):
            por_anio[g["anio_proyectado"]] = g
        self.mostrar({"historico": historico, "resultados": [por_anio[a] for a in sorted(por_anio)],
                      "modelo": resultados[0]["modelo"] if resultados else None})

    def generar(self):
        cuerpo = {"id_municipio": self.municipio.get(), "metodo": METODOS[self.metodo.get()]}
        self.app.en_segundo_plano(lambda: self.app.api.post("/proyecciones", cuerpo), self.mostrar)

    def mostrar(self, r):
        eje = self.grafico.nuevo()
        h = r["historico"]
        eje.plot([x["anio"] for x in h], [x["casos"] for x in h], "o-", color=AZUL, label="Histórico")
        self.tabla.delete(*self.tabla.get_children())
        res = r["resultados"]
        if res:
            anios = [x["anio_proyectado"] for x in res]
            eje.plot(anios, [x["valor_estimado"] for x in res], "o--", color=NARANJA, label="Proyección")
            eje.fill_between(anios, [x["intervalo_confianza_inf"] for x in res],
                             [x["intervalo_confianza_sup"] for x in res], color=NARANJA, alpha=0.2, label="IC 95 %")
            for x in res:
                self.tabla.insert("", "end", values=(x["anio_proyectado"], x["valor_estimado"],
                                                     x["intervalo_confianza_inf"], x["intervalo_confianza_sup"]))
            self.nota.config(text=f"Modelo: {r.get('modelo')}. La proyección supone que la tendencia observada se "
                                  "mantiene; el intervalo de confianza se amplía con el horizonte. "
                                  "Zipaquirá tiene pocos años y casos, por lo que su intervalo es muy amplio.")
        else:
            self.nota.config(text="Aún no hay proyecciones guardadas para este método. "
                                  + ("Pulse «Generar proyección»." if self.app.api.puede("generar_proyeccion")
                                     else "Pida a un analista que la genere."))
        eje.set_title(f"Casos de suicidio — {self.municipio.get()}")
        eje.set_ylim(bottom=0)
        eje.grid(alpha=0.3)
        eje.legend(loc="upper left")
        self.grafico.dibujar()


class PestanaComparacion(Pestana):
    titulo = "Bogotá vs. Zipaquirá"

    def construir(self):
        controles = ttk.Frame(self)
        controles.pack(fill="x")
        ttk.Label(controles, text="Desde").pack(side="left")
        self.desde = ttk.Spinbox(controles, from_=2015, to=2030, width=6)
        self.desde.set(2020)
        self.desde.pack(side="left", padx=4)
        ttk.Label(controles, text="Hasta").pack(side="left")
        self.hasta = ttk.Spinbox(controles, from_=2015, to=2030, width=6)
        self.hasta.set(2025)
        self.hasta.pack(side="left", padx=4)
        ttk.Label(controles, text="Indicador").pack(side="left", padx=(12, 0))
        self.indicador = ttk.Combobox(controles, values=list(INDICADORES), state="readonly", width=26)
        self.indicador.set("Tasa media por 100.000 hab.")
        self.indicador.pack(side="left", padx=4)
        self.boton = ttk.Button(controles, text="Generar comparación", command=self.generar)
        self.boton.pack(side="left", padx=10)
        if not self.app.api.puede("generar_comparacion"):
            self.boton.state(["disabled"])

        self.resultado = ttk.Label(self, text="", style="Titulo.TLabel")
        self.resultado.pack(anchor="w", pady=(10, 0))
        self.grafico = Grafico(self, alto=4)
        self.grafico.pack(fill="both", expand=True)
        self.texto = tk.Text(self, height=7, wrap="word", relief="flat", background=self.app.cget("background"))
        self.texto.pack(fill="x")

    def cargar(self):
        def tarea():
            return (self.app.api.get("/municipios/bogota_dc/indicadores"),
                    self.app.api.get("/municipios/zipaquira/indicadores"),
                    self.app.api.get("/comparaciones"))
        self.app.en_segundo_plano(tarea, self.mostrar)

    def generar(self):
        try:
            cuerpo = {"periodo_inicio": int(self.desde.get()), "periodo_fin": int(self.hasta.get()),
                      "indicador": INDICADORES[self.indicador.get()]}
        except ValueError:
            messagebox.showwarning("Datos inválidos", "Los años deben ser números.")
            return
        self.app.en_segundo_plano(lambda: self.app.api.post("/comparaciones", cuerpo), lambda _: self.cargar())

    def mostrar(self, datos):
        bog, zip_, comparaciones = datos
        sb = [s for s in bog["serie"] if s["completo"] and s["anio"] >= 2020]
        sz = [s for s in zip_["serie"] if s["completo"]]
        a, b = self.grafico.nuevo(1, 2)
        a.plot([s["anio"] for s in sb], [s["tasa_100k"] for s in sb], "o-", color=AZUL, label="Bogotá D.C.")
        a.plot([s["anio"] for s in sz], [s["tasa_100k"] for s in sz], "s-", color=VERDE, label="Zipaquirá")
        a.axhline(5, color=GRIS, ls=":", label="Meta PDSP 2031 (5,0)")
        a.set_title("Tasa de suicidio por 100.000 hab.")
        a.set_ylim(bottom=0)
        a.legend(fontsize=8)
        a.grid(alpha=0.3)
        intento = [s for s in sz if s.get("tasa_intento_100k")]
        b.bar([s["anio"] for s in intento], [s["tasa_intento_100k"] for s in intento], color=VERDE, alpha=0.7)
        b.set_title("Zipaquirá: intento de suicidio por 100.000 hab.")
        b.grid(axis="y", alpha=0.3)
        self.grafico.dibujar()

        if comparaciones:
            c = comparaciones[0]
            signo = "por encima" if c["resultado"] > 0 else "por debajo" if c["resultado"] < 0 else "igual"
            self.resultado.config(
                text=f"{c['indicador']} {c['periodo_inicio']}–{c['periodo_fin']}: Bogotá {c['valor_base']} · "
                     f"Zipaquirá {c['valor_comparado']} → Zipaquirá {abs(c['resultado'])} {signo}")
        else:
            self.resultado.config(text="Sin comparaciones guardadas todavía.")

        det = (zip_.get("detalle_boletin") or {})
        intento_d = det.get("intento_suicidio_2025_2026", {})
        conducta = det.get("conducta_suicida_2025_2026", {})
        self.texto.config(state="normal")
        self.texto.delete("1.0", "end")
        self.texto.insert("end", (
            "Zipaquirá (boletín Secretaría de Salud, corte 5 de junio de 2026, Anexo SAC 1232):\n"
            f"• Intento de suicidio 2025–2026: {intento_d.get('casos')} casos; {intento_d.get('pct_mujeres')} % mujeres; "
            f"{intento_d.get('intentos_previos_pct')} % con intentos previos; mecanismo principal: intoxicación "
            f"({(intento_d.get('mecanismo_pct') or {}).get('Intoxicación')} %).\n"
            f"• Conducta suicida: {conducta.get('casos')} casos en {conducta.get('personas')} personas; "
            f"{conducta.get('pct_mujeres')} % mujeres; {conducta.get('pct_solteros')} % solteros.\n"
            "• Zipaquirá entrega cifras ya agregadas, por eso la comparación se hace sobre indicadores por año "
            "y no sobre atributos de cada caso. Con tan pocos casos al año, la tasa de Zipaquirá varía mucho."))
        self.texto.config(state="disabled")


class PestanaReportes(Pestana):
    titulo = "Reportes"

    def construir(self):
        ttk.Label(self, text="Exportar reporte en PDF", style="Titulo.TLabel").pack(anchor="w")
        ttk.Label(self, text="Incluye indicadores, tendencia, proyección 2030–2040 y comparación con Zipaquirá. "
                             "Solo contiene cifras agregadas.", style="Nota.TLabel").pack(anchor="w", pady=(2, 12))
        fila = ttk.Frame(self)
        fila.pack(anchor="w")
        ttk.Label(fila, text="Título:").pack(side="left")
        self.titulo_var = tk.StringVar(value="Reporte BI — Suicidio en Bogotá D.C. y Zipaquirá")
        ttk.Entry(fila, textvariable=self.titulo_var, width=55).pack(side="left", padx=4)
        ttk.Label(fila, text="Método:").pack(side="left", padx=(10, 0))
        self.metodo = ttk.Combobox(fila, values=list(METODOS), state="readonly", width=26)
        self.metodo.set("Regresión lineal")
        self.metodo.pack(side="left", padx=4)
        ttk.Button(self, text="Generar y guardar PDF…", command=self.exportar).pack(anchor="w", pady=14)
        ttk.Label(self, text="Por seguridad, guarde el reporte en el equipo (Documentos) y no en la memoria USB.",
                  style="Nota.TLabel").pack(anchor="w")

    def exportar(self):
        destino = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
                                               initialdir=carpeta_documentos(), initialfile="reporte_bi_suicidio.pdf")
        if not destino:
            return

        def tarea():
            rep = self.app.api.post("/reportes", {"titulo": self.titulo_var.get()[:120],
                                                  "metodo": METODOS[self.metodo.get()]})
            return self.app.api.get(f"/reportes/{rep['id_reporte']}/export")

        def guardar(pdf: bytes):
            Path(destino).write_bytes(pdf)
            messagebox.showinfo("Reporte", f"Reporte guardado en:\n{destino}")
        self.app.en_segundo_plano(tarea, guardar)


class PestanaUsuarios(Pestana):
    titulo = "Usuarios"

    def construir(self):
        self.tabla = ttk.Treeview(self, columns=("id", "nombre", "correo", "rol"), show="headings", height=14)
        for col, texto in [("id", "ID"), ("nombre", "Nombre"), ("correo", "Correo"), ("rol", "Rol")]:
            self.tabla.heading(col, text=texto)
        self.tabla.pack(fill="both", expand=True)
        fila = ttk.Frame(self)
        fila.pack(anchor="w", pady=8)
        ttk.Label(fila, text="Nuevo rol para el usuario seleccionado:").pack(side="left")
        self.rol = ttk.Combobox(fila, values=["administrador", "analista", "consulta"], state="readonly", width=16)
        self.rol.set("consulta")
        self.rol.pack(side="left", padx=4)
        ttk.Button(fila, text="Aplicar", command=self.cambiar).pack(side="left")

    def cargar(self):
        self.app.en_segundo_plano(lambda: self.app.api.get("/usuarios"), self.mostrar)

    def mostrar(self, usuarios):
        self.tabla.delete(*self.tabla.get_children())
        for u in usuarios:
            self.tabla.insert("", "end", values=(u["id_usuario"], u.get("nombre"), u.get("correo"), u["id_rol"]))

    def cambiar(self):
        seleccion = self.tabla.selection()
        if not seleccion:
            messagebox.showwarning("Usuarios", "Seleccione un usuario.")
            return
        id_usuario = self.tabla.item(seleccion[0])["values"][0]
        self.app.en_segundo_plano(lambda: self.app.api.patch(f"/usuarios/{id_usuario}/rol", {"id_rol": self.rol.get()}),
                                  lambda _: self.cargar())


if __name__ == "__main__":
    App().mainloop()
