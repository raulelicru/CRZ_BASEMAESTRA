# Base Maestra de Cobranza — `BASE_MAESTRA_COBRANZA`

Solución de consolidación diaria que integra múltiples fuentes de cobranza en
una **tabla única** lista para explotación en Power BI, dashboards operativos,
seguimiento de recuperación y asignación de cobranza.

- **Llave principal:** `NO_DAMA` (único en la tabla final).
- **Llaves secundarias:** `NO_DAMA + CAMPANA_SALDO`, `ZONA`, `RUTA`, `ID_COBRADOR`.

La misma lógica de consolidación (8 pasos + validaciones) está disponible en **dos
implementaciones equivalentes y validadas**, que producen resultados idénticos:

| Implementación | Uso | Estado |
|---|---|---|
| **App Streamlit** (`streamlit_app.py`) | Carga de archivos, vista interactiva, descarga para Power BI | Validada (AppTest) |
| **SQL Server** (`sql/`) | Despliegue en BD, ejecución diaria por SQL Agent | Validada (SQL Server 2022) |

---

## 🖥️ App Streamlit

Interfaz para cargar las fuentes (CSV/Excel o datos de ejemplo), construir la
base maestra y descargar el resultado.

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Funcionalidad:
- **Origen de datos:** datos de ejemplo incluidos o carga de tus archivos.
- **Construcción** de `BASE_MAESTRA_COBRANZA` (8 pasos) con un clic.
- **Métricas** de bitácora: procesados / consolidados / con incidencia.
- **Pestañas:** Base Maestra (con filtros por zona, cobrador, temporalidad),
  Indicadores (saldo por temporalidad/zona/cobrador), Validaciones (auditoría) y
  Descargas (CSV UTF-8-BOM y Excel de 3 hojas).

Estructura del código de la app:

```
streamlit_app.py                  Interfaz Streamlit
src/io_fuentes.py       Carga y normalización de fuentes (alias CAMPAÑA→CAMPANA)
src/consolidacion.py    Pipeline de 8 pasos + validaciones (pandas)
sample_data/*.csv       Datos de ejemplo
```

---

## 🗄️ Implementación SQL Server (T-SQL)

- **Motor:** SQL Server (T-SQL). Validado en SQL Server 2022.
- **Frecuencia:** ejecución diaria vía SQL Server Agent.

> **Nota de nomenclatura:** el campo de negocio *CAMPAÑA_SALDO* se normaliza a
> ASCII como **`CAMPANA_SALDO`** para máxima compatibilidad con Power BI y
> drivers ODBC/JDBC.

---

## Estructura del repositorio

```
sql/
  00_run_all.sql                  Orquestador de despliegue (sqlcmd :r)
  01_tablas_fuente.sql            Esquema stg + tablas fuente (incl. Fase 2)
  02_tabla_maestra_y_control.sql  BASE_MAESTRA_COBRANZA + bitácoras + auditoría
  03_sp_construir_base_maestra.sql Procedimiento orquestador (PASOS 0–8)
  04_job_diario.sql               Job de SQL Server Agent (ejecución diaria)
  05_datos_prueba.sql             Datos de ejemplo para validación E2E
  06_consultas_validacion.sql     Consultas de control de calidad
docs/
  diccionario_datos.md            Diccionario de datos de la tabla final
```

---

## Despliegue

```bash
# 1) Crear la base (ajuste el nombre si lo requiere)
sqlcmd -S <servidor> -E -Q "IF DB_ID('CRZ_COBRANZA') IS NULL CREATE DATABASE CRZ_COBRANZA;"

# 2) Desplegar objetos (tablas + procedimiento)
#    Ejecutar DESDE la carpeta sql/ para que los includes ":r" se resuelvan.
cd sql && sqlcmd -S <servidor> -d CRZ_COBRANZA -E -i 00_run_all.sql && cd ..

# 3) (Opcional) Cargar datos de prueba y validar
sqlcmd -S <servidor> -d CRZ_COBRANZA -E -i sql/05_datos_prueba.sql
sqlcmd -S <servidor> -d CRZ_COBRANZA -E -Q "EXEC dbo.sp_construir_base_maestra @debug=1;"
sqlcmd -S <servidor> -d CRZ_COBRANZA -E -i sql/06_consultas_validacion.sql

# 4) Programar la ejecución diaria (ajuste @nombre_bd y @hora_inicio dentro del script)
sqlcmd -S <servidor> -E -i sql/04_job_diario.sql
```

Operación diaria (manual o vía job):

```sql
EXEC dbo.sp_construir_base_maestra;        -- producción
EXEC dbo.sp_construir_base_maestra @debug=1;-- con conteos por paso
```

El proceso es **idempotente**: cada corrida reconstruye `BASE_MAESTRA_COBRANZA`
por completo (`TRUNCATE` + `INSERT` dentro de una transacción), garantizando
`NO_DAMA` único.

---

## Secuencia de construcción (PASOS)

| Paso | Acción | Fuente / Llave |
|------|--------|----------------|
| 0 | **Pre-flight**: valida existencia de tablas fuente | — |
| 1 | `TMP_CARTERA`: único por `NO_DAMA`, conserva el registro **más reciente** | `CARTERA_INACTIVAS` |
| 2 | Datos de cliente + `NOMBRE_COMPLETO` + `DIRECCION_COMPLETA` | `CLIENTES` por `NO_DAMA` |
| 3 | Asignación geográfica: `REGION, DIVISION, RUTA, ID_COBRADOR` | `ZONAS_ASIGNADAS` por `ZONA` |
| 4 | Situación de mora | `CARTERA_MORA` por `NO_DAMA` |
| 5 | **Última gestión** + `NUMERO_GESTIONES` | `LAYOUT_ARABELA` por `NO_DAMA` |
| 6 | `SALDO_ACTUALIZADO` | `SALDOS_ACTUALIZADOS` por `NO_DAMA + CAMPANA_SALDO` |
| 7 | Indicadores `TEMPORALIDAD` y `DIAS_MORA` | calculado |
| 8 | `SALDO_FINAL = SALDO_DAMA - PAGOS_DAMA` | calculado |

**Reglas de cálculo**

- `DIAS_MORA = fecha_proceso - FECHA_FACTURA`.
- `TEMPORALIDAD`: por campaña (distancia a la más reciente) → `Inactivas`, `Mora 1`, `Mora 2`, `Mora 3`.
- `SALDO_FINAL = ISNULL(SALDO_DAMA,0) - ISNULL(PAGOS_DAMA,0)` (si no hay pagos → `SALDO_DAMA`).
- `PRECIERRE` = `PRECIERRE_2` si existe, en su defecto `PRECIERRE_1`.
- Los cruces 2–6 usan **LEFT JOIN**: nunca se pierde un `NO_DAMA` de cartera.

---

## Validaciones y trazabilidad

Cada corrida registra trazabilidad completa:

| Tabla | Propósito |
|-------|-----------|
| `dbo.BITACORA_EJECUCION` | 1 fila por corrida: fecha/hora, estatus, **registros procesados / consolidados / con error** |
| `dbo.BITACORA_ERRORES` | Detalle técnico de excepciones (número, severidad, línea, mensaje) |
| `dbo.AUDITORIA_RECHAZOS` | Registros rechazados / con advertencia, con motivo |

**Catálogo de motivos** (`AUDITORIA_RECHAZOS.MOTIVO`):

- `NO_DAMA_DUPLICADO` (RECHAZO): duplicado descartado; se conserva el más reciente.
- `ZONA_SIN_COBRADOR` (ADVERTENCIA): zona sin cobrador en `ZONAS_ASIGNADAS`.
- `SALDO_NEGATIVO` (ADVERTENCIA): `SALDO_FINAL < 0`.

> Las advertencias **no descartan** la fila; quedan en la base maestra y se
> registran para revisión operativa.

---

## Fase 2 y futuras integraciones

Las estructuras ya están creadas en el esquema `stg` para integración futura,
sin necesidad de rediseñar la tabla maestra:

- `stg.PAGOS_MORAS` (Fase 2) — pagos para refinar `SALDO_FINAL`.
- `stg.REPORTE_VISITAS` (Fase 2) — visitas domiciliarias.
- `stg.REPORTE_REMINDER` (En construcción) — recordatorios (SMS/WhatsApp/Email/IVR).

---

## Validación de ejemplo

Con los datos de `05_datos_prueba.sql` (6 filas de cartera, 5 `NO_DAMA`):

```
ESTATUS  REG_PROCESADOS  REG_CONSOLIDADOS  REG_CON_ERROR
EXITO    6               5                 3
```

- `0002` aparece dos veces → gana la campaña más reciente; el duplicado se audita.
- `0003` (zona `Z99`) → advertencia `ZONA_SIN_COBRADOR`.
- `0004` (pagos > saldo) → advertencia `SALDO_NEGATIVO`.
- `NO_DAMA` queda **único** en `BASE_MAESTRA_COBRANZA`.
