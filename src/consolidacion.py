"""Construccion de BASE_MAESTRA_COBRANZA (8 pasos) en pandas.

Replica fielmente la logica del procedimiento SQL
dbo.sp_construir_base_maestra:

  PASO 1  TMP_CARTERA: unico por NO_DAMA (registro mas reciente)
  PASO 2  + CLIENTES  -> NOMBRE_COMPLETO, DIRECCION_COMPLETA
  PASO 3  + ZONAS_ASIGNADAS (por ZONA)
  PASO 4  + CARTERA_MORA (por NO_DAMA)
  PASO 5  + LAYOUT_ARABELA (ultima gestion + NUMERO_GESTIONES)
  PASO 6  + SALDOS_ACTUALIZADOS (NO_DAMA + CAMPANA_SALDO)
  PASO 7  TEMPORALIDAD, DIAS_MORA
  PASO 8  SALDO_FINAL = SALDO_DAMA - PAGOS_DAMA

Validaciones: NO_DAMA duplicado, zona sin cobrador, saldo negativo.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import pandas as pd

from .io_fuentes import ESQUEMA_FUENTES, FUENTES_OBLIGATORIAS

# Orden final de columnas (ESTRUCTURA FINAL de la especificacion).
COLUMNAS_FINALES = [
    "REGION", "DIVISION", "ZONA", "RUTA", "ID_COBRADOR",
    "NO_DAMA", "DIGITO_DAMA", "NOMBRE_COMPLETO",
    "DIRECCION_COMPLETA", "COLONIA", "CODIGO_POSTAL", "POBLACION", "ESTADO",
    "TELEFONO_CASA", "TELEFONO_CELULAR",
    "CAMPANA_SALDO", "FECHA_FACTURA", "FECHA_INICIAL_VIGENCIA",
    "FECHA_FINAL_VIGENCIA", "SEGMENTO", "ESTADO_PROCESO",
    "SALDO_DAMA", "PAGOS_DAMA", "SALDO_ACTUALIZADO", "SALDO_FINAL",
    "TEMPORALIDAD", "DIAS_MORA",
    "ID_SITUACION", "DESC_SITUACION", "ID_SITUACION_CIE", "DESC_SITUACION_CIE",
    "TIPO_NOMBRAMIENTO",
    "STATUS_GESTION", "MOTIVO_NO_COBRO", "DICTAMINACION",
    "NUMERO_GESTIONES", "FECHA_PROMESA",
    "PRIMERA_ORDEN", "REACTIVACION", "CANCELACION",
    "PRECIERRE", "PRECIERRE_1", "PRECIERRE_2", "GEOLOCALIZACION",
    "FECHA_CARGA", "FECHA_ACTUALIZACION",
]


@dataclass
class ResultadoConsolidacion:
    base: pd.DataFrame
    auditoria: pd.DataFrame
    bitacora: dict = field(default_factory=dict)
    errores: list[str] = field(default_factory=list)


def _asegurar_columnas(df: pd.DataFrame, fuente: str) -> pd.DataFrame:
    """Garantiza que existan todas las columnas canonicas de la fuente."""
    df = df.copy()
    for col in ESQUEMA_FUENTES[fuente]:
        if col not in df.columns:
            df[col] = pd.NA
    return df


def _concat_ws(df: pd.DataFrame, columnas: list[str]) -> pd.Series:
    """Concatena columnas con espacio, ignorando vacios/nulos (como CONCAT_WS).

    Vectorizado: escala a cientos de miles de filas sin apply fila por fila.
    """
    partes = []
    for col in columnas:
        s = df[col].astype("string").str.strip()
        partes.append(s.where(s.notna() & (s != ""), ""))
    unido = partes[0]
    for s in partes[1:]:
        unido = unido.str.cat(s, sep=" ")
    return unido.str.replace(r"\s+", " ", regex=True).str.strip()


def _temporalidad(dias: pd.Series) -> pd.Series:
    bins = [-float("inf"), 30, 60, 90, 120, 150, 180, float("inf")]
    labels = ["0-30", "31-60", "61-90", "91-120", "121-150", "151-180", "181+"]
    cat = pd.cut(dias, bins=bins, labels=labels)
    return cat.astype("string").where(dias.notna())


# Campos de fecha que en la base maestra se muestran como DD/MM/YYYY (sin hora).
COLUMNAS_FECHA = [
    "FECHA_FACTURA", "FECHA_INICIAL_VIGENCIA", "FECHA_FINAL_VIGENCIA",
    "FECHA_PROMESA", "FECHA_CARGA", "FECHA_ACTUALIZACION",
]


def _ultimos2_campania(serie: pd.Series) -> pd.Series:
    """Ultimos 2 digitos de la campania (p.ej. '202526' -> '26')."""
    solo_digitos = serie.astype("string").str.replace(r"\D", "", regex=True)
    return solo_digitos.str[-2:].fillna("")


def _fmt_fecha(serie: pd.Series) -> pd.Series:
    """Convierte a texto DD/MM/YYYY (sin hora); vacios quedan como NA."""
    fechas = pd.to_datetime(serie, errors="coerce")
    out = fechas.dt.strftime("%d/%m/%Y")
    return out.where(fechas.notna(), pd.NA)


def construir_base_maestra(
    fuentes: dict[str, pd.DataFrame],
    fecha_proceso: datetime | None = None,
) -> ResultadoConsolidacion:
    fecha_proceso = fecha_proceso or datetime.now()
    fecha_dia = pd.Timestamp(fecha_proceso).normalize()
    errores: list[str] = []

    # ---- PASO 0: pre-flight de fuentes obligatorias ----
    faltantes = [f for f in FUENTES_OBLIGATORIAS if f not in fuentes or fuentes[f] is None]
    if faltantes:
        errores.append("Tablas fuente faltantes: " + ", ".join(faltantes))
        return ResultadoConsolidacion(
            base=pd.DataFrame(columns=COLUMNAS_FINALES),
            auditoria=pd.DataFrame(),
            bitacora={"ESTATUS": "ERROR"},
            errores=errores,
        )

    src = {f: _asegurar_columnas(fuentes[f], f) for f in FUENTES_OBLIGATORIAS}

    cartera = src["CARTERA_INACTIVAS"].copy()
    cartera = cartera[cartera["NO_DAMA"].notna() & (cartera["NO_DAMA"].astype(str).str.strip() != "")]
    reg_procesados = len(cartera)

    if reg_procesados == 0:
        cols = list(fuentes["CARTERA_INACTIVAS"].columns)
        errores.append(
            "CARTERA_INACTIVAS no tiene filas con NO_DAMA. Verifica que el "
            "archivo tenga una columna 'NO_DAMA' con datos. "
            f"Columnas detectadas: {', '.join(map(str, cols)) or '(ninguna)'}."
        )
        return ResultadoConsolidacion(
            base=pd.DataFrame(columns=COLUMNAS_FINALES),
            auditoria=pd.DataFrame(),
            bitacora={"ESTATUS": "ERROR", "REG_PROCESADOS": 0,
                      "REG_CONSOLIDADOS": 0, "REG_CON_ERROR": 0},
            errores=errores,
        )

    # Tipos
    for col in ("FECHA_FACTURA", "FECHA_INICIAL_VIGENCIA", "FECHA_FINAL_VIGENCIA", "FECHA_CARGA"):
        cartera[col] = pd.to_datetime(cartera[col], errors="coerce")
    for col in ("SALDO_DAMA", "PAGOS_DAMA"):
        cartera[col] = pd.to_numeric(cartera[col], errors="coerce")

    # ---- PASO 1: TMP_CARTERA unico por NO_DAMA (registro mas reciente) ----
    orden = ["FECHA_FACTURA", "FECHA_FINAL_VIGENCIA", "FECHA_CARGA"]
    cartera_ord = cartera.sort_values(
        by=["NO_DAMA"] + orden, ascending=[True, False, False, False],
        na_position="last", kind="stable",
    )
    tmp = cartera_ord.drop_duplicates(subset=["NO_DAMA"], keep="first").copy()

    # Auditoria: duplicados descartados (vectorizado)
    aud_dfs: list[pd.DataFrame] = []
    dup = cartera_ord[cartera_ord.duplicated(subset=["NO_DAMA"], keep="first")]
    if len(dup):
        aud_dfs.append(pd.DataFrame({
            "PASO": "PASO1_TMP_CARTERA", "MOTIVO": "NO_DAMA_DUPLICADO", "NIVEL": "RECHAZO",
            "NO_DAMA": dup["NO_DAMA"].to_numpy(),
            "CAMPANA_SALDO": dup["CAMPANA_SALDO"].to_numpy(),
            "ZONA": dup["ZONA"].to_numpy(),
            "DETALLE": "Registro duplicado descartado; se conservo el mas reciente.",
        }))

    # ---- PASO 2: CLIENTES ----
    cli = src["CLIENTES"].drop_duplicates(subset=["NO_DAMA"], keep="first")
    df = tmp.merge(cli, on="NO_DAMA", how="left", suffixes=("", "_CLI"))
    df["NOMBRE_COMPLETO"] = _concat_ws(df, ["NOMBRE", "APELLIDO_PATERNO", "APELLIDO_MATERNO"])
    df["DIRECCION_COMPLETA"] = _concat_ws(df, ["CALLE", "NUMERO_EXTERIOR", "NUMERO_INTERIOR"])

    # ---- PASO 3: ZONAS_ASIGNADAS (por ZONA) ----
    zon = src["ZONAS_ASIGNADAS"].drop_duplicates(subset=["ZONA"], keep="first")
    df = df.merge(zon, on="ZONA", how="left", suffixes=("", "_ZON"))

    # ---- PASO 4: CARTERA_MORA (por NO_DAMA) ----
    mora = src["CARTERA_MORA"].drop_duplicates(subset=["NO_DAMA"], keep="first")
    df = df.merge(mora, on="NO_DAMA", how="left", suffixes=("", "_MORA"))

    # ---- PASO 5: LAYOUT_ARABELA (ultima gestion + NUMERO_GESTIONES) ----
    ara = src["LAYOUT_ARABELA"].copy()
    ara["FECHA_GESTION"] = pd.to_datetime(ara["FECHA_GESTION"], errors="coerce")
    conteo = ara.groupby("NO_DAMA").size().rename("NUMERO_GESTIONES").reset_index()
    ult = (ara.sort_values(["NO_DAMA", "FECHA_GESTION"], ascending=[True, False], na_position="last")
              .drop_duplicates(subset=["NO_DAMA"], keep="first"))
    cols_ult = ["NO_DAMA", "STATUS_GESTION", "MOTIVO_NO_COBRO", "DICTAMINACION", "FECHA_PROMESA"]
    df = df.merge(ult[cols_ult], on="NO_DAMA", how="left", suffixes=("", "_ARA"))
    df = df.merge(conteo, on="NO_DAMA", how="left")
    df["NUMERO_GESTIONES"] = df["NUMERO_GESTIONES"].fillna(0).astype(int)
    df["FECHA_PROMESA"] = pd.to_datetime(df["FECHA_PROMESA"], errors="coerce")

    # ---- PASO 6: SALDOS_ACTUALIZADOS (llave NO_DAMA + ultimos 2 digitos de campania) ----
    # El "Saldo" de SALDOSACTUALIZADOS es el saldo posterior a pagos:
    #   0  -> liquidada,  >0 -> pendiente,  <0 -> pago mayor al adeudo.
    sal = src["SALDOS_ACTUALIZADOS"].copy()
    sal["SALDO_ACTUALIZADO"] = pd.to_numeric(sal["SALDO_ACTUALIZADO"], errors="coerce")
    sal["_KEY"] = (sal["NO_DAMA"].astype("string").str.strip()
                   + _ultimos2_campania(sal["CAMPANA_SALDO"]))
    sal = sal.drop_duplicates(subset=["_KEY"], keep="first")
    df["_KEY"] = (df["NO_DAMA"].astype("string").str.strip()
                  + _ultimos2_campania(df["CAMPANA_SALDO"]))
    df = df.merge(sal[["_KEY", "SALDO_ACTUALIZADO"]].rename(columns={"SALDO_ACTUALIZADO": "_S"}),
                  on="_KEY", how="left")

    # ---- PASO 7: indicadores ----
    df["DIAS_MORA"] = (fecha_dia - df["FECHA_FACTURA"]).dt.days
    df["DIAS_MORA"] = df["DIAS_MORA"].astype("Int64")
    df["TEMPORALIDAD"] = _temporalidad(df["DIAS_MORA"])

    # ---- PASO 8: pagos y saldos segun reglas de cobranza ----
    deuda = df["SALDO_DAMA"].fillna(0)
    s_raw = df["_S"]                       # saldo de SALDOSACTUALIZADOS (NaN si no cruza)
    cruza = s_raw.notna()
    # Pagos aplicados = Deuda Original - Saldo. Si no cruza, se usan los pagos de cartera.
    pagos_saldos = (deuda - s_raw).clip(lower=0)
    pagos_cartera = df["PAGOS_DAMA"].fillna(0)
    df["PAGOS_DAMA"] = pagos_saldos.where(cruza, pagos_cartera).round(2)
    # Saldo actualizado = Deuda - Pagos, SIN negativos (los <0 se muestran como 0).
    saldo_op = s_raw.where(cruza, deuda - pagos_cartera).clip(lower=0).round(2)
    df["SALDO_ACTUALIZADO"] = saldo_op
    df["SALDO_FINAL"] = saldo_op
    df.drop(columns=["_KEY", "_S"], inplace=True)

    # PRECIERRE = PRECIERRE_2 si existe, en su defecto PRECIERRE_1 (vectorizado)
    p2 = df["PRECIERRE_2"].astype("string").str.strip()
    p1 = df["PRECIERRE_1"].astype("string").str.strip()
    p2 = p2.where(p2.notna() & (p2 != ""), pd.NA)
    p1 = p1.where(p1.notna() & (p1 != ""), pd.NA)
    df["PRECIERRE"] = p2.fillna(p1)

    df["FECHA_ACTUALIZACION"] = pd.Timestamp(fecha_proceso)

    # ---- Validaciones de negocio (vectorizadas) ----
    mask_sc = df["ID_COBRADOR"].isna() | (df["ID_COBRADOR"].astype("string").str.strip() == "")
    if mask_sc.any():
        d = df.loc[mask_sc]
        aud_dfs.append(pd.DataFrame({
            "PASO": "VALIDACIONES", "MOTIVO": "ZONA_SIN_COBRADOR", "NIVEL": "ADVERTENCIA",
            "NO_DAMA": d["NO_DAMA"].to_numpy(), "CAMPANA_SALDO": d["CAMPANA_SALDO"].to_numpy(),
            "ZONA": d["ZONA"].to_numpy(),
            "DETALLE": "La zona no tiene cobrador asignado en ZONAS_ASIGNADAS.",
        }))

    # Sobrepago: el saldo original venia negativo (pago mayor al adeudo) -> liquidada.
    mask_sp = cruza & (s_raw < 0)
    if mask_sp.any():
        d = df.loc[mask_sp]
        aud_dfs.append(pd.DataFrame({
            "PASO": "VALIDACIONES", "MOTIVO": "CUENTA_LIQUIDADA_SOBREPAGO", "NIVEL": "ADVERTENCIA",
            "NO_DAMA": d["NO_DAMA"].to_numpy(), "CAMPANA_SALDO": d["CAMPANA_SALDO"].to_numpy(),
            "ZONA": d["ZONA"].to_numpy(),
            "DETALLE": "Pago mayor al adeudo; deuda liquidada, saldo mostrado como 0.",
        }))

    # ---- Formato de fechas DD/MM/YYYY (sin hora) ----
    for col in COLUMNAS_FECHA:
        if col in df.columns:
            df[col] = _fmt_fecha(df[col])

    # ---- Estructura final ----
    for col in COLUMNAS_FINALES:
        if col not in df.columns:
            df[col] = pd.NA
    base = df[COLUMNAS_FINALES].reset_index(drop=True)

    cols_aud = ["PASO", "MOTIVO", "NIVEL", "NO_DAMA", "CAMPANA_SALDO", "ZONA", "DETALLE"]
    auditoria = (pd.concat(aud_dfs, ignore_index=True)[cols_aud]
                 if aud_dfs else pd.DataFrame(columns=cols_aud))

    bitacora = {
        "PROCESO": "BASE_MAESTRA_COBRANZA",
        "FECHA_EJECUCION": pd.Timestamp(fecha_proceso).strftime("%Y-%m-%d %H:%M:%S"),
        "ESTATUS": "EXITO",
        "REG_PROCESADOS": reg_procesados,
        "REG_CONSOLIDADOS": len(base),
        "REG_CON_ERROR": len(auditoria),
    }

    return ResultadoConsolidacion(base=base, auditoria=auditoria,
                                  bitacora=bitacora, errores=errores)
