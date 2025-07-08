# --- Imports ---
from sentence_transformers import SentenceTransformer
from pypdf import PdfReader
import docx
import pandas as pd
import weaviate
import weaviate.classes.config as wvc
import weaviate.classes.data as wcd
import os

# AJOUT : Imports nécessaires pour Tesseract OCR
from PIL import Image
import pytesseract
from pdf2image import convert_from_path

# --- Initialisation ---
model = SentenceTransformer("BAAI/bge-base-en-v1.5")
CLASS_NAME = "DocumentParagraph"
FILES_DIRECTORY = os.path.join(os.path.dirname(__file__), "documents")

# S'assurer que le répertoire des documents existe
if not os.path.exists(FILES_DIRECTORY):
    os.makedirs(FILES_DIRECTORY)

# --- Configuration des outils externes ---

# MODIFIÉ : Chemin vers l'exécutable Tesseract (ESSENTIEL POUR WINDOWS)
# Décommentez cette ligne et assurez-vous que le chemin correspond à votre installation.
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# MODIFIÉ : Chemin vers le dossier 'bin' de Poppler, en utilisant le chemin que vous avez fourni.
POPPLER_PATH = r"C:\poppler-24.02.0\Library\bin"


# --- Fonctions d'extraction de texte ---

def extraire_texte_images_pdf_ocr(chemin_fichier):
    """
    Utilise Tesseract pour extraire le texte des pages d'un PDF qui sont des images.
    """
    texte_ocr = ""
    print(f"  -> Tentative d'OCR sur {os.path.basename(chemin_fichier)}...")
    try:
        # On passe le chemin de Poppler à la fonction pour qu'elle le trouve.
        images = convert_from_path(chemin_fichier, poppler_path=POPPLER_PATH)
        for i, img in enumerate(images):
            print(f"    - Lecture de l'image de la page {i+1}...")
            # Utilise Tesseract pour extraire le texte de l'image (en français)
            texte_ocr += pytesseract.image_to_string(img, lang='fra') + "\n"
    except Exception as e:
        print(f"❌ Erreur OCR sur le fichier {os.path.basename(chemin_fichier)}: {e}")
    return texte_ocr

def extraire_texte_pdf(chemin_fichier):
    """
    Tente d'abord une lecture normale. Si elle échoue, utilise l'OCR.
    """
    texte_normal = ""
    try:
        reader = PdfReader(chemin_fichier)
        for page in reader.pages:
            contenu = page.extract_text()
            if contenu:
                texte_normal += contenu + "\n"
    except Exception as e:
        print(f"Erreur avec {chemin_fichier} : {e}")
    
    # Si le texte normal est presque vide, on passe à l'OCR
    if len(texte_normal.strip()) < 100:
        return extraire_texte_images_pdf_ocr(chemin_fichier)
    else:
        return texte_normal

def extraire_texte_docx(chemin_fichier):
    try:
        document = docx.Document(chemin_fichier)
        return "\n".join([para.text for para in document.paragraphs])
    except Exception as e:
        print(f"Erreur avec {chemin_fichier} : {e}")
        return ""

def extraire_texte_xlsx(chemin_fichier):
    try:
        df = pd.read_excel(chemin_fichier, sheet_name=None, header=None)
        texte = ""
        for sheet_name in df:
            texte += df[sheet_name].to_string(index=False, header=False) + "\n"
        return texte
    except Exception as e:
        print(f"Erreur avec {chemin_fichier} : {e}")
        return ""

def extraire_texte_fichier(chemin_fichier):
    extension = os.path.splitext(chemin_fichier)[1].lower()
    if extension == ".pdf":
        return extraire_texte_pdf(chemin_fichier)
    elif extension == ".docx":
        return extraire_texte_docx(chemin_fichier)
    elif extension in [".xlsx", ".xls"]: # Ajout de .xls pour plus de compatibilité
        return extraire_texte_xlsx(chemin_fichier)
    else:
        print(f"Type de fichier non supporté : {extension}")
        return ""

def decouper_texte(texte):
    return [p.strip() for p in texte.split("\n") if len(p.strip()) > 10]

# --- Fonctions Weaviate ---
def traiter_fichier(client, chemin_fichier):
    texte = extraire_texte_fichier(chemin_fichier)
    if not texte:
        print(f"❗ Aucun texte extrait de {chemin_fichier}.")
        return 0

    paragraphes = decouper_texte(texte)
    if not paragraphes:
        print(f"❗ Aucun paragraphe trouvé dans {chemin_fichier}.")
        return 0

    print(f"  -> Vectorisation de {len(paragraphes)} paragraphes...")
    embeddings = model.encode(paragraphes, show_progress_bar=False)

    if embeddings is None or len(embeddings) == 0:
        print(f"❗ Aucun vecteur généré pour {chemin_fichier}.")
        return 0

    doc_collection = client.collections.get(CLASS_NAME)
    
    objects_to_insert = [
        wcd.DataObject(
            properties={"content": p, "source": os.path.basename(chemin_fichier)},
            vector=emb.tolist()
        )
        for p, emb in zip(paragraphes, embeddings)
    ]

    if not objects_to_insert:
        print(f"❗ Aucun objet à insérer pour {chemin_fichier}.")
        return 0
    
    doc_collection.data.insert_many(objects_to_insert)
    return len(objects_to_insert)

# --- Exécution principale ---
if __name__ == "__main__":
    with weaviate.connect_to_local(port=8080, grpc_port=50051) as client:
        print("✅ Connexion à Weaviate réussie.")

        if client.collections.exists(CLASS_NAME):
            print(f"🗑️ Suppression de la collection existante '{CLASS_NAME}'...")
            client.collections.delete(CLASS_NAME)
            print("Collection supprimée.")
        
        print(f"✨ Création de la collection '{CLASS_NAME}'...")
        client.collections.create(
            name=CLASS_NAME,
            properties=[
                wvc.Property(name="content", data_type=wvc.DataType.TEXT),
                wvc.Property(name="source", data_type=wvc.DataType.TEXT)
            ],
            vectorizer_config=wvc.Configure.Vectorizer.none()
        )
        print("Collection créée.")

        total_para = 0
        print("\n--- Début du traitement des fichiers ---")
        for nom_fichier in os.listdir(FILES_DIRECTORY):
            # On traite les .pdf, .docx, et les fichiers excel
            if nom_fichier.lower().endswith((".pdf", ".docx", ".xlsx", ".xls")):
                chemin = os.path.join(FILES_DIRECTORY, nom_fichier)
                print(f"📄 Traitement du fichier : {nom_fichier}")
                try:
                    nb = traiter_fichier(client, chemin)
                    print(f"  -> {nb} paragraphes indexés.")
                    total_para += nb
                except Exception as e:
                    print(f"❌ Erreur lors du traitement de {nom_fichier}: {e}")

        print(f"\n--- Fin du traitement ---")
        print(f"📊 Total des paragraphes indexés : {total_para}")
