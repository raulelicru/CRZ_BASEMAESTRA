# Diccionario de Datos — `BASE_MAESTRA_COBRANZA`

Llave principal: **`NO_DAMA`** (único). Una fila por cliente/cuenta.

| Columna | Tipo | Origen (PASO) | Descripción |
|---------|------|---------------|-------------|
| `REGION` | varchar(60) | ZONAS_ASIGNADAS (3) | Región de la zona |
| `DIVISION` | varchar(60) | ZONAS_ASIGNADAS (3) | División de la zona |
| `ZONA` | varchar(20) | CARTERA_INACTIVAS (1) | Zona de cobranza |
| `RUTA` | varchar(60) | ZONAS_ASIGNADAS (3) | Ruta asignada |
| `ID_COBRADOR` | varchar(30) | ZONAS_ASIGNADAS (3) | Cobrador asignado a la zona |
| `NO_DAMA` | varchar(20) | CARTERA_INACTIVAS (1) | **Llave principal** |
| `DIGITO_DAMA` | varchar(5) | CLIENTES (2) | Dígito verificador |
| `NOMBRE_COMPLETO` | varchar(255) | CLIENTES (2) | `NOMBRE + APELLIDO_PATERNO + APELLIDO_MATERNO` |
| `DIRECCION_COMPLETA` | varchar(300) | CLIENTES (2) | `CALLE + NUMERO_EXTERIOR + NUMERO_INTERIOR` |
| `COLONIA` | varchar(120) | CLIENTES (2) | Colonia |
| `CODIGO_POSTAL` | varchar(10) | CLIENTES (2) | Código postal |
| `POBLACION` | varchar(120) | CLIENTES (2) | Población |
| `ESTADO` | varchar(60) | CLIENTES (2) | Estado |
| `TELEFONO_CASA` | varchar(20) | CLIENTES (2) | Teléfono fijo |
| `TELEFONO_CELULAR` | varchar(20) | CLIENTES (2) | Teléfono celular |
| `CAMPANA_SALDO` | varchar(20) | CARTERA_INACTIVAS (1) | Campaña de saldo (*CAMPAÑA_SALDO*) |
| `FECHA_FACTURA` | date | CARTERA_INACTIVAS (1) | Fecha de factura (base de `DIAS_MORA`) |
| `FECHA_INICIAL_VIGENCIA` | date | CARTERA_INACTIVAS (1) | Inicio de vigencia |
| `FECHA_FINAL_VIGENCIA` | date | CARTERA_INACTIVAS (1) | Fin de vigencia |
| `SEGMENTO` | varchar(50) | CARTERA_INACTIVAS (1) | Segmento del cliente |
| `ESTADO_PROCESO` | varchar(50) | CARTERA_INACTIVAS (1) | Estado del proceso |
| `SALDO_DAMA` | decimal(18,2) | CARTERA_INACTIVAS (1) | Saldo origen |
| `PAGOS_DAMA` | decimal(18,2) | CARTERA_INACTIVAS (1) | Pagos aplicados |
| `SALDO_ACTUALIZADO` | decimal(18,2) | SALDOS_ACTUALIZADOS (6) | Saldo actualizado por campaña |
| `TEMPORALIDAD` | varchar(10) | Calculado (7) | Bucket de antigüedad de mora |
| `DIAS_MORA` | int | Calculado (7) | `fecha_proceso - FECHA_FACTURA` |
| `ID_SITUACION` | varchar(20) | CARTERA_MORA (4) | ID situación |
| `DESC_SITUACION` | varchar(120) | CARTERA_MORA (4) | Descripción situación |
| `ID_SITUACION_CIE` | varchar(20) | CARTERA_MORA (4) | ID situación CIE |
| `DESC_SITUACION_CIE` | varchar(120) | CARTERA_MORA (4) | Descripción situación CIE |
| `TIPO_NOMBRAMIENTO` | varchar(60) | CARTERA_MORA (4) | Tipo de nombramiento |
| `STATUS_GESTION` | varchar(60) | LAYOUT_ARABELA (5) | Estatus de la última gestión |
| `MOTIVO_NO_COBRO` | varchar(120) | LAYOUT_ARABELA (5) | Motivo de no cobro |
| `DICTAMINACION` | varchar(120) | LAYOUT_ARABELA (5) | Dictaminación |
| `NUMERO_GESTIONES` | int | LAYOUT_ARABELA (5) | Conteo de gestiones por `NO_DAMA` |
| `FECHA_PROMESA` | date | LAYOUT_ARABELA (5) | Fecha de promesa de pago |
| `PRIMERA_ORDEN` | varchar(40) | CARTERA_MORA (4) | Primera orden |
| `REACTIVACION` | varchar(40) | CARTERA_MORA (4) | Reactivación |
| `CANCELACION` | varchar(40) | CARTERA_MORA (4) | Cancelación |
| `PRECIERRE` | varchar(40) | Calculado (4) | Precierre vigente (`PRECIERRE_2` ?? `PRECIERRE_1`) |
| `PRECIERRE_1` | varchar(40) | CARTERA_MORA (4) | Precierre 1 |
| `PRECIERRE_2` | varchar(40) | CARTERA_MORA (4) | Precierre 2 |
| `GEOLOCALIZACION` | varchar(80) | CARTERA_MORA (4) | Geolocalización |
| `FECHA_CARGA` | datetime2 | CARTERA_INACTIVAS (1) | Fecha de carga del origen |
| `FECHA_ACTUALIZACION` | datetime2 | Proceso | Fecha/hora de la corrida |

## Reglas de `TEMPORALIDAD`

| Rango de `DIAS_MORA` | `TEMPORALIDAD` |
|----------------------|----------------|
| 0 – 30 | `0-30` |
| 31 – 60 | `31-60` |
| 61 – 90 | `61-90` |
| 91 – 120 | `91-120` |
| 121 – 150 | `121-150` |
| 151 – 180 | `151-180` |
| 181 o más | `181+` |
