# Offline Notebook Document QA

This project is a private document question-answering system for a lab or secure office. It can run with Docker or as a native Python and Ollama service. It accepts PDF, Word, Excel, and image files, extracts text and OCR content, creates local embeddings once, and stores everything in a persistent local data directory. Questions are scoped to a selected notebook, so a user can keep separate collections such as **Propulsion**, **Mission Reports**, or **Finance**.

The application runs locally with FastAPI and Ollama. After the connected installation is complete, the application, embedding model, OCR model, language model, documents, images, SQLite catalog, and embeddings can run without internet access.

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

With Docker, persistent data is kept in the `rag_data` volume and Ollama model files are kept in `ollama_models`. With native deployment, the same data is stored under the repository's `data/` and `models/` directories. Do not delete these directories.

## Recommended deployment without Docker

For a simple offline installation, use native Python and Ollama. This avoids Docker Desktop, WSL, Hyper-V, and Compose. The FastAPI application runs from a virtual environment, SQLite stores the notebooks and embeddings in `data/`, and the embedding, OCR, and Ollama model files stay under `models/`.

The connected preparation machine and the isolated deployment machine must use the same operating-system family and CPU architecture. Prepare a Windows bundle for Windows or an Ubuntu bundle for Ubuntu. Do not copy a virtual environment between operating systems; create it again from the copied wheel files.

### Native requirements

- Windows 10/11 or Ubuntu 22.04/24.04.
- Python 3.11 or newer from [python.org/downloads](https://www.python.org/downloads/).
- Ollama installed natively from [ollama.com/download](https://ollama.com/download).
- At least 16 GB RAM is recommended. An 8 GB PC can demonstrate text-only questions with `llama3.2:3b`, but image-aware answers with `llava:7b` need more memory.
- Internet access only on the preparation machine for installers, Python packages, model weights, and Ollama models.

### Windows native setup while connected

Install Python and Ollama, then open PowerShell in the project directory:

```powershell
cd "$HOME\URSC_RAG"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup_native.ps1
```

The setup script creates `.venv`, installs `requirements.txt`, and downloads the embedding and EasyOCR weights into `models/`. It does not use Docker or WSL.

Start Ollama in a separate PowerShell window so its model files remain inside the project:

```powershell
cd "$HOME\URSC_RAG"
.\scripts\run_ollama.ps1
```

In a third PowerShell window, download the language models:

```powershell
cd "$HOME\URSC_RAG"
ollama pull llama3.2:3b
ollama pull llava:7b
```

Keep the Ollama window running. Start the application in another window:

```powershell
cd "$HOME\URSC_RAG"
.\scripts\run_native.ps1
```

Check it at [http://127.0.0.1:8000](http://127.0.0.1:8000) and [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health). The first upload creates `data/knowledge.sqlite3`; later uploads of the same bytes are deduplicated and do not create embeddings again.

### Ubuntu native setup while connected

Install Python and Ollama using your organization's approved packages, then run:

```bash
cd ~/URSC_RAG
chmod +x scripts/*.sh
./scripts/setup_native.sh
```

Start Ollama in one terminal:

```bash
cd ~/URSC_RAG
./scripts/run_ollama.sh
```

In a second terminal, download the models:

```bash
cd ~/URSC_RAG
ollama pull llama3.2:3b
ollama pull llava:7b
```

In a third terminal, start FastAPI:

```bash
cd ~/URSC_RAG
./scripts/run_native.sh
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Keep the Ollama and FastAPI terminals running while using the application.

### Prepare a transferable offline bundle

Do this on the connected preparation machine after the native setup succeeds. The wheel files must be prepared separately for Windows and Ubuntu:

```powershell
cd "$HOME\URSC_RAG"
New-Item -ItemType Directory -Force .\offline-bundle\wheels | Out-Null
python -m pip download --only-binary=:all: -r requirements.txt -d .\offline-bundle\wheels
```

On Ubuntu, run the equivalent commands:

```bash
cd ~/URSC_RAG
mkdir -p offline-bundle/wheels
python3 -m pip download --only-binary=:all: -r requirements.txt -d offline-bundle/wheels
```

Copy the following to removable media or an approved internal share:

- The repository source files, including `models/` and the `offline-bundle/` directory.
- The Python installer for the target operating system.
- The native Ollama installer for the target operating system.
- `data/` if already-indexed documents and embeddings should be transferred; otherwise create an empty `data/` directory on the target.

Do not copy `.venv` between computers. It is rebuilt on the target from the local wheel files. Keep the `models/embeddings`, `models/easyocr`, and `models/ollama` directories; they contain the downloaded weights and language models needed offline.

### Install the bundle on an isolated Windows PC

Install Python and Ollama from the transferred installers, copy the project folder to the target PC, and run:

```powershell
cd "$HOME\URSC_RAG"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup_native.ps1 -Offline -BundlePath "$HOME\URSC_RAG\offline-bundle"
```

Start the local Ollama model store and application in two separate PowerShell windows:

```powershell
cd "$HOME\URSC_RAG"
.\scripts\run_ollama.ps1
```

```powershell
cd "$HOME\URSC_RAG"
.\scripts\run_native.ps1
```

No internet connection is required after the installers, wheel files, model directories, and source have been copied. Verify with `curl.exe http://127.0.0.1:8000/health`.

### Install the bundle on an isolated Ubuntu PC

Install Python and Ollama from approved offline packages, copy the project and bundle, and run:

```bash
cd ~/URSC_RAG
chmod +x scripts/*.sh
./scripts/setup_native.sh --offline ./offline-bundle
```

Start Ollama and FastAPI in separate terminals:

```bash
cd ~/URSC_RAG
./scripts/run_ollama.sh
```

```bash
cd ~/URSC_RAG
./scripts/run_native.sh
```

Verify with `curl http://127.0.0.1:8000/health`. Documents, images, notebooks, and embeddings remain in `data/` across restarts. Back up that directory before replacing the computer.

### Native lab-network access

The helper scripts bind FastAPI to `127.0.0.1` by default. To allow trusted lab workstations to connect, set the bind address on the server before starting FastAPI:

Windows PowerShell:

```powershell
$env:RAG_HOST = "0.0.0.0"
.\scripts\run_native.ps1
```

Ubuntu:

```bash
RAG_HOST=0.0.0.0 ./scripts/run_native.sh
```

Allow only the lab subnet through the host firewall, then use `http://SERVER_IP:8000` from a workstation. Keep Ollama on `127.0.0.1:11434`; do not expose it to the network. Add authentication and HTTPS before using the service outside a trusted lab.

### Native troubleshooting

- **`python` is not recognized:** install Python 3.11 or newer and enable “Add Python to PATH”, then open a new terminal.
- **`ollama` is not recognized:** install Ollama and open a new terminal, or add its installation directory to `PATH`.
- **The application cannot connect to Ollama:** make sure `run_ollama` is running and that `ollama list` shows `llama3.2:3b`.
- **Offline pip installation fails:** use a wheel bundle prepared on the same operating system, Python version, and CPU architecture as the target.
- **A model download is attempted while offline:** confirm `models/embeddings`, `models/easyocr`, and `models/ollama` were copied and that the helper scripts set `HF_HUB_OFFLINE` and `TRANSFORMERS_OFFLINE`.
- **Port 8000 is busy:** set another port, for example `RAG_PORT=8001 ./scripts/run_native.sh` on Ubuntu or `$env:RAG_PORT="8001"; .\scripts\run_native.ps1` on Windows.

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

## Windows installation with Docker Desktop

Windows 10/11 can run the same Linux containers through Docker Desktop and WSL2. Internet is needed for Docker Desktop, the first image build, and the model downloads. After that, the stack can run offline.

### 1. Install WSL2

Open **PowerShell as Administrator**:

```powershell
wsl --install
wsl --update
```

Restart Windows when prompted. Open the installed Ubuntu distribution once and create its Linux username and password.

### 2. Install Docker Desktop

In PowerShell:

```powershell
winget install --id Docker.DockerDesktop --exact
```

Start **Docker Desktop** and confirm:

- **Use the WSL 2 based engine** is enabled.
- **Settings → Resources → WSL Integration** is enabled for your Ubuntu distribution.
- Docker Desktop reports **Engine running**.

Verify from PowerShell:

```powershell
docker --version
docker compose version
docker run --rm hello-world
```

### 3. Clone and build the project

Run these commands in PowerShell:

```powershell
git clone https://github.com/dhxvxn/URSC_RAG.git
cd URSC_RAG

docker compose build
docker compose up -d

docker compose exec ollama ollama pull llama3.2:3b
docker compose exec ollama ollama pull llava:7b

docker compose ps
curl.exe http://127.0.0.1:8000/health
```

Open the application at [http://127.0.0.1:8000](http://127.0.0.1:8000) and the API page at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

The default Windows deployment is loopback-only, so other computers cannot connect. The named Docker volumes `ursc_rag_rag_data` and `ursc_rag_ollama_models` persist across Docker Desktop restarts and Windows reboots.

### 4. Run offline

After the image build and both model pulls finish, disconnect Windows from the internet. Start the application later with:

```powershell
cd URSC_RAG
docker compose up -d
```

Do not run `docker compose build` or `ollama pull` on the disconnected machine. Do not run `docker compose down -v`; that removes the document database, embeddings, and uploaded files.

### 5. Optional Windows lab-network access

For a later lab demonstration, create a file named `.env` beside `docker-compose.yml`:

```dotenv
RAG_BIND_ADDRESS=0.0.0.0
```

Restart Docker Compose:

```powershell
docker compose up -d
ipconfig
```

Restrict Windows Firewall to the lab subnet from an Administrator PowerShell:

```powershell
New-NetFirewallRule -DisplayName "Offline Document QA" -Direction Inbound -Protocol TCP -LocalPort 8000 -RemoteAddress 192.168.10.0/24 -Action Allow
```

Lab workstations can then open `http://WINDOWS_SERVER_IP:8000`. Keep port 11434 private; only the FastAPI port should be reachable from the lab.

## Windows installation without WSL (Hyper-V backend)

Use this option when WSL2 is not permitted. Docker Desktop can run this project with its **Hyper-V backend**, which uses Docker's own lightweight Linux virtual machine. The project still needs Linux containers, so Windows containers are not supported for this Compose file.

This option requires Windows 10/11 **Pro, Enterprise, or Education**, a 64-bit processor with hardware virtualization and SLAT, at least 4 GB RAM, and administrator access. Windows Home does not provide the Hyper-V backend; use WSL2 or an Ubuntu virtual machine/server on Windows Home.

### 1. Check Windows and virtualization support

Press `Win + R`, run `winver`, and confirm the Windows edition. Hardware virtualization must be enabled in BIOS/UEFI. If your organization manages the PC, ask IT to enable Hyper-V and permit Docker Desktop.

### 2. Enable Hyper-V and Windows containers

Open **PowerShell as Administrator** and run each command separately:

```powershell
dism /online /enable-feature /featurename:Microsoft-Hyper-V /all /norestart
dism /online /enable-feature /featurename:Containers /all /norestart
```

Restart Windows after the commands finish.

### 3. Install Docker Desktop with Hyper-V

Download Docker Desktop from [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/). During installation, leave the **Use WSL 2 instead of Hyper-V** option unchecked if it is shown.

After installation:

1. Open Docker Desktop and wait for **Engine running**.
2. Open **Settings → General**.
3. Make sure **Use the WSL 2 based engine** is disabled.
4. Select **Apply & Restart**.
5. If Docker is using Windows containers, open the Docker tray menu and select **Switch to Linux containers**.
6. Do not enable WSL Integration; this setup does not use WSL.

Verify the backend from PowerShell:

```powershell
docker --version
docker compose version
docker info --format '{{.OSType}}'
docker run --rm hello-world
```

The `docker info` command must print `linux`. If it prints `windows`, switch Docker Desktop to Linux containers and run the check again.

### 4. Clone and build the project

Run these commands one at a time. The first build needs internet access and can take 20–60 minutes because it installs Python packages and downloads the embedding and OCR model weights:

```powershell
cd "$HOME"
git clone https://github.com/dhxvxn/URSC_RAG.git
cd "$HOME\URSC_RAG"
docker compose config
docker compose --progress=plain build
```

If the repository is already present, skip `git clone` and enter the folder that contains `docker-compose.yml`:

```powershell
cd "$HOME\URSC_RAG"
Get-ChildItem docker-compose.yml
docker compose --progress=plain build
```

Do not run `docker compose build` from `C:\Users\<name>` or another parent folder. Compose must run in the project directory.

### 5. Start the services and download models

```powershell
docker compose up -d
docker compose ps
docker compose exec ollama ollama pull llama3.2:3b
```

For image-aware answers, download the optional vision model while internet is available:

```powershell
docker compose exec ollama ollama pull llava:7b
```

On an 8 GB PC, start with `llama3.2:3b` and add `llava:7b` only if the machine has enough free memory.

Verify the application:

```powershell
curl.exe http://127.0.0.1:8000/health
```

Open the UI at [http://127.0.0.1:8000](http://127.0.0.1:8000) and the API documentation at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). Create a notebook, select a document folder, index the files, and ask a question.

### 6. Run the Hyper-V installation offline

After the image build and model downloads complete, disconnect the PC from the internet. The documents, embeddings, images, and Ollama models are stored in named Docker volumes and survive restarts and reboots:

```powershell
cd "$HOME\URSC_RAG"
docker compose up -d
docker compose ps
```

Do not run `docker compose build` or `ollama pull` while disconnected. Do not run `docker compose down -v`; it deletes the document database, embeddings, and uploaded files.

### 7. Optional access from Windows lab workstations

The default binding accepts connections only from the same PC. To expose the API to a trusted lab subnet, create `.env` beside `docker-compose.yml`:

```dotenv
RAG_BIND_ADDRESS=0.0.0.0
```

Restart the stack and allow only the lab subnet through Windows Firewall from an Administrator PowerShell:

```powershell
cd "$HOME\URSC_RAG"
docker compose up -d
New-NetFirewallRule -DisplayName "Offline Document QA" -Direction Inbound -Protocol TCP -LocalPort 8000 -RemoteAddress 192.168.10.0/24 -Action Allow
ipconfig
```

Workstations can then open `http://WINDOWS_SERVER_IP:8000`. Keep port 11434 private; only port 8000 should be reachable from the lab. Add authentication and HTTPS before using the service outside a trusted network.

### Hyper-V troubleshooting

- **Hyper-V is unavailable:** confirm the Windows edition is Pro, Enterprise, or Education, enable CPU virtualization in BIOS/UEFI, and restart after enabling the features.
- **`docker info` prints `windows`:** switch Docker Desktop to **Linux containers**.
- **`no configuration file provided`:** run `cd "$HOME\URSC_RAG"` before every Compose command and confirm `Get-ChildItem docker-compose.yml` finds the file.
- **The first build appears slow:** this is expected while packages and model weights download. Keep Docker Desktop and internet access active until the build completes.
- **Services are unhealthy:** inspect logs with `docker compose logs --tail=100 rag` and `docker compose logs --tail=100 ollama`.




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
