/* =====================================================================
   PROYECTO : Base Maestra de Cobranza
   ARCHIVO  : 02_tabla_maestra_y_control.sql
   OBJETIVO : Crear la tabla de explotacion BASE_MAESTRA_COBRANZA y las
              tablas de control: bitacora de ejecucion, bitacora de
              errores y auditoria de registros rechazados.
   MOTOR    : SQL Server (T-SQL)
   ===================================================================== */

SET NOCOUNT ON;
GO

/* =====================================================================
   TABLA DE EXPLOTACION:  BASE_MAESTRA_COBRANZA
   Llave principal : NO_DAMA  (unico)
   ===================================================================== */
IF OBJECT_ID('dbo.BASE_MAESTRA_COBRANZA','U') IS NOT NULL
    DROP TABLE dbo.BASE_MAESTRA_COBRANZA;
GO
CREATE TABLE dbo.BASE_MAESTRA_COBRANZA
(
    /* --- Asignacion / geografia --- */
    REGION                  VARCHAR(60)   NULL,
    DIVISION                VARCHAR(60)   NULL,
    ZONA                    VARCHAR(20)   NULL,
    RUTA                    VARCHAR(60)   NULL,
    ID_COBRADOR             VARCHAR(30)   NULL,

    /* --- Identificacion cliente --- */
    NO_DAMA                 VARCHAR(20)   NOT NULL,
    DIGITO_DAMA             VARCHAR(5)    NULL,
    NOMBRE_COMPLETO         VARCHAR(255)  NULL,

    /* --- Domicilio / contacto --- */
    DIRECCION_COMPLETA      VARCHAR(300)  NULL,
    COLONIA                 VARCHAR(120)  NULL,
    CODIGO_POSTAL           VARCHAR(10)   NULL,
    POBLACION               VARCHAR(120)  NULL,
    ESTADO                  VARCHAR(60)   NULL,
    TELEFONO_CASA           VARCHAR(20)   NULL,
    TELEFONO_CELULAR        VARCHAR(20)   NULL,

    /* --- Campania / vigencias --- */
    CAMPANA_SALDO           VARCHAR(20)   NULL,   -- CAMPAÑA_SALDO
    FECHA_FACTURA           DATE          NULL,
    FECHA_INICIAL_VIGENCIA  DATE          NULL,
    FECHA_FINAL_VIGENCIA    DATE          NULL,
    SEGMENTO                VARCHAR(50)   NULL,
    ESTADO_PROCESO          VARCHAR(50)   NULL,

    /* --- Saldos --- */
    SALDO_DAMA              DECIMAL(18,2) NULL,
    PAGOS_DAMA              DECIMAL(18,2) NULL,
    SALDO_ACTUALIZADO       DECIMAL(18,2) NULL,
    SALDO_FINAL             DECIMAL(18,2) NULL,

    /* --- Indicadores --- */
    TEMPORALIDAD            VARCHAR(10)   NULL,    -- 0-30 ... 181+
    DIAS_MORA               INT           NULL,

    /* --- Situacion (CARTERA_MORA) --- */
    ID_SITUACION            VARCHAR(20)   NULL,
    DESC_SITUACION          VARCHAR(120)  NULL,
    ID_SITUACION_CIE        VARCHAR(20)   NULL,
    DESC_SITUACION_CIE      VARCHAR(120)  NULL,
    TIPO_NOMBRAMIENTO       VARCHAR(60)   NULL,

    /* --- Gestion (LAYOUT_ARABELA) --- */
    STATUS_GESTION          VARCHAR(60)   NULL,
    MOTIVO_NO_COBRO         VARCHAR(120)  NULL,
    DICTAMINACION           VARCHAR(120)  NULL,
    NUMERO_GESTIONES        INT           NULL,
    FECHA_PROMESA           DATE          NULL,

    /* --- Estatus de proceso de mora --- */
    PRIMERA_ORDEN           VARCHAR(40)   NULL,
    REACTIVACION            VARCHAR(40)   NULL,
    CANCELACION             VARCHAR(40)   NULL,
    PRECIERRE               VARCHAR(40)   NULL,    -- precierre vigente (1 o 2)
    PRECIERRE_1             VARCHAR(40)   NULL,
    PRECIERRE_2             VARCHAR(40)   NULL,
    GEOLOCALIZACION         VARCHAR(80)   NULL,

    /* --- Control de carga --- */
    FECHA_CARGA             DATETIME2(0)  NULL,
    FECHA_ACTUALIZACION     DATETIME2(0)  NULL,

    CONSTRAINT PK_BASE_MAESTRA_COBRANZA PRIMARY KEY CLUSTERED (NO_DAMA)
);
GO
CREATE INDEX IX_BMC_ZONA        ON dbo.BASE_MAESTRA_COBRANZA (ZONA);
CREATE INDEX IX_BMC_COBRADOR    ON dbo.BASE_MAESTRA_COBRANZA (ID_COBRADOR);
CREATE INDEX IX_BMC_TEMPORALIDAD ON dbo.BASE_MAESTRA_COBRANZA (TEMPORALIDAD);
GO

/* =====================================================================
   BITACORA DE EJECUCION  -- una fila por corrida del proceso
   ===================================================================== */
IF OBJECT_ID('dbo.BITACORA_EJECUCION','U') IS NOT NULL
    DROP TABLE dbo.BITACORA_EJECUCION;
GO
CREATE TABLE dbo.BITACORA_EJECUCION
(
    ID_EJECUCION         BIGINT IDENTITY(1,1) PRIMARY KEY,
    PROCESO              VARCHAR(80)  NOT NULL,
    FECHA_INICIO         DATETIME2(0) NOT NULL,
    FECHA_FIN            DATETIME2(0) NULL,
    ESTATUS              VARCHAR(20)  NULL,   -- EN_PROCESO / EXITO / ERROR
    REG_PROCESADOS       INT          NULL,   -- leidos de CARTERA_INACTIVAS
    REG_CONSOLIDADOS     INT          NULL,   -- insertados en la base maestra
    REG_CON_ERROR        INT          NULL,   -- rechazados / con incidencia
    MENSAJE              VARCHAR(MAX) NULL
);
GO

/* =====================================================================
   BITACORA DE ERRORES  -- detalle de incidencias tecnicas
   ===================================================================== */
IF OBJECT_ID('dbo.BITACORA_ERRORES','U') IS NOT NULL
    DROP TABLE dbo.BITACORA_ERRORES;
GO
CREATE TABLE dbo.BITACORA_ERRORES
(
    ID_ERROR        BIGINT IDENTITY(1,1) PRIMARY KEY,
    ID_EJECUCION    BIGINT       NULL,
    FECHA_HORA      DATETIME2(0) NOT NULL CONSTRAINT DF_BITERR_FH DEFAULT (SYSDATETIME()),
    PASO            VARCHAR(40)  NULL,
    ERROR_NUMBER    INT          NULL,
    ERROR_SEVERITY  INT          NULL,
    ERROR_LINE      INT          NULL,
    ERROR_MENSAJE   VARCHAR(MAX) NULL
);
GO

/* =====================================================================
   AUDITORIA DE REGISTROS RECHAZADOS  -- detalle de negocio
     Motivos: NO_DAMA_DUPLICADO, ZONA_SIN_COBRADOR, SALDO_NEGATIVO, etc.
   ===================================================================== */
IF OBJECT_ID('dbo.AUDITORIA_RECHAZOS','U') IS NOT NULL
    DROP TABLE dbo.AUDITORIA_RECHAZOS;
GO
CREATE TABLE dbo.AUDITORIA_RECHAZOS
(
    ID_RECHAZO     BIGINT IDENTITY(1,1) PRIMARY KEY,
    ID_EJECUCION   BIGINT       NULL,
    FECHA_HORA     DATETIME2(0) NOT NULL CONSTRAINT DF_AUDREC_FH DEFAULT (SYSDATETIME()),
    PASO           VARCHAR(40)  NULL,
    MOTIVO         VARCHAR(60)  NOT NULL,   -- catalogo de motivo de rechazo
    NIVEL          VARCHAR(20)  NULL,       -- RECHAZO / ADVERTENCIA
    NO_DAMA        VARCHAR(20)  NULL,
    CAMPANA_SALDO  VARCHAR(20)  NULL,
    ZONA           VARCHAR(20)  NULL,
    DETALLE        VARCHAR(MAX) NULL
);
GO
CREATE INDEX IX_AUDREC_EJEC ON dbo.AUDITORIA_RECHAZOS (ID_EJECUCION, MOTIVO);
GO

PRINT 'Tabla maestra y tablas de control creadas correctamente.';
GO
