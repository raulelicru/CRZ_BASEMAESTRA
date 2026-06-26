"""Carga y normalizacion de las tablas fuente.

Acepta archivos CSV o Excel. Normaliza los encabezados a MAYUSCULAS sin
acentos y mapea variantes conocidas (p.ej. CAMPAÑA_SALDO -> CAMPANA_SALDO),
de modo que la consolidacion reciba siempre nombres canonicos.
"""
from __future__ import annotations

import io
import unicodedata
import pandas as pd

# Catalogo de fuentes y sus columnas canonicas esperadas.
ESQUEMA_FUENTES: dict[str, list[str]] = {
    "CARTERA_INACTIVAS": [
        "NO_DAMA", "ZONA", "CAMPANA_SALDO", "FECHA_FACTURA",
        "FECHA_INICIAL_VIGENCIA", "FECHA_FINAL_VIGENCIA", "SEGMENTO",
        "ESTADO_PROCESO", "SALDO_DAMA", "PAGOS_DAMA", "FECHA_CARGA",
    ],
    "CLIENTES": [
        "NO_DAMA", "DIGITO_DAMA", "NOMBRE", "APELLIDO_PATERNO",
        "APELLIDO_MATERNO", "CALLE", "NUMERO_EXTERIOR", "NUMERO_INTERIOR",
        "COLONIA", "CODIGO_POSTAL", "POBLACION", "ESTADO",
        "TELEFONO_CASA", "TELEFONO_CELULAR",
    ],
    "ZONAS_ASIGNADAS": ["ZONA", "REGION", "DIVISION", "RUTA", "ID_COBRADOR"],
    "CARTERA_MORA": [
        "NO_DAMA", "ID_SITUACION", "DESC_SITUACION", "ID_SITUACION_CIE",
        "DESC_SITUACION_CIE", "TIPO_NOMBRAMIENTO", "GEOLOCALIZACION",
        "NUMERO_LIQUIDACION", "PRECIERRE_1", "PRECIERRE_2", "REACTIVACION",
        "CANCELACION", "PRIMERA_ORDEN",
    ],
    "LAYOUT_ARABELA": [
        "NO_DAMA", "FECHA_GESTION", "STATUS_GESTION", "MOTIVO_NO_COBRO",
        "DICTAMINACION", "FECHA_PROMESA",
    ],
    "SALDOS_ACTUALIZADOS": ["NO_DAMA", "CAMPANA_SALDO", "SALDO_ACTUALIZADO"],
}

# Fuentes obligatorias para poder construir la base maestra.
FUENTES_OBLIGATORIAS = list(ESQUEMA_FUENTES.keys())

# Mapeo de alias de encabezados -> nombre canonico.
ALIAS_COLUMNAS = {
    "CAMPANA_SALDO": "CAMPANA_SALDO",
    "CAMPANASALDO": "CAMPANA_SALDO",
    "CAMPANA": "CAMPANA_SALDO",
    "NODAMA": "NO_DAMA",
    "DIGITODAMA": "DIGITO_DAMA",
    "IDCOBRADOR": "ID_COBRADOR",
}


def _sin_acentos(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalizar_columna(nombre: str) -> str:
    """MAYUSCULAS, sin acentos, espacios->'_', y aplica alias conocidos."""
    base = _sin_acentos(str(nombre)).strip().upper()
    base = "_".join(base.split())
    base = base.replace("-", "_")
    return ALIAS_COLUMNAS.get(base.replace("_", ""), ALIAS_COLUMNAS.get(base, base))


def normalizar_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [normalizar_columna(c) for c in df.columns]
    # NO_DAMA siempre como texto, sin espacios (es la llave de los joins).
    for col in ("NO_DAMA", "ZONA", "CAMPANA_SALDO"):
        if col in df.columns:
            df[col] = df[col].astype("string").str.strip()
    return df


def leer_archivo(contenido: bytes, nombre_archivo: str) -> pd.DataFrame:
    """Lee CSV o Excel desde bytes y devuelve un DataFrame normalizado."""
    nombre = nombre_archivo.lower()
    if nombre.endswith((".xlsx", ".xls")):
        # dtype=str preserva ceros a la izquierda en NO_DAMA / CODIGO_POSTAL, etc.
        df = pd.read_excel(io.BytesIO(contenido), dtype=str)
    else:
        df = pd.read_csv(io.BytesIO(contenido), dtype=str, keep_default_na=True)
    return normalizar_dataframe(df)


def leer_ruta(ruta: str) -> pd.DataFrame:
    """Lee un archivo desde disco (usado para los datos de ejemplo)."""
    if ruta.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(ruta)
    else:
        df = pd.read_csv(ruta, dtype=str, keep_default_na=True)
    return normalizar_dataframe(df)
