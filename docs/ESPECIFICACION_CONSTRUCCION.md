# Especificación de construcción — `BASE_MAESTRA_COBRANZA`

Este documento describe **exactamente** cómo el proceso construye la base, en
el orden real del código (`src/consolidacion.py`). Úsalo para alinear tus
fuentes. Si algo no cuadra con tu operación, corrige aquí y lo ajustamos.

---

## 0. Fuentes y campos (nombre canónico ← tu columna)

Cada fuente se mapea en la app. Los campos con 🔑 son **llave de cruce**.

### CARTERA_INACTIVAS (fuente principal)
| Campo canónico | Uso |
|---|---|
| 🔑 `NO_DAMA` | Llave principal |
| `ID_COBRADOR` | Cobrador para cuentas **Inactivas** |
| `ZONA` | Llave de cruce con ZONAS_ASIGNADAS |
| `CAMPANA_SALDO` | Campaña (se normaliza, ver §1) |
| `FECHA_FACTURA`, `FECHA_INICIAL_VIGENCIA`, `FECHA_FINAL_VIGENCIA` | Fechas / vigencia |
| `SEGMENTO`, `ESTADO_PROCESO`, `SALDO_DAMA`, `PAGOS_DAMA` | Datos de cartera |

### CLIENTES (fuente principal de identificación)
`NO_DAMA` 🔑, `DIGITO_DAMA`, `NOMBRE`, `APELLIDO_PATERNO`, `APELLIDO_MATERNO`,
`CALLE`, `NUMERO_EXTERIOR`, `NUMERO_INTERIOR`, `COLONIA`, `CODIGO_POSTAL`,
`POBLACION`, `ESTADO`, `TELEFONO_CASA`, `TELEFONO_CELULAR`.

### ZONAS_ASIGNADAS
| Campo canónico | Contenido |
|---|---|
| 🔑 `ZONA` | La zona (p. ej. 970, 3242…). **Cruza con `ZONA` de la cartera.** |
| `ID_COBRADOR` | El **No. de Cobrador** (p. ej. 2887). Es un valor **distinto** de la ZONA. |
| `REGION`, `DIVISION`, `RUTA` | Se traen al cruzar |

### CARTERA_MORA (complementaria)
`NO_DAMA` 🔑, `CAMPANA_SALDO` 🔑 (para incorporar cuentas nuevas), `ZONA`,
y para **completar faltantes**: `DIGITO_DAMA`, `NOMBRE`, `SEGMENTO`,
`ESTADO_PROCESO`, `SALDO_DAMA`, `DOMICILIO`, `COLONIA`, `CODIGO_POSTAL`,
`POBLACION`, `ESTADO`, `TELEFONO_CASA`, `TELEFONO_CELULAR`,
`ID_SITUACION`, `DESC_SITUACION`, `ID_SITUACION_CIE`, `DESC_SITUACION_CIE`,
`TIPO_NOMBRAMIENTO`, `GEOLOCALIZACION`, `NUMERO_LIQUIDACION`,
`PRECIERRE_1`, `PRECIERRE_2`, `REACTIVACION`, `CANCELACION`, `PRIMERA_ORDEN`.

### LAYOUT_ARABELA
`NO_DAMA` 🔑, `FECHA_GESTION`, `STATUS_GESTION`, `MOTIVO_NO_COBRO`,
`DICTAMINACION`, `COMENTARIO`, `FECHA_PROMESA`.

### SALDOS_ACTUALIZADOS
`NO_DAMA` 🔑, `CAMPANA_SALDO` 🔑, `SALDO_ACTUALIZADO` (el "Saldo").

---

## 1. Normalización de llaves (antes de cualquier cruce)

- **`NO_DAMA`, `ZONA`, `CAMPANA_SALDO`**: se les quitan espacios y el `.0` que
  deja Excel al leer números (`1234567.0` → `1234567`). Esto es para que crucen
  entre archivos.
- **`CAMPANA_SALDO`** se normaliza al formato **`AAAA` + campaña (2 dígitos)**.
  El año se toma de las campañas que ya vienen completas en la cartera.
  Ej.: `9` → `202609`, `13` → `202613`, `202611` → `202611`.

---

## 2. Secuencia de construcción (pasos reales)

**PASO 0 — Pre-flight.** Deben existir las 6 fuentes obligatorias.

**PASO 1 — TMP_CARTERA.** De `CARTERA_INACTIVAS`, **un registro por `NO_DAMA`**,
conservando el **más reciente** (orden: `FECHA_FACTURA` desc, luego
`FECHA_FINAL_VIGENCIA` desc, luego `FECHA_CARGA` desc). Los descartados quedan en
auditoría como `NO_DAMA_DUPLICADO`.

**Incorporación de Moras.** Se agregan las cuentas de `CARTERA_MORA` cuya llave
**`NO_DAMA` + últimos 2 dígitos de campaña** (ver §4) **no exista** ya en la base.
Esas filas se marcan `CARTERA_MORAS = NUEVA`.

**PASO 2 — CLIENTES.** `JOIN por NO_DAMA`. Genera:
- `NOMBRE_COMPLETO = NOMBRE + APELLIDO_PATERNO + APELLIDO_MATERNO`
- `DIRECCION_COMPLETA = CALLE + NUMERO_EXTERIOR + NUMERO_INTERIOR`

**PASO 3 — ZONAS_ASIGNADAS.** `JOIN`: la **`ZONA` de la base (col C) = `No. de
Cobrador` (columna I)** de ZONAS_ASIGNADAS. Trae `REGION`, `DIVISION`, `RUTA`.
El `ID_COBRADOR` de Mora es el valor de esa columna I que coincidió con la ZONA.

**PASO 4 — CARTERA_MORA.** `JOIN por NO_DAMA`. Trae situación, geolocalización,
precierres, etc., y se usa para **completar faltantes** (ver §5).

**PASO 5 — LAYOUT_ARABELA.** `JOIN por NO_DAMA`.
- `NUMERO_GESTIONES` = conteo de gestiones por `NO_DAMA`.
- Última gestión (`STATUS_GESTION`, `MOTIVO_NO_COBRO`, `DICTAMINACION`,
  `COMENTARIO`, `FECHA_PROMESA`) = registro con la **fecha de llamada más
  reciente**.
- `FECHA_ULTIMA_LLAMADA` = **máxima** fecha de llamada de la consultora
  (fecha entre paréntesis del comentario; si no hay, `FECHA_GESTION`).

**PASO 6 — SALDOS_ACTUALIZADOS.** `JOIN por NO_DAMA + últimos 2 dígitos de
campaña`. Trae el "Saldo" (`SALDO_ACTUALIZADO`).

**PASO 7 — Indicadores.**
- `DIAS_MORA = hoy − FECHA_FACTURA` (se conserva, pero **no** define temporalidad).
- `TEMPORALIDAD` por campaña (ver §3).
- `ID_COBRADOR` por temporalidad (ver §6).

**PASO 8 — Pagos y saldos** (ver §7).

**Depuración por vigencia** (ver §8) y **validaciones** (ver §9).

---

## 3. TEMPORALIDAD (por campaña, no por días)

Tomando la **campaña más reciente** de la cartera como referencia:
| Distancia | Temporalidad |
|---|---|
| 0 (la más reciente) | `Inactivas` |
| 1 anterior | `Mora 1` |
| 2 anteriores | `Mora 2` |
| 3 o más anteriores | `Mora 3` |

Ej. (más reciente `202613`): `202613`→Inactivas, `202612`→Mora 1,
`202611`→Mora 2, `202610` y anteriores→Mora 3.

---

## 4. LLAVE_DAMA_CAMPAÑA

`NO_DAMA + "-" + últimos 2 dígitos de la campaña`.
Ej.: `7665522` + `202512` → `7665522-12`; `7663231` + `9` → `7663231-9`.
Se usa para comparar contra Moras e incorporar faltantes. **No** sustituye a
`NO_DAMA`.

---

## 5. Completado desde Cartera de Moras (solo si falta en CLIENTES/CARTERA)

Regla general: **CLIENTES es principal; Moras solo completa vacíos; no se
sobrescribe información válida.**
- Domicilio de Moras (un solo texto) se separa en `CALLE`, `NUMERO_EXTERIOR`,
  `NUMERO_INTERIOR`, `COLONIA`, `CODIGO_POSTAL` (formato `<calle> No <ext> Int
  <int> <colonia> CP <cp>`).
- Se completan desde Moras: `COLONIA`, `CODIGO_POSTAL`, `POBLACION`, `ESTADO`,
  `TELEFONO_CASA`, `TELEFONO_CELULAR`, `DIGITO_DAMA`, `NOMBRE_COMPLETO`
  (col. Nombre de Moras), `SEGMENTO`, `ESTADO_PROCESO`, `SALDO_DAMA`.
- `POBLACION` y `ESTADO` se **deducen del CP** (catálogo SEPOMEX) si siguen
  vacíos. Ej.: `45680` → El Salto, Jalisco.

---

## 6. ID_COBRADOR por temporalidad

| Temporalidad | Fuente del cobrador |
|---|---|
| `Inactivas` | `ID_COBRADOR` de **CARTERA_INACTIVAS** |
| `Mora 1/2/3` | Se cruza la **`ZONA` de la base contra el `No. de Cobrador` (columna I)** de ZONAS_ASIGNADAS |

Respaldo: si la fuente principal está vacía, usa la otra para no dejar
registros sin cobrador.

---

## 7. Saldos y pagos (PASO 8)

Sea `S` = "Saldo" de SALDOS_ACTUALIZADOS (por `NO_DAMA + últimos 2 díg. campaña`):
- `S = 0` → cuenta **liquidada**; `S > 0` → **pendiente**; `S < 0` → **sobrepago**.
- `SALDO_ACTUALIZADO = máx(S, 0)` → **nunca negativo**.
- `PAGOS_DAMA = SALDO_DAMA − máx(S, 0)` → el excedente del sobrepago **no** se
  considera (cuenta liquidada). Si no cruza con SALDOS, se usan los pagos de la
  cartera.
- **No existe** columna `SALDO_FINAL` (se eliminó).

---

## 8. Depuración por vigencia vencida

- Si `FECHA_FINAL_VIGENCIA < hoy` (solo fecha) → **excluir**.
- **Excepción:** cuentas `Mora 1` vencidas **sin pago** se **conservan**.
- Los excluidos quedan en auditoría (`VIGENCIA_VENCIDA`) y se cuentan.

---

## 9. Validaciones / auditoría / bitácora

- `NO_DAMA_DUPLICADO` (rechazo), `ZONA_SIN_COBRADOR`,
  `CUENTA_LIQUIDADA_SOBREPAGO`, `VIGENCIA_VENCIDA`.
- Bitácora: procesados, consolidados, nuevos (Moras), excluidos, con incidencia.
- **Cobertura de cruce por fuente**: cuántos registros cruzaron con
  CLIENTES/ZONAS/MORA/ARABELA. Si CLIENTES = 0 → la llave `NO_DAMA` no coincide.

---

## 10. Fechas

Todas las columnas de fecha se muestran como **`DD/MM/YYYY` sin hora**.

---

## Fórmulas rápidas (resumen)

| Campo | Regla |
|---|---|
| `NOMBRE_COMPLETO` | `NOMBRE + AP.PATERNO + AP.MATERNO` (o Nombre de Moras si vacío) |
| `DIRECCION_COMPLETA` | `CALLE + NUM_EXT + NUM_INT` (o domicilio de Moras) |
| `TEMPORALIDAD` | distancia de campaña a la más reciente |
| `ID_COBRADOR` | Inactivas→cartera; Mora→ZONAS por ZONA |
| `SALDO_ACTUALIZADO` | `máx(Saldo, 0)` |
| `PAGOS_DAMA` | `SALDO_DAMA − máx(Saldo, 0)` |
| `LLAVE_DAMA_CAMPAÑA` | `NO_DAMA-<2 díg campaña>` |
| `FECHA_ULTIMA_LLAMADA` | fecha de gestión más reciente |
| `CARTERA_MORAS` | `NUEVA` si se incorporó desde Moras |
