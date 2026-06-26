/* =====================================================================
   PROYECTO : Base Maestra de Cobranza
   ARCHIVO  : 01_tablas_fuente.sql
   OBJETIVO : Crear el esquema de trabajo y las tablas fuente (staging)
              que alimentan a BASE_MAESTRA_COBRANZA.

   MOTOR    : SQL Server (T-SQL)

   NOTA SOBRE NOMBRES:
     El campo de negocio "CAMPAÑA_SALDO" se normaliza a ASCII como
     CAMPANA_SALDO para garantizar compatibilidad con Power BI, drivers
     ODBC/JDBC y herramientas de carga. Se documenta esta equivalencia.

   IDEMPOTENTE: el script puede ejecutarse varias veces sin error.
   ===================================================================== */

SET NOCOUNT ON;
GO

/* ---------------------------------------------------------------------
   Esquemas
     stg = staging / fuentes crudas
     dbo = tablas de explotacion y control
   --------------------------------------------------------------------- */
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'stg')
    EXEC ('CREATE SCHEMA stg AUTHORIZATION dbo;');
GO

/* =====================================================================
   1) CARTERA_INACTIVAS  -- Tabla principal (PASO 1)
   ===================================================================== */
IF OBJECT_ID('stg.CARTERA_INACTIVAS','U') IS NOT NULL
    DROP TABLE stg.CARTERA_INACTIVAS;
GO
CREATE TABLE stg.CARTERA_INACTIVAS
(
    NO_DAMA                 VARCHAR(20)   NOT NULL,
    ZONA                    VARCHAR(20)   NULL,
    CAMPANA_SALDO           VARCHAR(20)   NULL,   -- CAMPAÑA_SALDO
    FECHA_FACTURA           DATE          NULL,
    FECHA_INICIAL_VIGENCIA  DATE          NULL,
    FECHA_FINAL_VIGENCIA    DATE          NULL,
    SEGMENTO                VARCHAR(50)   NULL,
    ESTADO_PROCESO          VARCHAR(50)   NULL,
    SALDO_DAMA              DECIMAL(18,2) NULL,
    PAGOS_DAMA              DECIMAL(18,2) NULL,
    FECHA_CARGA             DATETIME2(0)  NOT NULL CONSTRAINT DF_CARTINA_FCARGA DEFAULT (SYSDATETIME())
);
GO
CREATE INDEX IX_CARTINA_NODAMA ON stg.CARTERA_INACTIVAS (NO_DAMA, CAMPANA_SALDO);
GO

/* =====================================================================
   2) CLIENTES  (PASO 2)
   ===================================================================== */
IF OBJECT_ID('stg.CLIENTES','U') IS NOT NULL
    DROP TABLE stg.CLIENTES;
GO
CREATE TABLE stg.CLIENTES
(
    NO_DAMA            VARCHAR(20)  NOT NULL,
    DIGITO_DAMA        VARCHAR(5)   NULL,
    NOMBRE             VARCHAR(80)  NULL,
    APELLIDO_PATERNO   VARCHAR(80)  NULL,
    APELLIDO_MATERNO   VARCHAR(80)  NULL,
    CALLE              VARCHAR(120) NULL,
    NUMERO_EXTERIOR    VARCHAR(20)  NULL,
    NUMERO_INTERIOR    VARCHAR(20)  NULL,
    COLONIA            VARCHAR(120) NULL,
    CODIGO_POSTAL      VARCHAR(10)  NULL,
    POBLACION          VARCHAR(120) NULL,
    ESTADO             VARCHAR(60)  NULL,
    TELEFONO_CASA      VARCHAR(20)  NULL,
    TELEFONO_CELULAR   VARCHAR(20)  NULL
);
GO
CREATE UNIQUE INDEX UX_CLIENTES_NODAMA ON stg.CLIENTES (NO_DAMA);
GO

/* =====================================================================
   3) ZONAS_ASIGNADAS  (PASO 3)
   ===================================================================== */
IF OBJECT_ID('stg.ZONAS_ASIGNADAS','U') IS NOT NULL
    DROP TABLE stg.ZONAS_ASIGNADAS;
GO
CREATE TABLE stg.ZONAS_ASIGNADAS
(
    ZONA          VARCHAR(20)  NOT NULL,
    REGION        VARCHAR(60)  NULL,
    DIVISION      VARCHAR(60)  NULL,
    RUTA          VARCHAR(60)  NULL,
    ID_COBRADOR   VARCHAR(30)  NULL
);
GO
CREATE UNIQUE INDEX UX_ZONAS_ZONA ON stg.ZONAS_ASIGNADAS (ZONA);
GO

/* =====================================================================
   4) CARTERA_MORA  (PASO 4)
   ===================================================================== */
IF OBJECT_ID('stg.CARTERA_MORA','U') IS NOT NULL
    DROP TABLE stg.CARTERA_MORA;
GO
CREATE TABLE stg.CARTERA_MORA
(
    NO_DAMA                VARCHAR(20)  NOT NULL,
    ID_SITUACION           VARCHAR(20)  NULL,
    DESC_SITUACION         VARCHAR(120) NULL,
    ID_SITUACION_CIE       VARCHAR(20)  NULL,
    DESC_SITUACION_CIE     VARCHAR(120) NULL,
    TIPO_NOMBRAMIENTO      VARCHAR(60)  NULL,
    GEOLOCALIZACION        VARCHAR(80)  NULL,
    NUMERO_LIQUIDACION     VARCHAR(40)  NULL,
    PRECIERRE_1            VARCHAR(40)  NULL,
    PRECIERRE_2            VARCHAR(40)  NULL,
    REACTIVACION           VARCHAR(40)  NULL,
    CANCELACION            VARCHAR(40)  NULL,
    PRIMERA_ORDEN          VARCHAR(40)  NULL
);
GO
CREATE INDEX IX_CARTMORA_NODAMA ON stg.CARTERA_MORA (NO_DAMA);
GO

/* =====================================================================
   5) LAYOUT_ARABELA  (PASO 5) -- gestiones telefonicas / dictaminacion
       Se conserva FECHA_GESTION para identificar la ULTIMA gestion.
   ===================================================================== */
IF OBJECT_ID('stg.LAYOUT_ARABELA','U') IS NOT NULL
    DROP TABLE stg.LAYOUT_ARABELA;
GO
CREATE TABLE stg.LAYOUT_ARABELA
(
    NO_DAMA           VARCHAR(20)  NOT NULL,
    FECHA_GESTION     DATETIME2(0) NULL,
    STATUS_GESTION    VARCHAR(60)  NULL,
    MOTIVO_NO_COBRO   VARCHAR(120) NULL,
    DICTAMINACION     VARCHAR(120) NULL,
    FECHA_PROMESA     DATE         NULL
);
GO
CREATE INDEX IX_ARABELA_NODAMA ON stg.LAYOUT_ARABELA (NO_DAMA, FECHA_GESTION DESC);
GO

/* =====================================================================
   6) SALDOS_ACTUALIZADOS  (PASO 6)
       Llave: NO_DAMA + CAMPANA_SALDO
   ===================================================================== */
IF OBJECT_ID('stg.SALDOS_ACTUALIZADOS','U') IS NOT NULL
    DROP TABLE stg.SALDOS_ACTUALIZADOS;
GO
CREATE TABLE stg.SALDOS_ACTUALIZADOS
(
    NO_DAMA            VARCHAR(20)   NOT NULL,
    CAMPANA_SALDO      VARCHAR(20)   NOT NULL,  -- CAMPAÑA_SALDO
    SALDO_ACTUALIZADO  DECIMAL(18,2) NULL
);
GO
CREATE UNIQUE INDEX UX_SALDOSACT_KEY ON stg.SALDOS_ACTUALIZADOS (NO_DAMA, CAMPANA_SALDO);
GO

/* =====================================================================
   FASE 2 / EN CONSTRUCCION  (estructuras preparadas para integracion)
   ===================================================================== */

/* PAGOS_MORAS (Fase 2) -- pagos aplicados en mora */
IF OBJECT_ID('stg.PAGOS_MORAS','U') IS NOT NULL
    DROP TABLE stg.PAGOS_MORAS;
GO
CREATE TABLE stg.PAGOS_MORAS
(
    NO_DAMA        VARCHAR(20)   NOT NULL,
    CAMPANA_SALDO  VARCHAR(20)   NULL,
    FECHA_PAGO     DATE          NULL,
    MONTO_PAGO     DECIMAL(18,2) NULL,
    REFERENCIA     VARCHAR(60)   NULL
);
GO
CREATE INDEX IX_PAGOSMORAS_NODAMA ON stg.PAGOS_MORAS (NO_DAMA, CAMPANA_SALDO);
GO

/* REPORTE_VISITAS (Fase 2) -- visitas domiciliarias */
IF OBJECT_ID('stg.REPORTE_VISITAS','U') IS NOT NULL
    DROP TABLE stg.REPORTE_VISITAS;
GO
CREATE TABLE stg.REPORTE_VISITAS
(
    NO_DAMA          VARCHAR(20)  NOT NULL,
    FECHA_VISITA     DATETIME2(0) NULL,
    RESULTADO_VISITA VARCHAR(120) NULL,
    ID_COBRADOR      VARCHAR(30)  NULL,
    GEOLOCALIZACION  VARCHAR(80)  NULL
);
GO
CREATE INDEX IX_VISITAS_NODAMA ON stg.REPORTE_VISITAS (NO_DAMA, FECHA_VISITA DESC);
GO

/* REPORTE_REMINDER (En construccion) -- recordatorios */
IF OBJECT_ID('stg.REPORTE_REMINDER','U') IS NOT NULL
    DROP TABLE stg.REPORTE_REMINDER;
GO
CREATE TABLE stg.REPORTE_REMINDER
(
    NO_DAMA            VARCHAR(20)  NOT NULL,
    FECHA_REMINDER     DATETIME2(0) NULL,
    CANAL              VARCHAR(40)  NULL,   -- SMS / WHATSAPP / EMAIL / IVR
    RESULTADO_REMINDER VARCHAR(120) NULL
);
GO
CREATE INDEX IX_REMINDER_NODAMA ON stg.REPORTE_REMINDER (NO_DAMA, FECHA_REMINDER DESC);
GO

PRINT 'Tablas fuente (stg) creadas correctamente.';
GO
