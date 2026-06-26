/* =====================================================================
   PROYECTO : Base Maestra de Cobranza
   ARCHIVO  : 03_sp_construir_base_maestra.sql
   OBJETIVO : Procedimiento orquestador que construye BASE_MAESTRA_COBRANZA
              siguiendo la secuencia de 8 pasos. Pensado para ejecucion
              diaria.
   MOTOR    : SQL Server (T-SQL)

   SECUENCIA:
     PASO 1  TMP_CARTERA: unico por NO_DAMA (registro mas reciente)
     PASO 2  + CLIENTES  -> NOMBRE_COMPLETO, DIRECCION_COMPLETA
     PASO 3  + ZONAS_ASIGNADAS (por ZONA)
     PASO 4  + CARTERA_MORA (por NO_DAMA)
     PASO 5  + LAYOUT_ARABELA (ultima gestion + NUMERO_GESTIONES)
     PASO 6  + SALDOS_ACTUALIZADOS (NO_DAMA + CAMPANA_SALDO)
     PASO 7  TEMPORALIDAD, DIAS_MORA
     PASO 8  SALDO_FINAL = SALDO_DAMA - PAGOS_DAMA

   VALIDACIONES:
     - No NO_DAMA duplicados (se conserva el mas reciente por campania)
     - Zonas sin cobrador asignado (advertencia)
     - Saldos negativos (advertencia)
     - Bitacora de ejecucion / errores
     - Auditoria de registros rechazados
   ===================================================================== */

SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

CREATE OR ALTER PROCEDURE dbo.sp_construir_base_maestra
    @debug BIT = 0   -- 1 = devuelve conteos por paso como result sets
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @id_ejecucion   BIGINT,
            @fecha_proceso   DATETIME2(0) = SYSDATETIME(),
            @reg_procesados  INT = 0,
            @reg_consolidados INT = 0,
            @reg_con_error   INT = 0,
            @paso            VARCHAR(40) = 'INICIO';

    /* ---- Abrir bitacora de ejecucion ---- */
    INSERT INTO dbo.BITACORA_EJECUCION (PROCESO, FECHA_INICIO, ESTATUS)
    VALUES ('BASE_MAESTRA_COBRANZA', @fecha_proceso, 'EN_PROCESO');
    SET @id_ejecucion = SCOPE_IDENTITY();

    BEGIN TRY
        /* =============================================================
           PASO 0 -- PRE-FLIGHT: validar existencia de tablas fuente.
           Los errores de "objeto inexistente" (Msg 208) ocurren en
           tiempo de compilacion del SELECT...INTO y NO son atrapables
           por TRY/CATCH en el mismo ambito. Validar aqui convierte la
           falla mas comun (tabla fuente faltante/renombrada) en un
           error limpio, atrapable y registrado en bitacora.
           ============================================================= */
        SET @paso = 'PASO0_PREFLIGHT';

        DECLARE @faltantes VARCHAR(MAX) = NULL;
        SELECT @faltantes = STRING_AGG(t.tabla, ', ')
        FROM (VALUES
                ('stg.CARTERA_INACTIVAS'),
                ('stg.CLIENTES'),
                ('stg.ZONAS_ASIGNADAS'),
                ('stg.CARTERA_MORA'),
                ('stg.LAYOUT_ARABELA'),
                ('stg.SALDOS_ACTUALIZADOS')
             ) AS t(tabla)
        WHERE OBJECT_ID(t.tabla, 'U') IS NULL;

        IF @faltantes IS NOT NULL
        BEGIN
            DECLARE @msg_faltantes NVARCHAR(2048) =
                CONCAT(N'Tablas fuente faltantes: ', @faltantes);
            THROW 50001, @msg_faltantes, 1;
        END

        /* =============================================================
           PASO 1 -- TMP_CARTERA: unico por NO_DAMA
           Se conserva el registro mas reciente por NO_DAMA usando
           FECHA_FACTURA (desempate por FECHA_FINAL_VIGENCIA y FECHA_CARGA).
           Los registros descartados se auditan como NO_DAMA_DUPLICADO.
           ============================================================= */
        SET @paso = 'PASO1_TMP_CARTERA';

        IF OBJECT_ID('tempdb..#TMP_CARTERA') IS NOT NULL DROP TABLE #TMP_CARTERA;

        ;WITH ranked AS
        (
            SELECT  ci.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY ci.NO_DAMA
                        ORDER BY  ci.FECHA_FACTURA        DESC,
                                  ci.FECHA_FINAL_VIGENCIA DESC,
                                  ci.FECHA_CARGA          DESC
                    ) AS rn
            FROM stg.CARTERA_INACTIVAS ci
            WHERE ci.NO_DAMA IS NOT NULL AND LTRIM(RTRIM(ci.NO_DAMA)) <> ''
        )
        SELECT
            NO_DAMA, ZONA, CAMPANA_SALDO, FECHA_FACTURA,
            FECHA_INICIAL_VIGENCIA, FECHA_FINAL_VIGENCIA,
            SEGMENTO, ESTADO_PROCESO, SALDO_DAMA, PAGOS_DAMA, FECHA_CARGA
        INTO #TMP_CARTERA
        FROM ranked
        WHERE rn = 1;

        SELECT @reg_procesados = COUNT(*) FROM stg.CARTERA_INACTIVAS;

        CREATE UNIQUE CLUSTERED INDEX UX_TMP_CARTERA ON #TMP_CARTERA (NO_DAMA);

        /* Auditoria: registros duplicados descartados (rn > 1) */
        INSERT INTO dbo.AUDITORIA_RECHAZOS
            (ID_EJECUCION, PASO, MOTIVO, NIVEL, NO_DAMA, CAMPANA_SALDO, ZONA, DETALLE)
        SELECT @id_ejecucion, @paso, 'NO_DAMA_DUPLICADO', 'RECHAZO',
               d.NO_DAMA, d.CAMPANA_SALDO, d.ZONA,
               'Registro duplicado descartado; se conservo el mas reciente por NO_DAMA.'
        FROM
        (
            SELECT ci.NO_DAMA, ci.CAMPANA_SALDO, ci.ZONA,
                   ROW_NUMBER() OVER (
                       PARTITION BY ci.NO_DAMA
                       ORDER BY ci.FECHA_FACTURA DESC,
                                ci.FECHA_FINAL_VIGENCIA DESC,
                                ci.FECHA_CARGA DESC) AS rn
            FROM stg.CARTERA_INACTIVAS ci
            WHERE ci.NO_DAMA IS NOT NULL AND LTRIM(RTRIM(ci.NO_DAMA)) <> ''
        ) d
        WHERE d.rn > 1;

        IF @debug = 1 SELECT 'PASO1' AS paso, COUNT(*) AS filas FROM #TMP_CARTERA;

        /* =============================================================
           PASOS 2..8 -- construccion del set final en #BASE
           Se usan LEFT JOIN para preservar todos los NO_DAMA de cartera.
           ============================================================= */
        SET @paso = 'PASO2_8_CONSTRUCCION';

        IF OBJECT_ID('tempdb..#BASE') IS NOT NULL DROP TABLE #BASE;

        /* Ultima gestion de LAYOUT_ARABELA por NO_DAMA (PASO 5) */
        ;WITH arabela_ult AS
        (
            SELECT  la.NO_DAMA, la.STATUS_GESTION, la.MOTIVO_NO_COBRO,
                    la.DICTAMINACION, la.FECHA_PROMESA,
                    ROW_NUMBER() OVER (PARTITION BY la.NO_DAMA
                                       ORDER BY la.FECHA_GESTION DESC) AS rn
            FROM stg.LAYOUT_ARABELA la
        ),
        arabela_cnt AS   /* NUMERO_GESTIONES por NO_DAMA */
        (
            SELECT NO_DAMA, COUNT(*) AS NUMERO_GESTIONES
            FROM stg.LAYOUT_ARABELA
            GROUP BY NO_DAMA
        )
        SELECT
            /* --- PASO 3: asignacion / geografia --- */
            za.REGION,
            za.DIVISION,
            t.ZONA,
            za.RUTA,
            za.ID_COBRADOR,

            /* --- PASO 2: identificacion cliente --- */
            t.NO_DAMA,
            c.DIGITO_DAMA,
            NOMBRE_COMPLETO = LTRIM(RTRIM(
                CONCAT_WS(' ', NULLIF(LTRIM(RTRIM(c.NOMBRE)),''),
                               NULLIF(LTRIM(RTRIM(c.APELLIDO_PATERNO)),''),
                               NULLIF(LTRIM(RTRIM(c.APELLIDO_MATERNO)),'')) )),

            /* --- domicilio / contacto --- */
            DIRECCION_COMPLETA = LTRIM(RTRIM(
                CONCAT_WS(' ', NULLIF(LTRIM(RTRIM(c.CALLE)),''),
                               NULLIF(LTRIM(RTRIM(c.NUMERO_EXTERIOR)),''),
                               NULLIF(LTRIM(RTRIM(c.NUMERO_INTERIOR)),'')) )),
            c.COLONIA,
            c.CODIGO_POSTAL,
            c.POBLACION,
            c.ESTADO,
            c.TELEFONO_CASA,
            c.TELEFONO_CELULAR,

            /* --- campania / vigencias --- */
            t.CAMPANA_SALDO,
            t.FECHA_FACTURA,
            t.FECHA_INICIAL_VIGENCIA,
            t.FECHA_FINAL_VIGENCIA,
            t.SEGMENTO,
            t.ESTADO_PROCESO,

            /* --- saldos (PASO 6 y 8) --- */
            t.SALDO_DAMA,
            t.PAGOS_DAMA,
            sa.SALDO_ACTUALIZADO,
            SALDO_FINAL = CAST(
                ISNULL(t.SALDO_DAMA,0) - ISNULL(t.PAGOS_DAMA,0)
                AS DECIMAL(18,2)),

            /* --- PASO 7: indicadores --- */
            DIAS_MORA = CASE WHEN t.FECHA_FACTURA IS NULL THEN NULL
                             ELSE DATEDIFF(DAY, t.FECHA_FACTURA, CAST(@fecha_proceso AS DATE)) END,
            TEMPORALIDAD = CASE
                WHEN t.FECHA_FACTURA IS NULL THEN NULL
                ELSE
                    CASE
                        WHEN DATEDIFF(DAY, t.FECHA_FACTURA, CAST(@fecha_proceso AS DATE)) <= 30  THEN '0-30'
                        WHEN DATEDIFF(DAY, t.FECHA_FACTURA, CAST(@fecha_proceso AS DATE)) <= 60  THEN '31-60'
                        WHEN DATEDIFF(DAY, t.FECHA_FACTURA, CAST(@fecha_proceso AS DATE)) <= 90  THEN '61-90'
                        WHEN DATEDIFF(DAY, t.FECHA_FACTURA, CAST(@fecha_proceso AS DATE)) <= 120 THEN '91-120'
                        WHEN DATEDIFF(DAY, t.FECHA_FACTURA, CAST(@fecha_proceso AS DATE)) <= 150 THEN '121-150'
                        WHEN DATEDIFF(DAY, t.FECHA_FACTURA, CAST(@fecha_proceso AS DATE)) <= 180 THEN '151-180'
                        ELSE '181+'
                    END
                END,

            /* --- PASO 4: situacion (CARTERA_MORA) --- */
            cm.ID_SITUACION,
            cm.DESC_SITUACION,
            cm.ID_SITUACION_CIE,
            cm.DESC_SITUACION_CIE,
            cm.TIPO_NOMBRAMIENTO,

            /* --- PASO 5: gestion (LAYOUT_ARABELA) --- */
            au.STATUS_GESTION,
            au.MOTIVO_NO_COBRO,
            au.DICTAMINACION,
            NUMERO_GESTIONES = ISNULL(ac.NUMERO_GESTIONES, 0),
            au.FECHA_PROMESA,

            /* --- estatus de proceso de mora --- */
            cm.PRIMERA_ORDEN,
            cm.REACTIVACION,
            cm.CANCELACION,
            PRECIERRE = COALESCE(NULLIF(LTRIM(RTRIM(cm.PRECIERRE_2)),''),
                                 NULLIF(LTRIM(RTRIM(cm.PRECIERRE_1)),'')),
            cm.PRECIERRE_1,
            cm.PRECIERRE_2,
            cm.GEOLOCALIZACION,

            /* --- control --- */
            FECHA_CARGA = t.FECHA_CARGA,
            FECHA_ACTUALIZACION = @fecha_proceso
        INTO #BASE
        FROM #TMP_CARTERA t
        LEFT JOIN stg.CLIENTES          c  ON c.NO_DAMA  = t.NO_DAMA
        LEFT JOIN stg.ZONAS_ASIGNADAS   za ON za.ZONA    = t.ZONA
        LEFT JOIN stg.CARTERA_MORA      cm ON cm.NO_DAMA = t.NO_DAMA
        LEFT JOIN arabela_ult           au ON au.NO_DAMA = t.NO_DAMA AND au.rn = 1
        LEFT JOIN arabela_cnt           ac ON ac.NO_DAMA = t.NO_DAMA
        LEFT JOIN stg.SALDOS_ACTUALIZADOS sa ON sa.NO_DAMA = t.NO_DAMA
                                            AND sa.CAMPANA_SALDO = t.CAMPANA_SALDO;

        IF @debug = 1 SELECT 'PASO2_8' AS paso, COUNT(*) AS filas FROM #BASE;

        /* =============================================================
           VALIDACIONES DE NEGOCIO (advertencias, no descartan filas)
           ============================================================= */
        SET @paso = 'VALIDACIONES';

        /* Zonas sin cobrador asignado */
        INSERT INTO dbo.AUDITORIA_RECHAZOS
            (ID_EJECUCION, PASO, MOTIVO, NIVEL, NO_DAMA, CAMPANA_SALDO, ZONA, DETALLE)
        SELECT @id_ejecucion, @paso, 'ZONA_SIN_COBRADOR', 'ADVERTENCIA',
               b.NO_DAMA, b.CAMPANA_SALDO, b.ZONA,
               'La zona no tiene cobrador asignado en ZONAS_ASIGNADAS.'
        FROM #BASE b
        WHERE b.ID_COBRADOR IS NULL OR LTRIM(RTRIM(b.ID_COBRADOR)) = '';

        /* Saldos negativos */
        INSERT INTO dbo.AUDITORIA_RECHAZOS
            (ID_EJECUCION, PASO, MOTIVO, NIVEL, NO_DAMA, CAMPANA_SALDO, ZONA, DETALLE)
        SELECT @id_ejecucion, @paso, 'SALDO_NEGATIVO', 'ADVERTENCIA',
               b.NO_DAMA, b.CAMPANA_SALDO, b.ZONA,
               CONCAT('SALDO_FINAL negativo = ', b.SALDO_FINAL)
        FROM #BASE b
        WHERE b.SALDO_FINAL < 0;

        /* =============================================================
           PUBLICACION ATOMICA EN LA TABLA DE EXPLOTACION
           ============================================================= */
        SET @paso = 'PUBLICACION';

        BEGIN TRANSACTION;

            TRUNCATE TABLE dbo.BASE_MAESTRA_COBRANZA;

            INSERT INTO dbo.BASE_MAESTRA_COBRANZA
            (
                REGION, DIVISION, ZONA, RUTA, ID_COBRADOR,
                NO_DAMA, DIGITO_DAMA, NOMBRE_COMPLETO,
                DIRECCION_COMPLETA, COLONIA, CODIGO_POSTAL, POBLACION, ESTADO,
                TELEFONO_CASA, TELEFONO_CELULAR,
                CAMPANA_SALDO, FECHA_FACTURA, FECHA_INICIAL_VIGENCIA, FECHA_FINAL_VIGENCIA,
                SEGMENTO, ESTADO_PROCESO,
                SALDO_DAMA, PAGOS_DAMA, SALDO_ACTUALIZADO, SALDO_FINAL,
                TEMPORALIDAD, DIAS_MORA,
                ID_SITUACION, DESC_SITUACION, ID_SITUACION_CIE, DESC_SITUACION_CIE,
                TIPO_NOMBRAMIENTO,
                STATUS_GESTION, MOTIVO_NO_COBRO, DICTAMINACION,
                NUMERO_GESTIONES, FECHA_PROMESA,
                PRIMERA_ORDEN, REACTIVACION, CANCELACION,
                PRECIERRE, PRECIERRE_1, PRECIERRE_2, GEOLOCALIZACION,
                FECHA_CARGA, FECHA_ACTUALIZACION
            )
            SELECT
                REGION, DIVISION, ZONA, RUTA, ID_COBRADOR,
                NO_DAMA, DIGITO_DAMA, NOMBRE_COMPLETO,
                DIRECCION_COMPLETA, COLONIA, CODIGO_POSTAL, POBLACION, ESTADO,
                TELEFONO_CASA, TELEFONO_CELULAR,
                CAMPANA_SALDO, FECHA_FACTURA, FECHA_INICIAL_VIGENCIA, FECHA_FINAL_VIGENCIA,
                SEGMENTO, ESTADO_PROCESO,
                SALDO_DAMA, PAGOS_DAMA, SALDO_ACTUALIZADO, SALDO_FINAL,
                TEMPORALIDAD, DIAS_MORA,
                ID_SITUACION, DESC_SITUACION, ID_SITUACION_CIE, DESC_SITUACION_CIE,
                TIPO_NOMBRAMIENTO,
                STATUS_GESTION, MOTIVO_NO_COBRO, DICTAMINACION,
                NUMERO_GESTIONES, FECHA_PROMESA,
                PRIMERA_ORDEN, REACTIVACION, CANCELACION,
                PRECIERRE, PRECIERRE_1, PRECIERRE_2, GEOLOCALIZACION,
                FECHA_CARGA, FECHA_ACTUALIZACION
            FROM #BASE;

            SET @reg_consolidados = @@ROWCOUNT;

        COMMIT TRANSACTION;

        /* registros con incidencia (rechazos + advertencias de esta corrida) */
        SELECT @reg_con_error = COUNT(*)
        FROM dbo.AUDITORIA_RECHAZOS
        WHERE ID_EJECUCION = @id_ejecucion;

        /* ---- Cerrar bitacora: EXITO ---- */
        UPDATE dbo.BITACORA_EJECUCION
        SET FECHA_FIN        = SYSDATETIME(),
            ESTATUS          = 'EXITO',
            REG_PROCESADOS   = @reg_procesados,
            REG_CONSOLIDADOS = @reg_consolidados,
            REG_CON_ERROR    = @reg_con_error,
            MENSAJE          = CONCAT('Proceso completado. Consolidados=', @reg_consolidados,
                                      ', Incidencias=', @reg_con_error, '.')
        WHERE ID_EJECUCION = @id_ejecucion;

        IF @debug = 1
            SELECT * FROM dbo.BITACORA_EJECUCION WHERE ID_EJECUCION = @id_ejecucion;

    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;

        INSERT INTO dbo.BITACORA_ERRORES
            (ID_EJECUCION, PASO, ERROR_NUMBER, ERROR_SEVERITY, ERROR_LINE, ERROR_MENSAJE)
        VALUES
            (@id_ejecucion, @paso, ERROR_NUMBER(), ERROR_SEVERITY(),
             ERROR_LINE(), ERROR_MESSAGE());

        UPDATE dbo.BITACORA_EJECUCION
        SET FECHA_FIN = SYSDATETIME(),
            ESTATUS   = 'ERROR',
            REG_PROCESADOS = @reg_procesados,
            MENSAJE   = CONCAT('ERROR en ', @paso, ': ', ERROR_MESSAGE())
        WHERE ID_EJECUCION = @id_ejecucion;

        THROW;  -- propaga el error al job / cliente
    END CATCH
END
GO

PRINT 'Procedimiento dbo.sp_construir_base_maestra creado correctamente.';
GO
