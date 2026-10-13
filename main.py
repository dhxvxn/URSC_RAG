import os
import glob
import json
import hashlib
import io
import pymupdf
import easyocr
import docx
import pandas as pd
import uvicorn
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse
from typing import List
import httpx
import numpy as np

app = FastAPI(title="Offline Multi-Format QA API")
reader = easyocr.Reader(['en']) 
OLLAMA_URL = "http://localhost:11434/api/chat"

# --- CACHING SETUP ---
CACHE_DIR = "doc_cache"
REGISTRY_FILE = os.path.join(CACHE_DIR, "registry.json")
os.makedirs(CACHE_DIR, exist_ok=True)

def load_registry() -> dict:
    if os.path.exists(REGISTRY_FILE):
        with open(REGISTRY_FILE, "r") as f: return json.load(f)
    return {}

def save_registry(registry: dict):
    with open(REGISTRY_FILE, "w") as f: json.dump(registry, f, indent=4)

def get_upload_hash(file_bytes: bytes) -> str:
    return hashlib.md5(file_bytes).hexdigest()

# --- TEXT EXTRACTION ---
def extract_text_from_pdf(file_bytes: bytes) -> str:
    doc = pymupdf.open(stream=file_bytes, filetype="pdf")
    extracted_text = ""
    for page in doc:
        text = page.get_text().strip()
        if text: extracted_text += text + "\n"
        else:
            pix = page.get_pixmap()
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
            ocr_result = reader.readtext(img, detail=0)
            extracted_text += " ".join(ocr_result) + "\n"
    return extracted_text

def extract_text_from_docx(file_bytes: bytes) -> str:
    doc = docx.Document(io.BytesIO(file_bytes))
    return "\n".join([para.text for para in doc.paragraphs if para.text.strip()])

def extract_text_from_excel(file_bytes: bytes) -> str:
    sheets = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None)
    extracted_text = ""
    for sheet_name, df in sheets.items():
        extracted_text += f"\n--- Excel Sheet: {sheet_name} ---\n"
        extracted_text += df.to_string(index=False) + "\n"
    return extracted_text

async def query_ollama(context: str, question: str) -> str:
    payload = {
        "model": "llama3",
        "messages": [
            {"role": "system", "content": "You are a highly intelligent analytical assistant. Provide a highly detailed, comprehensive, and thorough answer based ONLY on the provided document context. Explain your reasoning fully and do not give brief summaries."},
            {"role": "user", "content": f"Context:\n{context[:7000]}\n\nQuestion: {question}"}
        ],
        "stream": False
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(OLLAMA_URL, json=payload, timeout=None)
        return response.json().get("message", {}).get("content", "").strip()

# --- WEB INTERFACE ---
@app.get("/", response_class=HTMLResponse)
async def get_web_interface():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Offline Multi-Document QA System</title>
        <style>
            body { font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; background-color: #f4f7f6; }
            .container { background: white; padding: 30px; border-radius: 10px; box-shadow: 0px 4px 10px rgba(0,0,0,0.1); }
            input[type="text"], input[type="file"] { width: 100%; padding: 10px; margin: 10px 0; border: 1px solid #ccc; border-radius: 5px; box-sizing: border-box; }
            button { background-color: #0056b3; color: white; padding: 12px 20px; border: none; border-radius: 5px; cursor: pointer; width: 100%; font-size: 16px;}
            #result { margin-top: 20px; padding: 15px; background: #e8f5e9; border-radius: 5px; display: none; white-space: pre-wrap; }
        </style>
    </head>
    <body>
        <div class="container">
            <h2>Offline Document QA (PDF, Word, Excel)</h2>
            <form id="uploadForm">
                <label><b>1. Select a Folder:</b></label><br>
                <input type="file" id="folderInput" name="files" webkitdirectory directory multiple required>
                <label><b>2. Ask your question:</b></label><br>
                <input type="text" id="questionInput" name="question" required>
                <button type="submit">Scan Folder & Ask</button>
            </form>
            <div id="result"></div>
        </div>
        <script>
            document.getElementById('uploadForm').onsubmit = async function(e) {
                e.preventDefault();
                let resultDiv = document.getElementById('result');
                resultDiv.style.display = 'block';
                resultDiv.innerHTML = "<i>Scanning documents... Please wait.</i>";
                
                let formData = new FormData();
                let files = document.getElementById('folderInput').files;
                let validExtensions = ['.pdf', '.docx', '.xlsx', '.xls'];
                
                for(let i=0; i<files.length; i++) {
                    let fileName = files[i].name.toLowerCase();
                    if(validExtensions.some(ext => fileName.endsWith(ext))) {
                        formData.append('files', files[i]);
                    }
                }
                formData.append('question', document.getElementById('questionInput').value);

                let response = await fetch('/api/qa/upload_folder', { method: 'POST', body: formData });
                let data = await response.json();
                resultDiv.innerHTML = "<b>AI Answer:</b><br>" + data.answer + "<br><br><b>Documents Read:</b><br>" + data.files_used.join("<br>");
            };
        </script>
    </body>
    </html>
    """

# --- BACKEND ROUTER ---
@app.post("/api/qa/upload_folder")
async def process_html_folder_upload(question: str = Form(...), files: List[UploadFile] = File(...)):
    registry = load_registry()
    combined_context = ""
    processed_files = []
    
    for file in files:
        ext = os.path.splitext(file.filename)[1].lower()
        file_bytes = await file.read()
        file_hash = get_upload_hash(file_bytes)
        cache_file_path = os.path.join(CACHE_DIR, f"{file_hash}.txt")
        
        if os.path.exists(cache_file_path):
            with open(cache_file_path, "r", encoding="utf-8") as f: text = f.read()
        else:
            try:
                if ext == ".pdf": text = extract_text_from_pdf(file_bytes)
                elif ext == ".docx": text = extract_text_from_docx(file_bytes)
                elif ext in [".xlsx", ".xls"]: text = extract_text_from_excel(file_bytes)
                else: continue
                with open(cache_file_path, "w", encoding="utf-8") as f: f.write(text)
                registry[file_hash] = {"name": file.filename}
            except Exception: continue
            
        combined_context += f"\n--- Source: {file.filename} ---\n" + text
        processed_files.append(file.filename)
        
    save_registry(registry)
    if not combined_context: return {"files_used": [], "answer": "No valid files found."}
    answer = await query_ollama(combined_context, question)
    return {"files_used": processed_files, "answer": answer}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)