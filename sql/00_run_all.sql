/* =====================================================================
   PROYECTO : Base Maestra de Cobranza
   ARCHIVO  : 00_run_all.sql
   OBJETIVO : Orquestador de despliegue. Ejecuta en orden los scripts de
              creacion de objetos. Pensado para sqlcmd con :r .

   USO (sqlcmd) -- IMPORTANTE: ejecutar DESDE la carpeta sql/ para que los
   includes ":r" relativos se resuelvan correctamente:
     cd sql
     sqlcmd -S <servidor> -d <base> -E -i 00_run_all.sql

   NOTA: si no usa sqlcmd, ejecute los archivos en este mismo orden
         manualmente desde SSMS / Azure Data Studio.
   ===================================================================== */
:on error exit

PRINT '== 01 Tablas fuente ==';
:r 01_tablas_fuente.sql

PRINT '== 02 Tabla maestra y control ==';
:r 02_tabla_maestra_y_control.sql

PRINT '== 03 Procedimiento de construccion ==';
:r 03_sp_construir_base_maestra.sql

PRINT '== Despliegue de objetos completado ==';
GO
