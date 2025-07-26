import requests
import zipfile
import io
from PyPDF2 import PdfReader
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np

def process_zip_in_memory(url, model):
    response = requests.get(url)
    response.raise_for_status()

    zip_bytes = io.BytesIO(response.content)
    with zipfile.ZipFile(zip_bytes) as z:
        for filename in z.namelist():
            if filename.endswith(".pdf"):
                with z.open(filename) as pdf_file:
                    reader = PdfReader(pdf_file)
                    texte = ""
                    for page in reader.pages:
                        page_text = page.extract_text()
                        if page_text:
                            texte += page_text + "\n"
                    
                    paragraphes = [p.strip() for p in texte.split("\n") if len(p.strip()) > 10]
                    embeddings = model.encode(paragraphes)
                    
                    # Ici : tu peux directement ajouter à un index FAISS, DB, etc.
                    print(f"Traitement fini pour {filename} ({len(paragraphes)} paragraphes)")

                    yield embeddings, paragraphes

# Exemple d'utilisation
model = SentenceTransformer("paraphrase-MiniLM-L6-v2")
url = "https://www.marchespublics.gov.ma/index.php?page=entreprise.EntrepriseDownloadCompleteDce&reference=908892&orgAcronym=g3h"
for embeddings, paragraphs in process_zip_in_memory(url, model):
    # Ajout dans un index FAISS (ou autre traitement direct)
    pass
