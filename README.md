# AI Document Analyzer

https://github.com/user-attachments/assets/3fe36e15-da09-48a9-96b8-990529fea1d8

Full-stack application for ingesting documents, extracting page text and metadata, and answering governed questions through Oracle Autonomous Database, OCI Object Storage, and OCI Generative AI.

## Docker

The container serves the static frontend through `nginx`, the FastAPI backend through `uvicorn`, and the internal API proxy under `/api`.

```bash
docker run -d \
  --name ai-document-analyzer \
  -p 8080:80 \
  -v ai_document_analyzer_data:/app/apps/backend/data \
  -v ai_document_analyzer_wallet:/app/apps/backend/wallet \
  -v ai_document_analyzer_keys:/app/apps/backend/keys \
  -v ai_document_analyzer_logs:/app/apps/backend/logs \
  ghcr.io/jgangini/ai-document-analyzer:v1.0.0
```

Then open `http://localhost:8080`.

## CloudTechNext

The repository follows the same deployment shape as `select-ai-analyzer`: the `Dockerfile` lives at the repository root, the frontend lives in `apps/frontend`, the backend lives in `apps/backend`, nginx configuration lives in `docker/`, and `/api/health` exposes the health check.

CloudTechNext can clone `https://github.com/jgangini/ai-document-analyzer.git`, build the image from the repository root, and mount persistent volumes for `data`, `wallet`, `keys`, and `logs`.

## Wizard

1. Upload `wallet.zip`.
2. Select the `tnsnames.ora` alias.
3. Test the Oracle Autonomous Database connection.
4. Run the SQL installation and create the administrator user.
5. Upload the OCI `key.pem` file.
6. Save the OCI API key, Object Storage, and Generative AI configuration.
7. Test Object Storage and Generative AI and complete setup.

## Runtime

- `POST /api/files/upload`: uploads document files for preparation.
- `POST /api/files/prepare`: creates the ingestion plan for uploaded documents.
- `POST /api/files/process`: processes one document into pages, markdown, metadata, and embeddings.
- `POST /api/files/process-batch`: processes a batch of prepared documents.
- `POST /api/metadata/upload`: loads CSV metadata and links it to document files.
- `POST /api/questions/ask`: answers document questions with scoped retrieval, citations, evidence, and metadata context.
- `POST /api/questions/ask/stream`: streams the same document QA flow.

## Test Data

The public image does not ship with real documents, wallets, keys, or metadata. After completing the wizard, upload PDF files or document archives from the UI. Optional CSV metadata can be loaded through the metadata panel or through `POST /api/metadata/upload`.

Runtime artifacts are stored in the mounted `data`, `wallet`, `keys`, and `logs` volumes.

## Local Development

```powershell
.\scripts\dev.ps1
```

- Backend: `http://127.0.0.1:8012/`
- Frontend: `http://localhost:5173/`

To reinstall frontend dependencies:

```powershell
.\scripts\dev.ps1 -InstallFrontendDeps
```

## Verification

```powershell
.\scripts\check-project.ps1
```

The script validates the FastAPI import and builds the frontend.

## License

This project is licensed under the [MIT License](LICENSE).

AI Document Analyzer is an independent project and is not an official Oracle product. It is not affiliated with, endorsed by, or sponsored by Oracle Corporation. Oracle, OCI, and related marks are trademarks or registered trademarks of Oracle and/or its affiliates. Third-party trademarks, logos, service names, and assets remain the property of their respective owners.

