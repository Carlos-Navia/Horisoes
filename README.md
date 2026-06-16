# Auditoria PDF OOP

Proyecto en Python orientado a objetos para auditar consistencia entre documentos PDF de facturacion en salud.

## Objetivo
Validar automaticamente:

1. Codigo/CUPS en factura (`FEV`) vs codigo/CUPS en autorizacion (`PDE`).
   - `COOSALUD`: esta comparacion se omite por regla de negocio.
   - `NUEVA_EPS`: esta comparacion es obligatoria.
   - `SANITAS`: esta comparacion es obligatoria.
2. Identidad del paciente en `FEV` como referencia y comparacion contra todos los demas PDFs del lote.
   - La identidad pasa si coincide exactamente el documento del paciente.
   - Si el documento no esta disponible en algun PDF, tambien puede pasar por nombre completo exacto normalizado.
3. Regimen del paciente entre `FEV` y `PDE`.
   - `NUEVA_EPS`: en `PDE`, si `Semanas Cotizadas` esta vacio -> `SUBSIDIADO`; si tiene valor -> `CONTRIBUTIVO`.
4. Estructura del lote:
   - Minimo 2 y maximo 6 PDFs.
   - Obligatorio: `FEV` + al menos otro PDF permitido.
   - Opcionales: `PDE`, `CRC`, `HEV`, `HAO`, `PDX` u otro prefijo.

## Arquitectura
- `auditoria_pdf/extractor.py`: extraccion hibrida PDF (texto nativo + OCR con Tesseract) leyendo el documento completo por defecto.
- `auditoria_pdf/parsers.py`: parsers OOP por tipo de documento.
- `auditoria_pdf/rules.py`: reglas de negocio desacopladas.
- `auditoria_pdf/service.py`: orquestacion del flujo completo.
- `auditoria_pdf/domain.py`: modelos de dominio y reporte.
- `main.py`: CLI para ejecutar auditorias.

## Requisitos
- Python 3.11+.
- Tesseract OCR instalado en Windows.
  - Ruta tipica: `C:\Program Files\Tesseract-OCR\tesseract.exe`
- Dependencias Python en `requirements.txt`.
  - Incluye `pymupdf` para OCR robusto por pagina completa en PDFs dificiles.

## Instalacion
```powershell
python -m pip install -r requirements.txt
```

## Uso
### Seleccionar EPS (nuevo)
El flujo de auditoria ahora se ejecuta por perfil EPS independiente:
- `coosalud`
- `nueva_eps`
- `sanitas`

Si no se indica `--eps`, el programa pregunta antes de ejecutar.

### Opcion 1: modo masivo (recomendado)
Si no envias parametros, el script solicita por `input` la ruta de la carpeta principal y procesa recursivamente todas las subcarpetas que tengan PDFs.
```powershell
python main.py --eps coosalud
```

Tambien puedes pasar la carpeta principal por argumento:
```powershell
python main.py --eps nueva_eps --root-dir "G:\ruta\carpeta\principal"
```

### Opcion 2: carpeta de un solo caso
```powershell
python main.py --eps nueva_eps --pdf-dir "G:\ruta\carpeta\caso"
```

### Opcion 3: rutas explicitas
```powershell
python main.py `
  --eps coosalud `
  --fev "G:\...\FEV_901011395_FVEA6202.pdf" `
  --pde "G:\...\PDE_901011395_FVEA6202.pdf" `
  --crc "G:\...\CRC_901011395_FVEA6202.pdf" `
  --extra "G:\...\HAO_901011395_FVEA6202.pdf"
```

### Varios adicionales
```powershell
python main.py `
  --eps nueva_eps `
  --fev "G:\...\FEV_901011395_FVEP8177.pdf" `
  --pde "G:\...\PDE_901011395_FVEP8177.pdf" `
  --crc "G:\...\CRC_901011395_FVEP8177.pdf" `
  --extra "G:\...\HEV_901011395_FVEP8177.pdf" "G:\...\PDX_901011395_FVEP8177.pdf"
```

### Guardar salida JSON
```powershell
python main.py --eps coosalud --pdf-dir "G:\...\FVEP8177" --output-json ".\salidas\reporte_fvep8177.json"
```

### Salida Excel
El programa genera un Excel automaticamente:
- Modo masivo: `<carpeta_principal>\reporte_masivo_<carpeta_principal>.xlsx`
- Modo unico: `.\salidas\reporte_<carpeta_caso>.xlsx`

Tambien puedes definir ruta:
```powershell
python main.py --eps nueva_eps --pdf-dir "G:\...\FVEP8177" --output-excel ".\salidas\auditoria_fvep8177.xlsx"
```

Encabezados del Excel:
- `carpeta`
- `tipo_archivo`
- `documento_referencia`
- `documentos_detectados`
- `estado_documento`
- `nombre_referencia`
- `nombres_detectados`
- `estado_nombre`
- `regimen_factura`
- `regimen_detectado`
- `estado_regimen`
- `error`

### Ajustar minimo y maximo de PDFs del lote
```powershell
python main.py --eps coosalud --pdf-dir "G:\...\FVEP8177" --min-pdfs 2 --max-pdfs 10
```

### Si Tesseract no se detecta automaticamente
```powershell
python main.py --eps coosalud --pdf-dir "G:\...\FVEP8177" --tesseract-cmd "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

### Mostrar mensajes tecnicos de MuPDF (opcional)
Por defecto, la aplicacion oculta warnings/errores de formato de MuPDF en consola
(por ejemplo: `No common ancestor in structure tree`) para evitar ruido cuando el
PDF es legible pero tiene metadatos dañados.

Si quieres verlos otra vez para diagnostico:
```powershell
$env:AUDITORIA_PDF_SHOW_MUPDF_MESSAGES="1"
python main.py --eps coosalud --root-dir "G:\...\FRAMINGHAM"
```

## Convencion de tipos
- `FEV_` -> obligatorio (factura)
- `PDE_` -> opcional (autorizacion)
- `CRC_` -> permitido (no obligatorio)
- `HEV_` -> adicional
- Cualquier otro prefijo (`HAO_`, `PDX_`, etc.) -> adicional
