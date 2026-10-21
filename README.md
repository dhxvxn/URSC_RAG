# Offline Notebook Document QA

This project is a private, Docker-based document question-answering system for a lab or secure office. It accepts PDF, Word, Excel, and image files, extracts text and OCR content, creates local embeddings once, and stores everything in persistent Docker volumes. Questions are scoped to a selected notebook, so a user can keep separate collections such as **Propulsion**, **Mission Reports**, or **Finance**.

The application runs locally with FastAPI and Ollama. After the connected installation is complete, the containers, embedding model, OCR model, language model, documents, images, SQLite catalog, and embeddings can run without internet access.

## What is included

- Persistent notebooks with a separate document collection for each topic or project.
- PDF, DOCX, XLSX, XLS, PNG, JPEG, TIFF, BMP, and WebP ingestion.
- SHA-256 document deduplication. Uploading the same file again links it to the notebook without extracting or embedding it again.
- Incremental indexing. Add another file or folder later and index only new or changed files.
- Local `all-MiniLM-L6-v2` sentence embeddings stored in SQLite BLOBs.
- Cosine-similarity retrieval restricted to the selected notebook.
- PDF page text extraction, scanned-PDF OCR, DOCX/XLSX embedded-image extraction, and image OCR.
- Persistent image storage and source URLs in API responses.
- Optional Ollama vision answering with `llava`; without a vision model, image OCR still participates in retrieval and the image is returned as a source.
- Extractive fallback answers when Ollama is stopped or unavailable.
- FastAPI web UI, Swagger API at `/docs`, and MCP tools for notebook operations.
- No cloud API is needed at runtime.

The persistent data is kept in the Docker volume `rag_data`; Ollama model files are kept in `ollama_models`. Removing containers does not remove these volumes.

## Connected installation (internet available once)

The following procedure is for an Ubuntu 22.04/24.04 machine that will become the lab server. Internet is required only for Docker installation, the first image build, and the initial model downloads. After these steps, the server can be disconnected from the internet.

Install Docker Engine and the Compose plugin from Docker's Ubuntu repository:

```bash
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

Log out and back in once after adding yourself to the `docker` group. Verify the installation:

```bash
docker --version
docker compose version
docker run --rm hello-world
```

Then clone the repository:

```bash
git clone https://github.com/dhxvxn/URSC_RAG.git
cd URSC_RAG
```

Build the application image while internet is available:

```bash
docker compose build
```

Start both services:

```bash
docker compose up -d
```

Download the local language models into the persistent Ollama volume:

```bash
docker compose exec ollama ollama pull llama3.2:3b
docker compose exec ollama ollama pull llava:7b
```

`llava:7b` is used when a retrieved source includes images. If the server cannot hold that model, set `OLLAMA_VISION_MODEL` to another installed vision model in a `.env` file. The application still indexes image OCR when no vision model is available.

Check the services:

```bash
docker compose ps
curl http://127.0.0.1:8000/health
```

Open the user interface at [http://127.0.0.1:8000](http://127.0.0.1:8000) and the API documentation at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

### Complete first-install sequence

For a clean Ubuntu PC, the full order is:

```bash
# 1. Install Docker and Compose (internet required for this step).
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"

# Start a new login session after the usermod command, then verify Docker.
docker --version
docker compose version
docker run --rm hello-world

# 2. Download this project (internet required for this step).
git clone https://github.com/dhxvxn/URSC_RAG.git
cd URSC_RAG

# 3. Build the application image. This downloads Python packages and embeds
#    the sentence-embedding and EasyOCR weights into the image.
docker compose build

# 4. Start the private API and the local Ollama service.
docker compose up -d

# 5. Download the language models into the persistent Ollama volume.
docker compose exec ollama ollama pull llama3.2:3b
docker compose exec ollama ollama pull llava:7b

# 6. Verify the complete deployment.
docker compose ps
docker compose exec ollama ollama list
curl http://127.0.0.1:8000/health
```

After the health check succeeds, open `http://127.0.0.1:8000`, create a notebook, select a folder, and click **Index selected files**. The service is now ready to run without internet. To start it later, only run `docker compose up -d`; do not rebuild or pull models on the isolated machine.

To update an existing connected installation:

```bash
cd URSC_RAG
git pull --ff-only origin main
docker compose build
docker compose up -d
```


## First demonstration on one Ubuntu PC

Use an SSD and at least 16 GB RAM for a comfortable demonstration. The text model is kept warm in Ollama, and the embedding model is loaded once when the API starts. The default Compose binding is loopback-only, so another machine cannot reach the service:

```bash
docker compose up -d
docker compose ps
curl http://127.0.0.1:8000/health
```

Use [http://127.0.0.1:8000](http://127.0.0.1:8000) to create a notebook, select a folder, index it, and ask questions. A later upload of the same bytes returns `cached`; new or changed files are embedded once. The API response includes `timings_ms.retrieval` and `timings_ms.answer`, which makes the retrieval and model-generation delays visible during the demonstration.

The fast path is deliberately local: the embedding matrix for a notebook is loaded into memory after the first query, SQLite FTS5 handles exact terms, and reciprocal-rank fusion combines lexical and semantic matches. Ollama receives only the top passages, uses a bounded context, and keeps the model loaded. Retrieval should therefore be much faster than answer generation; the language model is normally the longer part of a response.

For an isolated PC, block inbound traffic and leave the default loopback binding in place:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw enable
```

## Later connection to lab workstations

When the single-PC demonstration is approved, bind the API to the lab interface and keep Ollama private. Create a `.env` file beside `docker-compose.yml`:

```dotenv
RAG_BIND_ADDRESS=0.0.0.0
```

Restart the stack and allow only the lab subnet through the server firewall:

```bash
docker compose up -d
sudo ufw allow from 192.168.10.0/24 to any port 8000 proto tcp
```

Workstations then use `http://SERVER_IP:8000`; they never receive the document store or Ollama port. Add HTTPS and user authentication at a reverse proxy before using the service outside a trusted lab subnet.

## Running fully offline

The application image contains the embedding and EasyOCR weights. The Ollama models are in the `ollama_models` Docker volume. Once `docker compose build` and both `ollama pull` commands have completed, disconnect the server from the internet and start normally:

```bash
docker compose up -d
```

To move the prepared deployment to an isolated machine, export the images and volumes while the connected machine is stopped:

```bash
docker compose down
mkdir -p offline-bundle
docker image ls
# Use the exact RAG image name shown by the previous command.
docker save -o offline-bundle/ollama-image.tar ollama/ollama:latest
docker save -o offline-bundle/rag-image.tar ursc_rag-rag:latest
docker run --rm -v ursc_rag_ollama_models:/source -v "$PWD/offline-bundle:/backup" alpine \
  tar czf /backup/ollama-models.tar.gz -C /source .
docker run --rm -v ursc_rag_rag_data:/source -v "$PWD/offline-bundle:/backup" alpine \
  tar czf /backup/rag-data.tar.gz -C /source .
```

Copy `offline-bundle/` and the repository to the isolated machine. Load the images and restore the volumes:

```bash
docker load -i offline-bundle/ollama-image.tar
docker load -i offline-bundle/rag-image.tar
docker volume create ursc_rag_ollama_models
docker volume create ursc_rag_rag_data
docker run --rm -v ursc_rag_ollama_models:/target -v "$PWD/offline-bundle:/backup" alpine \
  tar xzf /backup/ollama-models.tar.gz -C /target
docker run --rm -v ursc_rag_rag_data:/target -v "$PWD/offline-bundle:/backup" alpine \
  tar xzf /backup/rag-data.tar.gz -C /target
docker compose up -d
```

Do not run `docker compose build` on the isolated machine unless all build layers and package caches have already been transferred. The normal offline operation is `docker compose up -d` using the loaded image.

## Persistent embeddings and later uploads

The first successful upload performs extraction/OCR, creates chunks, generates embeddings, writes them to `/data/knowledge.sqlite3`, and stores the original files and extracted images under `/data`. `/data` is mounted from the named Docker volume `ursc_rag_rag_data`, so the catalog and embeddings survive:

- `docker compose restart`
- `docker compose down` followed by `docker compose up -d`
- application image rebuilds
- host reboots

The same file is identified by its SHA-256 hash. Uploading it again returns `cached`, links it to the selected notebook, and does not extract or embed it again. A new file is indexed once; a modified file has a new hash and is indexed as a new version. Questions use the saved embeddings and never require the source files to be uploaded again.

Do **not** run `docker compose down -v` unless you intentionally want to delete the document catalog, embeddings, and uploaded files. Back up `ursc_rag_rag_data` before moving or reinstalling the server. The Ollama model volume `ursc_rag_ollama_models` is separate and must also be backed up for a completely offline restore.

To confirm that the persistent data volume exists:

```bash
docker volume inspect ursc_rag_rag_data
docker compose exec rag ls -lh /data/knowledge.sqlite3
```

## Notebook workflow

1. Open the web UI.
2. Create a notebook such as `Mission Reports`.
3. Select files or an entire folder and click **Index selected files**.
4. Ask questions while that notebook is selected.
5. Add more files later and index them again. Existing files are reported as `cached`; new or changed files are embedded once.

The database keeps a content hash, so the same document can be linked into several notebooks without duplicate storage or embedding work. A changed document receives a new hash and is indexed as a new version. Documents are never sent to a cloud service.

## API examples

Create a notebook:

```bash
curl -X POST http://127.0.0.1:8000/api/notebooks \
  -H 'Content-Type: application/json' \
  -d '{"name":"Mission Reports"}'
```

Use the returned notebook ID to index files:

```bash
curl -X POST http://127.0.0.1:8000/api/notebooks/NOTEBOOK_ID/documents \
  -F 'files=@/srv/documents/report.pdf' \
  -F 'files=@/srv/documents/figures.png'
```

Ask a question without uploading the files again:

```bash
curl -X POST http://127.0.0.1:8000/api/notebooks/NOTEBOOK_ID/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"What is the reported mission lifetime?","top_k":8}'
```

The response contains the answer, matched passages, page numbers, and image URLs such as `/media/images/...`. Open an image through the API host when reviewing evidence.

## Lab network access

When `RAG_BIND_ADDRESS=0.0.0.0` is enabled, port `8000` is published for the lab API and web UI. Ollama remains bound only to `127.0.0.1` on the host and is not exposed to lab clients. Restrict port 8000 to the lab subnet with the host firewall:

```bash
sudo ufw allow from 192.168.10.0/24 to any port 8000 proto tcp
sudo ufw enable
```

Clients can then open `http://SERVER_IP:8000` and `http://SERVER_IP:8000/docs`. The current application does not provide user authentication; keep it on a trusted subnet or place it behind an authenticated reverse proxy before exposing it beyond the lab.

## MCP

The MCP adapter uses the same persistent database and embeddings as the API:

```bash
docker compose exec rag python mcp_server.py
```

For a local MCP client, configure stdio with the Python interpreter in the checkout. The available tools are `list_notebooks`, `create_notebook`, `ingest_folder`, and `ask_notebook`. `ingest_folder` recursively scans supported files and reuses the content-hash index on later runs.

## Storage and backups

Back up both persistent volumes. `rag_data` contains the SQLite catalog, original documents, extracted images, and embeddings. `ollama_models` contains the language models. A backup made while the services are stopped is the simplest consistent backup:

```bash
docker compose down
# export the two volumes using the tar commands in the offline-bundle section
docker compose up -d
```

Protect the backup files because they contain office documents and image extracts.

## Troubleshooting

```bash
docker compose logs -f rag
docker compose logs -f ollama
curl http://127.0.0.1:8000/health
docker compose exec ollama ollama list
```

- If the app reports an embedding-model error, rebuild the image while connected: `docker compose build --no-cache`.
- If image answers fall back to OCR, confirm that `llava:7b` appears in `docker compose exec ollama ollama list` and that `OLLAMA_VISION_MODEL` matches its name.
- If a repeated upload is not marked `cached`, the file bytes changed; this is intentional and creates a new indexed version.
- If the host is low on memory, use a smaller Ollama text or vision model and reduce `top_k`.
