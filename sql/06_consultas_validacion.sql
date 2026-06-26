/* =====================================================================
   PROYECTO : Base Maestra de Cobranza
   ARCHIVO  : 06_consultas_validacion.sql
   OBJETIVO : Consultas de validacion y control de calidad sobre el
              resultado de BASE_MAESTRA_COBRANZA y sus tablas de control.
   MOTOR    : SQL Server (T-SQL)
   ===================================================================== */

/* 1) Resumen de la ultima ejecucion -------------------------------- */
SELECT TOP 1 *
FROM dbo.BITACORA_EJECUCION
ORDER BY ID_EJECUCION DESC;

/* 2) Validacion: NO_DAMA NO debe tener duplicados ------------------ */
SELECT NO_DAMA, COUNT(*) AS repeticiones
FROM dbo.BASE_MAESTRA_COBRANZA
GROUP BY NO_DAMA
HAVING COUNT(*) > 1;
-- Esperado: 0 filas

/* 3) Distribucion por TEMPORALIDAD --------------------------------- */
SELECT TEMPORALIDAD,
       COUNT(*)            AS cuentas,
       SUM(SALDO_FINAL)    AS saldo_final
FROM dbo.BASE_MAESTRA_COBRANZA
GROUP BY TEMPORALIDAD
ORDER BY MIN(DIAS_MORA);

/* 4) Zonas sin cobrador (advertencias de la ultima corrida) -------- */
SELECT *
FROM dbo.AUDITORIA_RECHAZOS
WHERE MOTIVO = 'ZONA_SIN_COBRADOR'
  AND ID_EJECUCION = (SELECT MAX(ID_EJECUCION) FROM dbo.BITACORA_EJECUCION);

/* 5) Saldos negativos (advertencias) ------------------------------- */
SELECT *
FROM dbo.AUDITORIA_RECHAZOS
WHERE MOTIVO = 'SALDO_NEGATIVO'
  AND ID_EJECUCION = (SELECT MAX(ID_EJECUCION) FROM dbo.BITACORA_EJECUCION);

/* 6) Registros rechazados por duplicado ---------------------------- */
SELECT *
FROM dbo.AUDITORIA_RECHAZOS
WHERE MOTIVO = 'NO_DAMA_DUPLICADO'
  AND ID_EJECUCION = (SELECT MAX(ID_EJECUCION) FROM dbo.BITACORA_EJECUCION);

/* 7) Conteo de incidencias por motivo ------------------------------ */
SELECT MOTIVO, NIVEL, COUNT(*) AS total
FROM dbo.AUDITORIA_RECHAZOS
WHERE ID_EJECUCION = (SELECT MAX(ID_EJECUCION) FROM dbo.BITACORA_EJECUCION)
GROUP BY MOTIVO, NIVEL
ORDER BY total DESC;

/* 8) Bitacora de errores tecnicos ---------------------------------- */
SELECT *
FROM dbo.BITACORA_ERRORES
ORDER BY ID_ERROR DESC;

/* 9) Vista rapida de la base maestra ------------------------------- */
SELECT NO_DAMA, NOMBRE_COMPLETO, ZONA, ID_COBRADOR,
       CAMPANA_SALDO, SALDO_DAMA, PAGOS_DAMA, SALDO_FINAL,
       SALDO_ACTUALIZADO, DIAS_MORA, TEMPORALIDAD,
       NUMERO_GESTIONES, STATUS_GESTION, FECHA_PROMESA
FROM dbo.BASE_MAESTRA_COBRANZA
ORDER BY NO_DAMA;
