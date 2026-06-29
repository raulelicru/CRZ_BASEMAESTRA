"""Base Maestra de Cobranza - App Streamlit.

Carga las tablas fuente (CSV/Excel o datos de ejemplo), construye
BASE_MAESTRA_COBRANZA siguiendo los 8 pasos especificados, muestra
indicadores y validaciones, y permite descargar el resultado para Power BI.

Ejecutar:  streamlit run app.py
"""
from __future__ import annotations

import io
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from src.io_fuentes import (
    ESQUEMA_FUENTES, FUENTES_OBLIGATORIAS, COLUMNAS_CLAVE, leer_archivo, leer_ruta,
    campos_mapeables, aplicar_mapeo, sugerir_mapeo,
)
from src.consolidacion import construir_base_maestra, TEMPORALIDADES

SIN_MAPEO = "— (ninguna) —"

DIR_EJEMPLO = Path(__file__).parent / "sample_data"

# Marcador de version: cambia con cada despliegue para verificar que la app
# desplegada tiene el codigo mas reciente.
VERSION = "2026.06.29-f · gestión ARABELA + COMENTARIO · temporalidad por campaña"

st.set_page_config(
    page_title="Base Maestra de Cobranza",
    page_icon="📊",
    layout="wide",
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def cargar_ejemplo() -> dict[str, pd.DataFrame]:
    fuentes = {}
    for nombre in ESQUEMA_FUENTES:
        ruta = DIR_EJEMPLO / f"{nombre}.csv"
        if ruta.exists():
            fuentes[nombre] = leer_ruta(str(ruta))
    return fuentes


@st.cache_data(show_spinner=False, max_entries=8)
def leer_archivo_cache(file_id: str, nombre_archivo: str, _contenido: bytes) -> pd.DataFrame:
    """Lee y normaliza un archivo UNA sola vez (cacheado por file_id).

    Evita re-parsear Excels grandes en cada interaccion (clave en archivos de
    cientos de miles de filas y en entornos con poca RAM como Streamlit Cloud).
    `_contenido` lleva guion bajo para que Streamlit NO lo incluya en la llave
    de cache (no rehashea megabytes en cada rerun).
    """
    return leer_archivo(_contenido, nombre_archivo)


def a_excel(hojas: dict[str, pd.DataFrame]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for nombre, df in hojas.items():
            df.to_excel(writer, sheet_name=nombre[:31], index=False)
    return buffer.getvalue()


# --------------------------------------------------------------------------
# Sidebar - origen de datos
# --------------------------------------------------------------------------
st.sidebar.title("⚙️ Origen de datos")
modo = st.sidebar.radio(
    "Selecciona el origen",
    ["Datos de ejemplo", "Cargar archivos"],
    help="Usa los datos de ejemplo para una demo, o carga tus archivos CSV/Excel.",
)

fuentes_raw: dict[str, pd.DataFrame] = {}
modo_ejemplo = (modo == "Datos de ejemplo")

if modo_ejemplo:
    fuentes_raw = cargar_ejemplo()
    st.sidebar.success(f"{len(fuentes_raw)} fuentes de ejemplo cargadas.")
else:
    st.sidebar.caption("Formatos aceptados: .csv, .xlsx, .xls (un archivo por fuente)")
    for nombre in FUENTES_OBLIGATORIAS:
        archivo = st.sidebar.file_uploader(
            nombre, type=["csv", "xlsx", "xls"], key=f"up_{nombre}",
        )
        if archivo is not None:
            try:
                df = leer_archivo_cache(archivo.file_id, archivo.name, archivo.getvalue())
                fuentes_raw[nombre] = df
                st.sidebar.caption(f"• {nombre}: {len(df):,} filas")
            except Exception as exc:  # noqa: BLE001
                st.sidebar.error(f"{nombre}: error al leer ({exc})")

fecha_proceso = st.sidebar.date_input("Fecha de proceso", value=datetime.now())

# Cargar un mapeo previamente guardado (para no re-mapear tras un reinicio).
if not modo_ejemplo and fuentes_raw:
    cfg_file = st.sidebar.file_uploader(
        "📂 Cargar mapeo guardado (JSON)", type=["json"], key="cfg_map",
    )
    if cfg_file is not None and st.session_state.get("_cfg_id") != cfg_file.file_id:
        try:
            cfg = json.loads(cfg_file.getvalue().decode("utf-8"))
            for fnt, mp in cfg.items():
                cols_fnt = list(fuentes_raw.get(fnt, pd.DataFrame()).columns)
                for campo, col in mp.items():
                    if col is None or col in cols_fnt:
                        st.session_state[f"map_{fnt}_{campo}"] = col if col else SIN_MAPEO
            st.session_state["_cfg_id"] = cfg_file.file_id
            st.sidebar.success("Mapeo cargado. Revisa los paneles.")
        except Exception as exc:  # noqa: BLE001
            st.sidebar.error(f"Mapeo inválido: {exc}")

faltantes = [f for f in FUENTES_OBLIGATORIAS if f not in fuentes_raw]
construir = st.sidebar.button("🚀 Construir Base Maestra", type="primary",
                              disabled=bool(faltantes), width="stretch")
if faltantes and not modo_ejemplo:
    st.sidebar.warning("Fuentes pendientes: " + ", ".join(faltantes))


# --------------------------------------------------------------------------
# Titulo
# --------------------------------------------------------------------------
st.title("📊 Base Maestra de Cobranza")
st.caption(
    "Tabla única **BASE_MAESTRA_COBRANZA** · llave `NO_DAMA` · "
    "lista para Power BI y dashboards operativos."
)
st.caption(f"🟢 Versión desplegada: `{VERSION}`")

# --------------------------------------------------------------------------
# Mapeo de columnas (solo cuando se cargan archivos)
# --------------------------------------------------------------------------
fuentes: dict[str, pd.DataFrame] = {}

if modo_ejemplo:
    fuentes = fuentes_raw
elif fuentes_raw:
    st.subheader("🔗 Mapeo de columnas")
    st.caption(
        "La app **autodetecta** la columna de tu archivo para cada campo. "
        "Revisa y corrige solo lo que haga falta. Los campos con 🔑 son llave "
        "(obligatorios para el cruce)."
    )
    mapeo_total: dict[str, dict[str, str | None]] = {}
    for nombre in FUENTES_OBLIGATORIAS:
        if nombre not in fuentes_raw:
            continue
        df = fuentes_raw[nombre]
        cols = list(df.columns)
        opciones = [SIN_MAPEO] + cols
        claves = COLUMNAS_CLAVE.get(nombre, [])
        campos = campos_mapeables(nombre)
        sugerencias = sugerir_mapeo(cols, campos)
        faltan_clave = [c for c in claves if not sugerencias.get(c)]
        n_auto = sum(1 for v in sugerencias.values() if v)
        titulo = f"{nombre} · {len(df)} filas · {n_auto}/{len(campos)} autodetectados"
        with st.expander(titulo, expanded=bool(faltan_clave)):
            st.caption("📋 Columnas en tu archivo: " + ", ".join(f"`{c}`" for c in cols))
            mapeo: dict[str, str | None] = {}
            grid = st.columns(3)
            for i, campo in enumerate(campos):
                es_clave = campo in claves
                etiqueta = f"🔑 {campo}" if es_clave else campo
                default = sugerencias.get(campo) or SIN_MAPEO
                sel = grid[i % 3].selectbox(
                    etiqueta, opciones, index=opciones.index(default),
                    key=f"map_{nombre}_{campo}",
                )
                mapeo[campo] = None if sel == SIN_MAPEO else sel
            mapeo_total[nombre] = mapeo
            fuentes[nombre] = aplicar_mapeo(df, mapeo)
            pendientes = [c for c in claves
                          if c not in fuentes[nombre].columns
                          or fuentes[nombre][c].isna().all()]
            if pendientes:
                st.warning(f"Falta asignar la llave: {', '.join('🔑 '+p for p in pendientes)}")
            else:
                st.success("Llaves asignadas ✓")

    st.download_button(
        "💾 Guardar mapeo (JSON)",
        data=json.dumps(mapeo_total, ensure_ascii=False, indent=2),
        file_name="mapeo_columnas.json",
        mime="application/json",
        help="Descarga el mapeo actual para recargarlo después y no repetirlo.",
    )
else:
    st.info("Sube tus archivos en la barra lateral para mapear las columnas.")

# --------------------------------------------------------------------------
# Construccion
# --------------------------------------------------------------------------
if construir:
    fproc = datetime.combine(fecha_proceso, datetime.now().time())
    with st.spinner("Consolidando fuentes…"):
        st.session_state["resultado"] = construir_base_maestra(fuentes, fecha_proceso=fproc)

resultado = st.session_state.get("resultado")

if resultado is None:
    st.info("Selecciona el origen de datos y presiona **Construir Base Maestra**.")
    st.stop()

if resultado.errores:
    for e in resultado.errores:
        st.error(e)
    st.stop()

base = resultado.base
auditoria = resultado.auditoria
bit = resultado.bitacora

# --------------------------------------------------------------------------
# Bitacora / metricas
# --------------------------------------------------------------------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("Registros procesados", bit["REG_PROCESADOS"])
c2.metric("Consolidados", bit["REG_CONSOLIDADOS"])
c3.metric("Con incidencia", bit["REG_CON_ERROR"])
c4.metric("Fecha ejecución", bit["FECHA_EJECUCION"].split(" ")[0])

st.divider()

tab_base, tab_ind, tab_val, tab_desc = st.tabs(
    ["🗂️ Base Maestra", "📈 Indicadores", "✅ Validaciones", "⬇️ Descargas"]
)

# --------------------------------------------------------------------------
# TAB: Base Maestra (con filtros)
# --------------------------------------------------------------------------
with tab_base:
    f1, f2, f3 = st.columns(3)
    zonas = sorted(base["ZONA"].dropna().unique().tolist())
    cobradores = sorted(base["ID_COBRADOR"].dropna().unique().tolist())
    temporalidades = TEMPORALIDADES
    fz = f1.multiselect("Zona", zonas)
    fc = f2.multiselect("Cobrador", cobradores)
    ft = f3.multiselect("Temporalidad", temporalidades)

    vista = base.copy()
    if fz:
        vista = vista[vista["ZONA"].isin(fz)]
    if fc:
        vista = vista[vista["ID_COBRADOR"].isin(fc)]
    if ft:
        vista = vista[vista["TEMPORALIDAD"].isin(ft)]

    st.caption(f"{len(vista)} de {len(base)} registros")
    st.dataframe(vista, width="stretch", hide_index=True, height=460)

# --------------------------------------------------------------------------
# TAB: Indicadores
# --------------------------------------------------------------------------
with tab_ind:
    i1, i2, i3 = st.columns(3)
    i1.metric("Saldo actualizado total", f"${base['SALDO_ACTUALIZADO'].sum():,.2f}")
    i2.metric("Pagos totales", f"${base['PAGOS_DAMA'].sum():,.2f}")
    i3.metric("Días mora (promedio)", f"{base['DIAS_MORA'].dropna().mean():,.0f}")

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Saldo actualizado por temporalidad")
        por_temp = (base.groupby("TEMPORALIDAD", observed=True)["SALDO_ACTUALIZADO"]
                        .sum().reindex(temporalidades).dropna())
        st.bar_chart(por_temp)
    with col_b:
        st.subheader("Saldo actualizado por zona")
        por_zona = base.groupby("ZONA")["SALDO_ACTUALIZADO"].sum().sort_values(ascending=False)
        st.bar_chart(por_zona)

    st.subheader("Cartera por cobrador")
    por_cob = (base.groupby("ID_COBRADOR", dropna=False)
                   .agg(REGISTROS=("NO_DAMA", "count"),
                        SALDO_ACTUALIZADO=("SALDO_ACTUALIZADO", "sum"))
                   .reset_index().sort_values("SALDO_ACTUALIZADO", ascending=False))
    st.dataframe(por_cob, width="stretch", hide_index=True)

# --------------------------------------------------------------------------
# TAB: Validaciones / auditoria
# --------------------------------------------------------------------------
with tab_val:
    dup = base["NO_DAMA"].is_unique
    st.metric("NO_DAMA único (sin duplicados)", "✅ Sí" if dup else "❌ No")

    if auditoria.empty:
        st.success("Sin incidencias registradas.")
    else:
        resumen = (auditoria.groupby(["MOTIVO", "NIVEL"]).size()
                            .rename("TOTAL").reset_index().sort_values("TOTAL", ascending=False))
        st.subheader("Resumen de incidencias")
        st.dataframe(resumen, width="stretch", hide_index=True)

        st.subheader("Detalle de auditoría")
        motivo = st.selectbox("Filtrar por motivo",
                              ["(todos)"] + auditoria["MOTIVO"].unique().tolist())
        det = auditoria if motivo == "(todos)" else auditoria[auditoria["MOTIVO"] == motivo]
        st.dataframe(det, width="stretch", hide_index=True)

# --------------------------------------------------------------------------
# TAB: Descargas
# --------------------------------------------------------------------------
with tab_desc:
    st.subheader("Exportar resultados")
    stamp = datetime.now().strftime("%Y%m%d")

    st.download_button(
        "⬇️ BASE_MAESTRA_COBRANZA (CSV)",
        data=base.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"BASE_MAESTRA_COBRANZA_{stamp}.csv",
        mime="text/csv", width="stretch",
    )

    hojas = {
        "BASE_MAESTRA_COBRANZA": base,
        "AUDITORIA_RECHAZOS": auditoria,
        "BITACORA": pd.DataFrame([bit]),
    }
    st.download_button(
        "⬇️ Reporte completo (Excel · 3 hojas)",
        data=a_excel(hojas),
        file_name=f"BASE_MAESTRA_COBRANZA_{stamp}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )

    st.caption("El CSV usa codificación UTF-8 con BOM para abrir correctamente "
               "los acentos en Excel / Power BI.")
