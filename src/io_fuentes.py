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
# Alias de encabezados -> nombre canonico. La clave se compara en su forma
# "compacta" (MAYUSCULAS, sin acentos, sin espacios/guiones/puntos), de modo que
# "No. Dama", "NUM DAMA", "No_Dama" y "NODAMA" mapean todas a NO_DAMA.
ALIAS_COLUMNAS = {
    # NO_DAMA
    "NODAMA": "NO_DAMA", "NUMDAMA": "NO_DAMA", "NUMERODAMA": "NO_DAMA",
    "NODEDAMA": "NO_DAMA", "NUMERODEDAMA": "NO_DAMA", "NRODAMA": "NO_DAMA",
    "DAMA": "NO_DAMA", "CUENTADAMA": "NO_DAMA",
    # DIGITO_DAMA
    "DIGITODAMA": "DIGITO_DAMA", "DIGITO": "DIGITO_DAMA",
    "DIGITOVERIFICADOR": "DIGITO_DAMA", "DV": "DIGITO_DAMA",
    # CAMPANA_SALDO
    "CAMPANASALDO": "CAMPANA_SALDO", "CAMPANA": "CAMPANA_SALDO",
    "CAMPANIA": "CAMPANA_SALDO", "CAMPANIASALDO": "CAMPANA_SALDO",
    # ZONA / asignacion
    "ZONA": "ZONA", "IDZONA": "ZONA",
    "IDCOBRADOR": "ID_COBRADOR", "COBRADOR": "ID_COBRADOR",
    "IDGESTOR": "ID_COBRADOR", "GESTOR": "ID_COBRADOR",
    "RUTA": "RUTA", "REGION": "REGION", "DIVISION": "DIVISION",
    # saldos
    "SALDODAMA": "SALDO_DAMA", "PAGOSDAMA": "PAGOS_DAMA",
    "SALDOACTUALIZADO": "SALDO_ACTUALIZADO",
    # fechas
    "FECHAFACTURA": "FECHA_FACTURA", "FECHAGESTION": "FECHA_GESTION",
    "FECHAPROMESA": "FECHA_PROMESA",
}


def _sin_acentos(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _compacta(nombre: str) -> str:
    """Forma comparable: MAYUSCULAS, sin acentos ni caracteres no alfanumericos."""
    base = _sin_acentos(str(nombre)).upper()
    return "".join(c for c in base if c.isalnum())


def normalizar_columna(nombre: str) -> str:
    """MAYUSCULAS, sin acentos, espacios->'_', y aplica alias conocidos."""
    compacta = _compacta(nombre)
    if compacta in ALIAS_COLUMNAS:
        return ALIAS_COLUMNAS[compacta]
    base = _sin_acentos(str(nombre)).strip().upper()
    base = "_".join(base.split())
    return base.replace("-", "_").replace(".", "")


def normalizar_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [normalizar_columna(c) for c in df.columns]
    # NO_DAMA siempre como texto, sin espacios (es la llave de los joins).
    for col in ("NO_DAMA", "ZONA", "CAMPANA_SALDO"):
        if col in df.columns:
            df[col] = df[col].astype("string").str.strip()
    return df


def _leer_excel(origen) -> pd.DataFrame:
    """Lee un Excel y devuelve la hoja con mas filas con datos.

    Esto evita resultados vacios cuando la primera hoja es una portada o esta
    en blanco y los datos viven en otra hoja. dtype=str preserva ceros a la
    izquierda (NO_DAMA, CODIGO_POSTAL, etc.).
    """
    hojas = pd.read_excel(origen, dtype=str, sheet_name=None)
    if not hojas:
        return pd.DataFrame()
    # Elegir la hoja con mas filas no vacias.
    mejor = max(hojas.values(), key=lambda d: d.dropna(how="all").shape[0])
    return mejor.dropna(how="all")


def leer_archivo(contenido: bytes, nombre_archivo: str) -> pd.DataFrame:
    """Lee CSV o Excel desde bytes y devuelve un DataFrame normalizado."""
    nombre = nombre_archivo.lower()
    if nombre.endswith((".xlsx", ".xls")):
        df = _leer_excel(io.BytesIO(contenido))
    else:
        df = pd.read_csv(io.BytesIO(contenido), dtype=str, keep_default_na=True)
    return normalizar_dataframe(df)


def leer_ruta(ruta: str) -> pd.DataFrame:
    """Lee un archivo desde disco (usado para los datos de ejemplo)."""
    if ruta.lower().endswith((".xlsx", ".xls")):
        df = _leer_excel(ruta)
    else:
        df = pd.read_csv(ruta, dtype=str, keep_default_na=True)
    return normalizar_dataframe(df)


# Columnas clave por fuente para diagnostico (si faltan, el cruce sale vacio).
COLUMNAS_CLAVE = {
    "CARTERA_INACTIVAS": ["NO_DAMA"],
    "CLIENTES": ["NO_DAMA"],
    "ZONAS_ASIGNADAS": ["ZONA"],
    "CARTERA_MORA": ["NO_DAMA"],
    "LAYOUT_ARABELA": ["NO_DAMA"],
    "SALDOS_ACTUALIZADOS": ["NO_DAMA", "CAMPANA_SALDO"],
}


def diagnosticar_fuente(df: pd.DataFrame, fuente: str) -> dict:
    """Resumen para mostrar en la app: filas, columnas y claves faltantes."""
    claves = COLUMNAS_CLAVE.get(fuente, [])
    faltan = [c for c in claves if c not in df.columns]
    return {
        "filas": int(len(df)),
        "columnas": list(df.columns),
        "claves_faltantes": faltan,
    }
