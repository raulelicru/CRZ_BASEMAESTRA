"""Carga y normalizacion de las tablas fuente.

Acepta archivos CSV o Excel. Normaliza los encabezados a MAYUSCULAS sin
acentos y mapea variantes conocidas (p.ej. CAMPAÑA_SALDO -> CAMPANA_SALDO),
de modo que la consolidacion reciba siempre nombres canonicos.
"""
from __future__ import annotations

import difflib
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

    Usa el motor 'calamine' (Rust) cuando esta disponible: es mucho mas rapido y
    ligero en memoria que openpyxl, clave para archivos de cientos de miles de
    filas en entornos con poca RAM. Cae a openpyxl si no esta instalado.

    Esto evita resultados vacios cuando la primera hoja es una portada o esta
    en blanco y los datos viven en otra hoja. dtype=str preserva ceros a la
    izquierda (NO_DAMA, CODIGO_POSTAL, etc.).
    """
    try:
        hojas = pd.read_excel(origen, dtype=str, sheet_name=None, engine="calamine")
    except Exception:  # noqa: BLE001  (motor no disponible / origen no re-seekeable)
        if hasattr(origen, "seek"):
            origen.seek(0)
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


def campos_mapeables(fuente: str) -> list[str]:
    """Campos canonicos que el usuario puede mapear para una fuente."""
    return [c for c in ESQUEMA_FUENTES[fuente] if c != "FECHA_CARGA"]


# Palabras clave (en forma compacta) que sugieren un campo canonico.
SINONIMOS = {
    "NO_DAMA": ["NODAMA", "CODIGO", "CODIGODAMA", "CUENTA", "CONTRATO", "FOLIO", "NOCLIENTE"],
    "DIGITO_DAMA": ["DIGITODAMA", "DIGITO", "DIGITOVERIFICADOR", "DV"],
    "NOMBRE": ["NOMBRE", "NOMBRES"],
    "APELLIDO_PATERNO": ["APELLIDOPATERNO", "PATERNO", "APPATERNO"],
    "APELLIDO_MATERNO": ["APELLIDOMATERNO", "MATERNO", "APMATERNO"],
    "CALLE": ["CALLE", "DOMICILIO", "DIRECCION"],
    "NUMERO_EXTERIOR": ["NUMEROEXTERIOR", "NUMEXT", "NOEXT", "EXTERIOR"],
    "NUMERO_INTERIOR": ["NUMEROINTERIOR", "NUMINT", "NOINT", "INTERIOR"],
    "COLONIA": ["COLONIA", "COL"],
    "CODIGO_POSTAL": ["CODIGOPOSTAL", "CP", "CODPOSTAL"],
    "POBLACION": ["POBLACION", "MUNICIPIO", "CIUDAD", "LOCALIDAD"],
    "ESTADO": ["ESTADO", "ENTIDAD"],
    "TELEFONO_CASA": ["TELEFONOCASA", "TELCASA", "TELEFONOFIJO", "TELFIJO"],
    "TELEFONO_CELULAR": ["TELEFONOCELULAR", "TELCEL", "CELULAR", "MOVIL", "TELEFONO"],
    "CAMPANA_SALDO": ["CAMPANASALDO", "ANIOCAMPANIASALDO", "ANIOCAMPANASALDO", "CAMPANA", "CAMPANIA"],
    "ZONA": ["ZONA", "PLAZA", "TERRITORIO"],
    "RUTA": ["RUTA"],
    "REGION": ["REGION"],
    "DIVISION": ["DIVISION"],
    "ID_COBRADOR": ["IDCOBRADOR", "COBRADOR", "GESTOR", "EJECUTIVO", "PROMOTOR"],
    "SEGMENTO": ["SEGMENTO", "SEGMENT"],
    "ESTADO_PROCESO": ["ESTADOPROCESO", "ESTATUSPROCESO", "PROCESO"],
    "SALDO_DAMA": ["SALDODAMA", "SALDO", "ADEUDO", "DEUDA", "IMPORTE"],
    "PAGOS_DAMA": ["PAGOSDAMA", "PAGOS", "PAGO", "ABONO", "ABONOS"],
    "SALDO_ACTUALIZADO": ["SALDOACTUALIZADO", "SALDOCAMPANIA", "SALDOCAMPANA", "SALDOACT", "SALDONUEVO"],
    "FECHA_FACTURA": ["FECHAFACTURA", "FACTURA", "FECHAFACT", "FFACTURA"],
    "FECHA_INICIAL_VIGENCIA": ["FECHAINICIALVIGENCIA", "INICIOVIGENCIA", "FECHAINICIO", "INICIVIGEN"],
    "FECHA_FINAL_VIGENCIA": ["FECHAFINALVIGENCIA", "FINVIGENCIA", "FECHAFIN", "FINVIGEN"],
    "FECHA_GESTION": ["FECHAGESTION", "FECHA", "FECHAGEST"],
    "STATUS_GESTION": ["STATUSGESTION", "ESTATUS", "ESTATUSGESTION", "STATUS"],
    "MOTIVO_NO_COBRO": ["MOTIVONOCOBRO", "MOTIVO", "COMENTARIO", "OBSERVACION"],
    "DICTAMINACION": ["DICTAMINACION", "DICTAMEN", "TIPIFICACION", "TIPIFICACILON", "TIPODEGESTION"],
    "FECHA_PROMESA": ["FECHAPROMESA", "PROMESA", "FPROMESA"],
    "ID_SITUACION": ["IDSITUACION", "SITUACION"],
    "DESC_SITUACION": ["DESCSITUACION", "DESCRIPCIONSITUACION"],
    "ID_SITUACION_CIE": ["IDSITUACIONCIE", "SITUACIONCIE"],
    "DESC_SITUACION_CIE": ["DESCSITUACIONCIE"],
    "TIPO_NOMBRAMIENTO": ["TIPONOMBRAMIENTO", "NOMBRAMIENTO"],
    "GEOLOCALIZACION": ["GEOLOCALIZACION", "GEO", "COORDENADAS", "LATLON"],
    "PRIMERA_ORDEN": ["PRIMERAORDEN", "PRIMERORDEN"],
    "REACTIVACION": ["REACTIVACION"],
    "CANCELACION": ["CANCELACION"],
    "PRECIERRE_1": ["PRECIERRE1", "PRECIERREUNO"],
    "PRECIERRE_2": ["PRECIERRE2", "PRECIERREDOS"],
}

_STOPWORDS = {"DE", "DEL", "LA", "EL", "Y", "DAMA"}


def _tokens(nombre: str) -> set[str]:
    base = _sin_acentos(str(nombre)).upper()
    crudo = "".join(c if c.isalnum() else " " for c in base).split()
    return {t for t in crudo if t and t not in _STOPWORDS}


def _score(campo: str, columna: str) -> float:
    """Similitud 0..1 entre un campo canonico y una columna del archivo."""
    a, b = _compacta(campo), _compacta(columna)
    if a == b:
        return 1.0
    mejor = 0.0
    for kw in SINONIMOS.get(campo, []):
        if kw == b:
            mejor = max(mejor, 0.97)
        elif len(kw) >= 4 and (kw in b or b in kw):
            mejor = max(mejor, 0.9)
    ta, tb = _tokens(campo), _tokens(columna)
    if ta and tb and (ta & tb):
        mejor = max(mejor, 0.6 + 0.35 * len(ta & tb) / max(len(ta), len(tb)))
    mejor = max(mejor, 0.9 * difflib.SequenceMatcher(None, a, b).ratio())
    return mejor


def sugerir_mapeo(columnas: list[str], campos: list[str],
                  umbral: float = 0.72) -> dict[str, str | None]:
    """Asignacion automatica campo->columna por mejor similitud (unica)."""
    pares = []
    for campo in campos:
        for col in columnas:
            s = _score(campo, col)
            if s >= umbral:
                pares.append((s, campo, col))
    pares.sort(reverse=True)
    usados_col: set[str] = set()
    asignado: dict[str, str | None] = {c: None for c in campos}
    for s, campo, col in pares:
        if asignado[campo] is None and col not in usados_col:
            asignado[campo] = col
            usados_col.add(col)
    return asignado


def aplicar_mapeo(df: pd.DataFrame, mapeo: dict[str, str | None]) -> pd.DataFrame:
    """Renombra columnas del archivo a nombres canonicos segun `mapeo`.

    `mapeo` = {campo_canonico: columna_del_archivo | None}. La columna elegida
    por el usuario gana sobre cualquier columna canonica preexistente.
    """
    df = df.copy()
    for canonico, columna in mapeo.items():
        if not columna or columna not in df.columns or columna == canonico:
            continue
        if canonico in df.columns:
            df = df.drop(columns=[canonico])
        df = df.rename(columns={columna: canonico})
    # Normaliza tipos de las llaves recien mapeadas.
    for col in ("NO_DAMA", "ZONA", "CAMPANA_SALDO"):
        if col in df.columns:
            df[col] = df[col].astype("string").str.strip()
    return df
