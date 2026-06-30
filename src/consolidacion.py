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
    "CALLE", "NUMERO_EXTERIOR", "NUMERO_INTERIOR",
    "DIRECCION_COMPLETA", "COLONIA", "CODIGO_POSTAL", "POBLACION", "ESTADO",
    "TELEFONO_CASA", "TELEFONO_CELULAR",
    "CAMPANA_SALDO", "FECHA_FACTURA", "FECHA_INICIAL_VIGENCIA",
    "FECHA_FINAL_VIGENCIA", "SEGMENTO", "ESTADO_PROCESO",
    "SALDO_DAMA", "PAGOS_DAMA", "SALDO_ACTUALIZADO",
    "TEMPORALIDAD", "DIAS_MORA",
    "ID_SITUACION", "DESC_SITUACION", "ID_SITUACION_CIE", "DESC_SITUACION_CIE",
    "TIPO_NOMBRAMIENTO",
    "STATUS_GESTION", "MOTIVO_NO_COBRO", "DICTAMINACION", "COMENTARIO",
    "FECHA_ULTIMA_LLAMADA", "NUMERO_GESTIONES", "FECHA_PROMESA",
    "PRIMERA_ORDEN", "REACTIVACION", "CANCELACION",
    "PRECIERRE", "PRECIERRE_1", "PRECIERRE_2", "GEOLOCALIZACION",
    "LLAVE_DAMA_CAMPAÑA", "CARTERA_MORAS",
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


# Clasificacion de TEMPORALIDAD por campaña (ya no por dias de mora).
TEMPORALIDADES = ["Inactivas", "Mora 1", "Mora 2", "Mora 3"]


def _num_campania(serie: pd.Series) -> pd.Series:
    """Valor numerico de la campaña (p.ej. '202513' -> 202513, 'CAMPAÑA 13' -> 13)."""
    digitos = serie.astype("string").str.replace(r"\D", "", regex=True)
    return pd.to_numeric(digitos, errors="coerce")


def _temporalidad_campania(campania: pd.Series) -> pd.Series:
    """Temporalidad segun la distancia a la campaña mas reciente de la cartera.

    0 campañas (la mas reciente) -> Inactivas
    1 campaña anterior           -> Mora 1
    2 campañas anteriores        -> Mora 2
    3 o mas campañas anteriores  -> Mora 3
    """
    camp = _num_campania(campania)
    out = pd.Series(pd.NA, index=campania.index, dtype="string")
    if not camp.notna().any():
        return out
    max_camp = camp.max()
    diff = max_camp - camp
    out[diff == 0] = "Inactivas"
    out[diff == 1] = "Mora 1"
    out[diff == 2] = "Mora 2"
    out[diff >= 3] = "Mora 3"
    return out


# Campos de fecha que en la base maestra se muestran como DD/MM/YYYY (sin hora).
COLUMNAS_FECHA = [
    "FECHA_FACTURA", "FECHA_INICIAL_VIGENCIA", "FECHA_FINAL_VIGENCIA",
    "FECHA_PROMESA", "FECHA_CARGA", "FECHA_ACTUALIZACION",
]


def _ultimos2_campania(serie: pd.Series) -> pd.Series:
    """Ultimos 2 digitos de la campania (p.ej. '202526' -> '26', '9' -> '9')."""
    solo_digitos = serie.astype("string").str.replace(r"\D", "", regex=True)
    return solo_digitos.str[-2:].fillna("")


def _norm_txt(serie: pd.Series) -> pd.Series:
    """Texto limpio; cadenas vacias -> NA."""
    s = serie.astype("string")
    return s.where(s.notna() & (s.str.strip() != ""), pd.NA)


def _parse_direccion(serie: pd.Series) -> dict[str, pd.Series]:
    """Separa, en lo posible, un domicilio de texto libre en componentes.

    Heuristica (best-effort) para domicilios tipo "CALLE 123 INT 4, COLONIA,
    CP CIUDAD, ESTADO". Lo que no se reconoce queda vacio.
    """
    s = serie.astype("string").fillna("")
    partes = s.str.split(",")
    seg0 = partes.str[0].fillna("").str.strip()
    seg1 = partes.str[1].fillna("")
    seg2 = partes.str[2].fillna("")
    seg3 = partes.str[3].fillna("")

    cp = s.str.extract(r"\b(\d{5})\b")[0]
    numint = s.str.extract(
        r"(?i)(?:int\.?|interior|depto\.?|departamento)\s*[:#\-]?\s*([0-9a-z]+)")[0]
    # quitar la parte de interior del primer segmento antes de buscar el exterior
    seg0_ne = seg0.str.replace(
        r"(?i)(?:int\.?|interior|depto\.?|departamento)\s*[:#\-]?\s*[0-9a-z]+", "", regex=True)
    numext = seg0_ne.str.extract(r"(?:no\.?|num\.?|#)?\s*(\d+)\s*$")[0]
    calle = seg0_ne.str.replace(r"(?:no\.?|num\.?|#)?\s*\d+\s*$", "", regex=True,
                                ).str.replace(r"(?i)^(calle|c\.)\s*", "", regex=True).str.strip()

    quita_cp = lambda x: x.str.replace(r"\b\d{5}\b", "", regex=True).str.strip()
    colonia = quita_cp(seg1).str.replace(r"(?i)^col(onia)?\.?\s*", "", regex=True).str.strip()
    poblacion = quita_cp(seg2)
    estado = quita_cp(seg3)

    return {
        "CALLE": _norm_txt(calle), "NUMERO_EXTERIOR": _norm_txt(numext),
        "NUMERO_INTERIOR": _norm_txt(numint), "COLONIA": _norm_txt(colonia),
        "CODIGO_POSTAL": _norm_txt(cp), "POBLACION": _norm_txt(poblacion),
        "ESTADO": _norm_txt(estado),
    }


def _llave_dama_campania(no_dama: pd.Series, campania: pd.Series) -> pd.Series:
    """LLAVE_DAMA_CAMPAÑA = No.Dama + '-' + ultimos 2 digitos de la campania."""
    dama = no_dama.astype("string").str.strip()
    return dama + "-" + _ultimos2_campania(campania)


def agregar_llave_dama_campania(df: pd.DataFrame) -> pd.DataFrame:
    """Devuelve una copia del df con la columna LLAVE_DAMA_CAMPAÑA.

    Mismo nombre y formato que en la Base Maestra, para cruces directos contra
    la Cartera de Moras u otras bases.
    """
    out = df.copy()
    if "NO_DAMA" in out.columns and "CAMPANA_SALDO" in out.columns:
        out["LLAVE_DAMA_CAMPAÑA"] = _llave_dama_campania(out["NO_DAMA"], out["CAMPANA_SALDO"])
    else:
        out["LLAVE_DAMA_CAMPAÑA"] = pd.NA
    return out


def _fmt_fecha(serie: pd.Series) -> pd.Series:
    """Convierte a texto DD/MM/YYYY (sin hora); vacios quedan como NA."""
    fechas = pd.to_datetime(serie, errors="coerce")
    out = fechas.dt.strftime("%d/%m/%Y")
    return out.where(fechas.notna(), pd.NA)


def _fecha_parentesis(serie: pd.Series) -> pd.Series:
    """Fecha (datetime) contenida entre parentesis en el texto; acepta - / .

    p.ej. "5556206818 (25-6-2026) NO CONTESTAN" -> 2026-06-25.
    """
    raw = (serie.astype("string")
           .str.extract(r"\(\s*(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})\s*\)")[0])
    norm = raw.str.replace(r"[-.]", "/", regex=True)
    return pd.to_datetime(norm, dayfirst=True, errors="coerce")


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

    # ---- Incorporar cuentas de CARTERA_MORA no presentes (NO_DAMA + campaña) ----
    # Tras armar la base con Inactivas, se agregan las cuentas de Moras cuya
    # combinacion NO_DAMA + ultimos 2 digitos de campaña no exista aun. Se les
    # aplican luego los mismos cruces (PASO 2..8). Se marcan con CARTERA_MORAS=NUEVA.
    tmp["CARTERA_MORAS"] = ""
    cols_principal = ["NO_DAMA", "ZONA", "CAMPANA_SALDO", "FECHA_FACTURA",
                      "FECHA_INICIAL_VIGENCIA", "FECHA_FINAL_VIGENCIA", "SEGMENTO",
                      "ESTADO_PROCESO", "SALDO_DAMA", "PAGOS_DAMA", "FECHA_CARGA"]
    mext = src["CARTERA_MORA"].copy()
    mext = mext[
        mext["NO_DAMA"].notna()
        & (mext["NO_DAMA"].astype("string").str.strip() != "")
        & mext["CAMPANA_SALDO"].notna()
        & (mext["CAMPANA_SALDO"].astype("string").str.strip() != "")
    ].copy()
    if len(mext):
        mext["_K"] = _llave_dama_campania(mext["NO_DAMA"], mext["CAMPANA_SALDO"])
        base_keys = set(_llave_dama_campania(tmp["NO_DAMA"], tmp["CAMPANA_SALDO"]).dropna())
        extras = (mext[~mext["_K"].isin(base_keys)]
                  .drop_duplicates(subset=["_K"], keep="first"))
        if len(extras):
            ex = pd.DataFrame({
                "NO_DAMA": extras["NO_DAMA"].astype("string").str.strip().to_numpy(),
                "ZONA": extras["ZONA"].to_numpy(),
                "CAMPANA_SALDO": extras["CAMPANA_SALDO"].astype("string").str.strip().to_numpy(),
            })
            for c in cols_principal:
                if c not in ex.columns:
                    ex[c] = pd.NA
            ex["FECHA_CARGA"] = pd.Timestamp(fecha_proceso)
            ex["CARTERA_MORAS"] = "NUEVA"
            tmp = pd.concat([tmp, ex[cols_principal + ["CARTERA_MORAS"]]], ignore_index=True)
            for c in ("FECHA_FACTURA", "FECHA_INICIAL_VIGENCIA", "FECHA_FINAL_VIGENCIA", "FECHA_CARGA"):
                tmp[c] = pd.to_datetime(tmp[c], errors="coerce")
            for c in ("SALDO_DAMA", "PAGOS_DAMA"):
                tmp[c] = pd.to_numeric(tmp[c], errors="coerce")

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

    # ---- Completar datos faltantes de la consultora con la Cartera de Moras ----
    # Si un dato viene vacio de CLIENTES y existe en Moras, se usa el de Moras.
    # El domicilio unico de Moras se separa en componentes (best-effort).
    comp = _parse_direccion(df["DOMICILIO"]) if "DOMICILIO" in df.columns else {}

    def _completar(destino, *fuentes):
        base_s = _norm_txt(df[destino]) if destino in df.columns else \
            pd.Series(pd.NA, index=df.index, dtype="string")
        for f in fuentes:
            if f is None:
                continue
            base_s = base_s.fillna(_norm_txt(f))
        df[destino] = base_s

    _completar("CALLE", comp.get("CALLE"))
    _completar("NUMERO_EXTERIOR", comp.get("NUMERO_EXTERIOR"))
    _completar("NUMERO_INTERIOR", comp.get("NUMERO_INTERIOR"))
    _completar("COLONIA", df.get("COLONIA_MORA"), comp.get("COLONIA"))
    _completar("CODIGO_POSTAL", df.get("CODIGO_POSTAL_MORA"), comp.get("CODIGO_POSTAL"))
    _completar("POBLACION", df.get("POBLACION_MORA"), comp.get("POBLACION"))
    _completar("ESTADO", df.get("ESTADO_MORA"), comp.get("ESTADO"))
    _completar("TELEFONO_CASA", df.get("TELEFONO_CASA_MORA"))
    _completar("TELEFONO_CELULAR", df.get("TELEFONO_CELULAR_MORA"))

    # Recalcular DIRECCION_COMPLETA con la calle/numeros ya completados; si sigue
    # vacia y hay domicilio de Moras, usar el texto completo.
    df["DIRECCION_COMPLETA"] = _concat_ws(df, ["CALLE", "NUMERO_EXTERIOR", "NUMERO_INTERIOR"])
    if "DOMICILIO" in df.columns:
        dc = _norm_txt(df["DIRECCION_COMPLETA"])
        df["DIRECCION_COMPLETA"] = dc.fillna(_norm_txt(df["DOMICILIO"]))

    # ---- PASO 5: LAYOUT_ARABELA (ultima gestion + NUMERO_GESTIONES) ----
    ara = src["LAYOUT_ARABELA"].copy()
    ara["FECHA_GESTION"] = pd.to_datetime(ara["FECHA_GESTION"], errors="coerce")
    # Fecha de la llamada por registro: la fecha entre parentesis del comentario;
    # si no hay, se usa FECHA_GESTION. FECHA_ULTIMA_LLAMADA sera la MAS RECIENTE.
    if "COMENTARIO" in ara.columns:
        ara["_FLLAM"] = _fecha_parentesis(ara["COMENTARIO"]).fillna(ara["FECHA_GESTION"])
    else:
        ara["_FLLAM"] = ara["FECHA_GESTION"]
    conteo = ara.groupby("NO_DAMA").size().rename("NUMERO_GESTIONES").reset_index()
    fmax = (ara.groupby("NO_DAMA")["_FLLAM"].max()
               .rename("_FECHA_ULT").reset_index())
    # "Ultima gestion" (status/comentario/etc.) = registro con la llamada mas reciente.
    ult = (ara.sort_values(["NO_DAMA", "_FLLAM"], ascending=[True, False], na_position="last")
              .drop_duplicates(subset=["NO_DAMA"], keep="first"))
    cols_ult = ["NO_DAMA", "STATUS_GESTION", "MOTIVO_NO_COBRO", "DICTAMINACION",
                "COMENTARIO", "FECHA_PROMESA"]
    df = df.merge(ult[cols_ult], on="NO_DAMA", how="left", suffixes=("", "_ARA"))
    df = df.merge(conteo, on="NO_DAMA", how="left")
    df = df.merge(fmax, on="NO_DAMA", how="left")
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
    # DIAS_MORA se conserva para analisis; TEMPORALIDAD ya NO depende de el.
    df["DIAS_MORA"] = (fecha_dia - df["FECHA_FACTURA"]).dt.days
    df["DIAS_MORA"] = df["DIAS_MORA"].astype("Int64")
    df["TEMPORALIDAD"] = _temporalidad_campania(df["CAMPANA_SALDO"])

    # ---- PASO 8: pagos y saldos segun reglas de cobranza ----
    deuda = df["SALDO_DAMA"].fillna(0)
    s_raw = df["_S"]                       # saldo de SALDOSACTUALIZADOS (NaN si no cruza)
    cruza = s_raw.notna()
    pagos_cartera = df["PAGOS_DAMA"].fillna(0)
    # Saldo actualizado SIN negativos: max(Saldo, 0). Si no cruza: deuda - pagos de cartera.
    saldo_op = (s_raw.clip(lower=0)
                .where(cruza, (deuda - pagos_cartera).clip(lower=0))
                .round(2))
    # Pagos = Deuda - max(Saldo, 0): cuando hay sobrepago el excedente NO se considera
    # (cuenta liquidada -> el pago registrado es la deuda que se debia).
    df["PAGOS_DAMA"] = (deuda - saldo_op).clip(lower=0).where(cruza, pagos_cartera).round(2)
    df["SALDO_ACTUALIZADO"] = saldo_op
    df.drop(columns=["_KEY", "_S"], inplace=True)

    # PRECIERRE = PRECIERRE_2 si existe, en su defecto PRECIERRE_1 (vectorizado)
    p2 = df["PRECIERRE_2"].astype("string").str.strip()
    p1 = df["PRECIERRE_1"].astype("string").str.strip()
    p2 = p2.where(p2.notna() & (p2 != ""), pd.NA)
    p1 = p1.where(p1.notna() & (p1 != ""), pd.NA)
    df["PRECIERRE"] = p2.fillna(p1)

    df["FECHA_ACTUALIZACION"] = pd.Timestamp(fecha_proceso)

    # LLAVE_DAMA_CAMPAÑA (auxiliar para validaciones/cruces; no es la llave principal)
    df["LLAVE_DAMA_CAMPAÑA"] = _llave_dama_campania(df["NO_DAMA"], df["CAMPANA_SALDO"])

    # FECHA_ULTIMA_LLAMADA: la gestion MAS RECIENTE de cada consultora (DD/MM/YYYY).
    # Se calculo en PASO 5 como el maximo de las fechas de llamada por NO_DAMA.
    if "_FECHA_ULT" in df.columns:
        df["FECHA_ULTIMA_LLAMADA"] = _fmt_fecha(df["_FECHA_ULT"])
        df.drop(columns=["_FECHA_ULT"], inplace=True)
    else:
        df["FECHA_ULTIMA_LLAMADA"] = pd.NA

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

    reg_nuevos_moras = int((base["CARTERA_MORAS"] == "NUEVA").sum())
    bitacora = {
        "PROCESO": "BASE_MAESTRA_COBRANZA",
        "FECHA_EJECUCION": pd.Timestamp(fecha_proceso).strftime("%Y-%m-%d %H:%M:%S"),
        "ESTATUS": "EXITO",
        "REG_PROCESADOS": reg_procesados,
        "REG_CONSOLIDADOS": len(base),
        "REG_NUEVOS_MORAS": reg_nuevos_moras,
        "REG_CON_ERROR": len(auditoria),
    }

    return ResultadoConsolidacion(base=base, auditoria=auditoria,
                                  bitacora=bitacora, errores=errores)
