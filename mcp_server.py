import os
import json
import hashlib
import io
import pymupdf
import easyocr
import docx
import pandas as pd
import httpx
import numpy as np
from mcp.server.fastmcp import FastMCP

# Initialize the MCP Server
mcp = FastMCP("Local_Document_QA_Server")

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

def get_file_hash(file_path: str) -> str:
    with open(file_path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()

# --- TEXT EXTRACTION ---
def extract_text_from_pdf(file_path: str) -> str:
    doc = pymupdf.open(file_path)
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

def extract_text_from_docx(file_path: str) -> str:
    doc = docx.Document(file_path)
    return "\n".join([para.text for para in doc.paragraphs if para.text.strip()])

def extract_text_from_excel(file_path: str) -> str:
    sheets = pd.read_excel(file_path, sheet_name=None)
    extracted_text = ""
    for sheet_name, df in sheets.items():
        extracted_text += f"\n--- Excel Sheet: {sheet_name} ---\n"
        extracted_text += df.to_string(index=False) + "\n"
    return extracted_text

async def query_ollama(context: str, question: str) -> str:
    payload = {
        "model": "llama3",
        "messages": [
            {"role": "system", "content": "You are a highly intelligent analytical assistant. Provide a highly detailed answer based ONLY on the provided document context."},
            {"role": "user", "content": f"Context:\n{context[:7000]}\n\nQuestion: {question}"}
        ],
        "stream": False
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(OLLAMA_URL, json=payload, timeout=None)
        return response.json().get("message", {}).get("content", "").strip()

# --- MCP TOOL REGISTRATION ---
@mcp.tool()
async def query_local_documents(folder_path: str, question: str) -> str:
    """
    Scans a local folder for PDF, Word, and Excel files, reads their contents, 
    and answers a specific question using a local Ollama AI model.
    """
    if not os.path.exists(folder_path):
        return f"Error: The folder '{folder_path}' does not exist."

    registry = load_registry()
    combined_context = ""
    valid_extensions = ['.pdf', '.docx', '.xlsx', '.xls']
    
    # Iterate through files in the specified local directory
    for filename in os.listdir(folder_path):
        ext = os.path.splitext(filename)[1].lower()
        if ext not in valid_extensions:
            continue
            
        file_path = os.path.join(folder_path, filename)
        file_hash = get_file_hash(file_path)
        cache_file_path = os.path.join(CACHE_DIR, f"{file_hash}.txt")
        
        # Check Cache
        if os.path.exists(cache_file_path):
            with open(cache_file_path, "r", encoding="utf-8") as f: text = f.read()
        else:
            try:
                if ext == ".pdf": text = extract_text_from_pdf(file_path)
                elif ext == ".docx": text = extract_text_from_docx(file_path)
                elif ext in [".xlsx", ".xls"]: text = extract_text_from_excel(file_path)
                
                with open(cache_file_path, "w", encoding="utf-8") as f: f.write(text)
                registry[file_hash] = {"name": filename}
            except Exception as e:
                continue
                
        combined_context += f"\n--- Source: {filename} ---\n" + text
        
    save_registry(registry)
    
    if not combined_context:
        return "No valid documents found in the folder."

    # Ask the local Ollama model
    answer = await query_ollama(combined_context, question)
    return answer

if __name__ == "__main__":
    # Runs the MCP server listening on standard input/output
    mcp.run()