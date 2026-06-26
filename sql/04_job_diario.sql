/* =====================================================================
   PROYECTO : Base Maestra de Cobranza
   ARCHIVO  : 04_job_diario.sql
   OBJETIVO : Crear el Job de SQL Server Agent para ejecutar la
              construccion diaria de BASE_MAESTRA_COBRANZA.
   MOTOR    : SQL Server (T-SQL) + SQL Server Agent

   PARAMETROS A AJUSTAR ANTES DE EJECUTAR:
     @nombre_bd    -> nombre de la base de datos destino
     @hora_inicio  -> hora de ejecucion (formato HHMMSS, default 06:00:00)
   ===================================================================== */

USE msdb;
GO

DECLARE @nombre_bd   SYSNAME = N'CRZ_COBRANZA';   -- << AJUSTAR
DECLARE @hora_inicio INT     = 060000;            -- 06:00:00
DECLARE @job_name    SYSNAME = N'JOB_BASE_MAESTRA_COBRANZA_DIARIO';

/* Eliminar job previo si existe (idempotente) */
IF EXISTS (SELECT 1 FROM msdb.dbo.sysjobs WHERE name = @job_name)
    EXEC msdb.dbo.sp_delete_job @job_name = @job_name, @delete_unused_schedule = 1;

EXEC msdb.dbo.sp_add_job
     @job_name   = @job_name,
     @enabled    = 1,
     @description = N'Construccion diaria de la Base Maestra de Cobranza.';

EXEC msdb.dbo.sp_add_jobstep
     @job_name       = @job_name,
     @step_name      = N'Construir BASE_MAESTRA_COBRANZA',
     @subsystem      = N'TSQL',
     @database_name  = @nombre_bd,
     @command        = N'EXEC dbo.sp_construir_base_maestra;',
     @retry_attempts = 2,
     @retry_interval = 5,   -- minutos
     @on_success_action = 1, -- terminar con exito
     @on_fail_action    = 2; -- terminar con error

EXEC msdb.dbo.sp_add_schedule
     @schedule_name = N'SCH_BASE_MAESTRA_DIARIO',
     @freq_type     = 4,            -- diario
     @freq_interval = 1,            -- cada 1 dia
     @active_start_time = @hora_inicio;

EXEC msdb.dbo.sp_attach_schedule
     @job_name      = @job_name,
     @schedule_name = N'SCH_BASE_MAESTRA_DIARIO';

EXEC msdb.dbo.sp_add_jobserver
     @job_name = @job_name;

PRINT 'Job diario creado: ' + @job_name;
GO
