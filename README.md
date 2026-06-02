# AI Document Analyzer

Aplicacion full-stack para cargar, procesar y consultar documentos con Oracle Autonomous Database, OCI Generative AI y un flujo RAG guiado desde una interfaz web.

El proyecto toma como referencia la misma forma de despliegue de [`jgangini/select-ai-analyzer`](https://github.com/jgangini/select-ai-analyzer): Dockerfile en la raiz, frontend en `apps/frontend`, backend en `apps/backend`, proxy `nginx` en `docker/` y API interna publicada bajo `/api`.

## Caracteristicas

- Wizard inicial para configurar Oracle ADB, wallet, credenciales OCI, Object Storage y Generative AI.
- Carga y procesamiento de documentos con catalogo, paginas, markdown, imagenes y embeddings.
- Consulta de documentos mediante chat RAG, citas, evidencia y razonamiento del agente.
- Soporte de metadatos CSV por archivo o archivo comprimido para filtrar y comparar informacion estructurada.
- Conversaciones persistentes, exportacion de chats y panel de mejora/evaluacion.
- Imagen Docker unica con frontend estatico, backend FastAPI y proxy interno.

## Video demo

El video demo del flujo GitHub esta incluido en [`docs/videos/oci-ai-document-analyzer-git.mp4`](docs/videos/oci-ai-document-analyzer-git.mp4).

## Stack

- Frontend: React 18, Vite, TypeScript, Tailwind CSS, React Query.
- Backend: Python 3.11, FastAPI, LangGraph, LangChain OCI, Oracle DB, OCI SDK.
- Runtime: Docker, `nginx`, `uvicorn`, volumenes persistentes para datos, wallet, claves y logs.

## Docker

La imagen publica esta pensada para correr como un solo contenedor. El contenedor sirve:

- frontend estatico por `nginx`
- backend FastAPI por `uvicorn`
- proxy interno en `/api`

```bash
docker run -d \
  --name ai-document-analyzer \
  -p 8080:80 \
  -v ai_document_analyzer_data:/app/apps/backend/data \
  -v ai_document_analyzer_wallet:/app/apps/backend/wallet \
  -v ai_document_analyzer_keys:/app/apps/backend/keys \
  -v ai_document_analyzer_logs:/app/apps/backend/logs \
  ghcr.io/jgangini/ai-document-analyzer:v0.1.0
```

Luego abre `http://localhost:8080` o la IP publica de tu VM en OCI.

### Actualizar version

```bash
docker pull ghcr.io/jgangini/ai-document-analyzer:v0.1.0
docker stop ai-document-analyzer
docker rm ai-document-analyzer
docker run -d \
  --name ai-document-analyzer \
  -p 8080:80 \
  -v ai_document_analyzer_data:/app/apps/backend/data \
  -v ai_document_analyzer_wallet:/app/apps/backend/wallet \
  -v ai_document_analyzer_keys:/app/apps/backend/keys \
  -v ai_document_analyzer_logs:/app/apps/backend/logs \
  ghcr.io/jgangini/ai-document-analyzer:v0.1.0
```

## CloudTechNext / OCI

CloudTechNext puede clonar `https://github.com/jgangini/ai-document-analyzer.git`, construir la imagen desde la raiz del repositorio y montar volumenes persistentes para:

- `/app/apps/backend/data`
- `/app/apps/backend/wallet`
- `/app/apps/backend/keys`
- `/app/apps/backend/logs`

La imagen no incluye credenciales, wallet, claves privadas ni datos reales. El wizard guarda la configuracion runtime en los volumenes montados para conservar el setup entre reinicios.

## Wizard inicial

En el primer arranque, completa el setup desde la UI:

1. Sube el `wallet.zip`.
2. Selecciona el alias del `tnsnames.ora`.
3. Prueba y guarda la conexion con Oracle ADB.
4. Ejecuta la instalacion SQL.
5. Sube el `key.pem` de OCI.
6. Prueba OCI, Object Storage y Generative AI.
7. Guarda la configuracion y completa el setup.

Las operaciones de runtime quedan bloqueadas hasta completar este wizard.

## Runtime API

Todas las rutas se publican bajo `/api`:

| Ruta | Uso |
| --- | --- |
| `GET /api/health` | Health check del contenedor y del backend. |
| `POST /api/files/upload` | Carga archivos al area temporal del backend. |
| `POST /api/files/prepare` | Genera el plan de preparacion antes de procesar documentos. |
| `POST /api/files/process` | Procesa un documento y crea el job de ingesta. |
| `POST /api/files/process-batch` | Procesa varios documentos en lote. |
| `GET /api/files` | Lista documentos disponibles. |
| `GET /api/files/{file_id}/markdown` | Devuelve el markdown extraido de un documento. |
| `POST /api/metadata/upload` | Carga metadatos CSV para el catalogo. |
| `POST /api/questions/ask` | Ejecuta una pregunta RAG sobre documentos y metadatos. |
| `POST /api/questions/ask/stream` | Ejecuta una pregunta RAG con streaming. |
| `GET /api/chats` | Lista conversaciones persistentes. |
| `GET /api/improvement/overview` | Consulta metricas y trazas de mejora. |

## Desarrollo local

### Requisitos

- Windows con PowerShell.
- Node.js y npm.
- Python 3.11.
- Dependencias del frontend instaladas en `apps/frontend`.

Para preparar el backend por primera vez:

```powershell
py -3.11 -m venv apps\backend\.venv
.\apps\backend\.venv\Scripts\python.exe -m pip install -r apps\backend\requirements.txt
```

Para instalar dependencias del frontend:

```powershell
Push-Location apps\frontend
npm install
Pop-Location
```

### Levantar el proyecto

Desde la raiz del repositorio:

```powershell
.\scripts\dev.ps1
```

El script abre:

- Backend FastAPI: `http://127.0.0.1:8012/`
- Frontend Vite: `http://localhost:5173/`

En Cursor o VS Code, usa la tarea `Dev: Start Project` desde `Tasks: Run Task`. Si necesitas reinstalar dependencias del frontend:

```powershell
.\scripts\dev.ps1 -InstallFrontendDeps
```

Si prefieres levantar el backend sin reload:

```powershell
.\scripts\dev.ps1 -NoReload
```

Si quieres forzar ventanas externas incluso desde Cursor o VS Code:

```powershell
.\scripts\dev.ps1 -ExternalWindows
```

## Verificacion

```powershell
.\scripts\check-project.ps1
```

La validacion:

- importa el backend FastAPI
- compila el frontend con `npm run build`

Si el proyecto tiene Sentrux instalado, tambien puedes validar reglas estructurales:

```powershell
sentrux check .
```

## Estructura

```text
apps/
  backend/        API FastAPI, servicios, RAG, ingesta y SQL bootstrap
  frontend/       UI React/Vite
docker/           nginx y arranque del contenedor
scripts/          utilidades de desarrollo y verificacion
.sentrux/         reglas de arquitectura del repositorio
Dockerfile        build multi-stage para frontend, backend y runtime
```

## Licencia

Este proyecto esta licenciado bajo la licencia MIT. Consulta [`LICENSE`](LICENSE).
