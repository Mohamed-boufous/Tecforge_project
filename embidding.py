from sentence_transformers import SentenceTransformer
from PyPDF2 import PdfReader
import docx # Ajout : pour lire les fichiers .docx
import pandas as pd # Ajout : pour lire les fichiers .xlsx
import weaviate
import weaviate.classes.config as wvc
import weaviate.classes.data as wcd
import os

# --- Initialisation ---
model = SentenceTransformer("BAAI/bge-base-en-v1.5")
CLASS_NAME = "DocumentParagraph" # Modification : nom de classe plus générique
FILES_DIRECTORY = os.path.join(os.path.dirname(__file__), "documents") # Modification : nom de dossier plus générique

# S'assurer que le répertoire des documents existe
if not os.path.exists(FILES_DIRECTORY):
    os.makedirs(FILES_DIRECTORY)

# --- Fonctions d'extraction de texte ---

def extraire_texte_pdf(chemin_fichier):
    # Extrait le texte d'un fichier PDF.
    texte = ""
    try:
        reader = PdfReader(chemin_fichier)
        for page in reader.pages:
            contenu = page.extract_text()
            if contenu:
                texte += contenu + "\n"
    except Exception as e:
        print(f"Erreur avec {chemin_fichier} : {e}")
    return texte

def extraire_texte_docx(chemin_fichier):
    # Ajout : Extrait le texte d'un fichier DOCX.
    try:
        document = docx.Document(chemin_fichier)
        return "\n".join([para.text for para in document.paragraphs])
    except Exception as e:
        print(f"Erreur avec {chemin_fichier} : {e}")
        return ""

def extraire_texte_xlsx(chemin_fichier):
    # Ajout : Extrait le texte de toutes les cellules d'un fichier XLSX.
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
    # Ajout : choisit la bonne fonction d'extraction selon l'extension du fichier.
    extension = os.path.splitext(chemin_fichier)[1].lower()
    if extension == ".pdf":
        return extraire_texte_pdf(chemin_fichier)
    elif extension == ".docx":
        return extraire_texte_docx(chemin_fichier)
    elif extension == ".xlsx":
        return extraire_texte_xlsx(chemin_fichier)
    else:
        print(f"Type de fichier non supporté : {extension}")
        return ""

def decouper_texte(texte):
    # Découpe le texte en paragraphes nettoyés.
    return [p.strip() for p in texte.split("\n") if len(p.strip()) > 10]

# --- Fonctions Weaviate ---
def traiter_fichier(client, chemin_fichier):
    # Traite un fichier (extraction, vectorisation, insertion).
    texte = extraire_texte_fichier(chemin_fichier) # Modification : utilise la fonction générique d'extraction.
    if not texte:
        print(f"❗ Aucun texte extrait de {chemin_fichier}.")
        return 0

    paragraphes = decouper_texte(texte)
    if not paragraphes:
        print(f"❗ Aucun paragraphe trouvé dans {chemin_fichier}.")
        return 0

    print(f"  -> Vectorisation de {len(paragraphes)} paragraphes...")
    embeddings = model.encode(paragraphes, show_progress_bar=False) # Simplification : barre de progression désactivée pour un affichage plus propre.

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
            # Modification : traite les .pdf, .docx, et .xlsx
            if nom_fichier.lower().endswith((".pdf", ".docx", ".xlsx")):
                chemin = os.path.join(FILES_DIRECTORY, nom_fichier)
                print(f"📄 Traitement du fichier : {nom_fichier}")
                try:
                    nb = traiter_fichier(client, chemin)
                    print(f"   -> {nb} paragraphes indexés.")
                    total_para += nb
                except Exception as e:
                    print(f"❌ Erreur lors du traitement de {nom_fichier}: {e}")

        print(f"\n--- Fin du traitement ---")
        print(f"📊 Total des paragraphes indexés : {total_para}")