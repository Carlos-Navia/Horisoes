# Guia del Proyecto: Auditoria PDF

## 1) Descripcion del proyecto

`AUDITORIA PDF` es una herramienta CLI en Python para validar automaticamente la consistencia entre documentos PDF de facturacion en salud.

El sistema procesa lotes de PDFs por caso, extrae informacion clave (documento del paciente, regimen y codigos CUPS), aplica reglas de negocio y genera resultados en consola, Excel y opcionalmente JSON.

## 2) Reglas que valida el sistema

1. Estructura del lote:
   - Obligatorios: `FEV` y `PDE`.
   - `CRC` se mantiene como archivo permitido, pero no obligatorio.
   - Se permite trabajar con otros adicionales (`HEV`, `HAO`, `PDX`, etc.).
2. CUPS entre factura y autorizacion:
   - Compara codigos/CUPS de `FEV` vs `PDE`.
   - Excepcion: si detecta `COOSALUD`, omite esta comparacion por regla de negocio.
3. Documento del paciente:
   - Toma como referencia el documento extraido de `FEV`.
   - Lo compara contra todos los demas PDFs del lote.
   - Si algun PDF no permite extraer documento, usa el nombre del paciente como segunda coincidencia exacta normalizada.
4. Regimen del paciente:
   - Compara `SUBSIDIADO` o `CONTRIBUTIVO` entre `FEV` y `PDE`.

Un caso queda:
- `APROBADO`: sin errores de procesamiento y todas las reglas en estado OK.
- `RECHAZADO`: si falla alguna regla o hay errores de procesamiento.

## 3) Arquitectura (resumen tecnico)

- `main.py`: punto de entrada CLI (modo unico y modo masivo).
- `auditoria_pdf/extractor.py`: extraccion de texto PDF completo (texto nativo + OCR Tesseract + fallback por render).
- `auditoria_pdf/parsers.py`: parseo de campos por tipo de documento.
- `auditoria_pdf/rules.py`: reglas de negocio desacopladas.
- `auditoria_pdf/service.py`: orquestador del flujo de auditoria.
- `auditoria_pdf/batch.py`: escaneo y ejecucion masiva por carpetas.
- `auditoria_pdf/excel_exporter.py`: generacion de salida Excel consolidada.

## 4) Requisitos para ejecutar

1. Windows con `Python 3.11+`.
2. `Tesseract OCR` instalado.
3. Dependencias Python del archivo `requirements.txt`.

Dependencias actuales:
- `pypdf`
- `Pillow`
- `pytesseract`
- `openpyxl`
- `pymupdf`

## 5) Configuracion en una PC nueva

### Opcion recomendada (rapida)

1. Copiar la carpeta completa del proyecto a la nueva PC.
2. Abrir la carpeta del proyecto.
3. Ejecutar el archivo:
   - `instalar_y_ejecutar_auditoria.bat`

Ese `.bat`:
- crea `.venv` si no existe,
- instala dependencias,
- ejecuta `main.py`,
- permite pasar argumentos (`--root-dir`, `--pdf-dir`, etc.).

### Opcion manual (paso a paso)

En PowerShell, dentro de la carpeta del proyecto:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Si PowerShell bloquea scripts:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## 6) Uso operativo

### Modo masivo (recomendado)

Procesa todas las subcarpetas con PDFs dentro de una carpeta principal:

```powershell
python main.py --root-dir "D:\Casos\CarpetaPrincipal"
```

Tambien puedes ejecutar sin argumentos y el sistema pedira la ruta:

```powershell
python main.py
```

### Modo unico por carpeta

```powershell
python main.py --pdf-dir "D:\Casos\Caso001"
```

### Modo unico por rutas explicitas

```powershell
python main.py `
  --fev "D:\Casos\Caso001\FEV_xxx.pdf" `
  --pde "D:\Casos\Caso001\PDE_xxx.pdf" `
  --crc "D:\Casos\Caso001\CRC_xxx.pdf" `
  --extra "D:\Casos\Caso001\HAO_xxx.pdf"
```

### Argumentos utiles

- `--min-pdfs 2 --max-pdfs 6`: rango permitido por lote.
- `--output-excel "ruta\reporte.xlsx"`: define salida Excel.
- `--output-json "ruta\reporte.json"`: genera salida JSON.
- `--tesseract-cmd "C:\Program Files\Tesseract-OCR\tesseract.exe"`: ruta manual de Tesseract.

## 7) Estructura recomendada de carpetas para modo masivo

```text
D:\Casos\CarpetaPrincipal
  \Caso001
    FEV_....pdf
    PDE_....pdf
    CRC_....pdf
    HAO_....pdf
  \Caso002
    FEV_....pdf
    PDE_....pdf
    CRC_....pdf
    HEV_....pdf
```

Cada carpeta que contenga PDFs se procesa como un caso independiente.

## 8) Salidas del sistema

1. Consola:
   - Estado general (`APROBADO` / `RECHAZADO`).
   - Resultado por regla.
   - Errores detectados.
2. Excel:
   - Modo unico: `.\salidas\reporte_<carpeta_caso>.xlsx` (si no se define ruta).
   - Modo masivo: `<root_dir>\reporte_masivo_<root_dir>.xlsx` (si no se define ruta).
3. JSON (opcional):
   - Reporte detallado por caso con reglas, errores y datos extraidos.

## 9) Recomendaciones operativas

1. Estandarizar nombres por prefijo (`FEV_`, `PDE_`, `CRC_`, etc.).
2. Asegurar calidad de escaneo PDF para mejorar OCR.
3. Usar siempre modo masivo para cierres diarios y modo unico para analisis puntual.
4. Verificar instalacion de Tesseract en nuevas estaciones.
5. Mantener una carpeta de salida/versionado de reportes para trazabilidad.

## 10) Solucion de problemas comunes

1. Error de Tesseract no encontrado:
   - Instalar Tesseract OCR.
   - Ejecutar con `--tesseract-cmd "ruta\tesseract.exe"`.
2. No detecta datos en PDFs:
   - Revisar calidad del PDF (escaneo, rotacion, ruido).
   - Confirmar que sean realmente `.pdf`.
3. Falla por estructura del lote:
   - Confirmar presencia de `FEV` y `PDE`.
   - `CRC` es opcional.
   - Revisar nombres/extensiones si no aparecen en el reporte.

## 11) Formatos HEV documentados (COOSALUD)

Para `HEV` se adicionaron reglas especificas para layouts manuales nuevos de COOSALUD.  
El dato objetivo de documento se busca solo en el campo de identificacion del usuario/paciente.

Formatos soportados:

1. `FICHA DE EDUCACION INDIVIDUAL (FO-GS-ED-12-HS)`
   - Campo objetivo: `Numero de identificacion`.
   - Se prioriza ese campo antes de firmas o bloques de educador.
2. `FORMATO DE DEMANDA INDUCIDA (COOSALUD) (FO-MI-CR-15-HS)`
   - Campo objetivo: `Numero Identificacion` (seccion datos personales del usuario).
   - Se ignoran numeros de celular y datos de firma.

Nota tecnica:
- Si el OCR de HEV queda degradado y no entrega un documento confiable, el sistema usa el documento de referencia de `FEV` del mismo caso para evitar falsos negativos en HEV, dejando trazabilidad en metadata.
