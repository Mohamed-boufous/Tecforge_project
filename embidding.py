from sentence_transformers import SentenceTransformer
from PyPDF2 import PdfReader
import weaviate
import weaviate.classes.config as wvc
import weaviate.classes.data as wcd # Ajout: Importation pour la création d'objets de données
import os

# --- Initialisation (inchangée) ---
model = SentenceTransformer("BAAI/bge-base-en-v1.5")
CLASS_NAME = "PDFParagraph" 
PDFS_DIRECTORY = "./pdfs"

# --- Fonctions de traitement de texte (inchangées) ---
def extraire_texte_pdf(chemin_pdf):
    texte = ""
    try:
        reader = PdfReader(chemin_pdf)
        for page in reader.pages:
            contenu = page.extract_text()
            if contenu:
                texte += contenu + "\n"
    except Exception as e:
        print(f"Erreur avec {chemin_pdf} : {e}")
    return texte

def decouper_texte(texte):
    return [p.strip() for p in texte.split("\n") if len(p.strip()) > 10]

# --- Fonctions Weaviate (MODIFIÉE ET CORRIGÉE) ---
def traiter_pdf(client, chemin_pdf):
    texte = extraire_texte_pdf(chemin_pdf)
    if not texte:
        return 0
    
    paragraphes = decouper_texte(texte)
    if not paragraphes:
        return 0
        
    print(f"  -> Vectorisation de {len(paragraphes)} paragraphes...")
    embeddings = model.encode(paragraphes, show_progress_bar=False)

    pdf_collection = client.collections.get(CLASS_NAME)
    
    # Correction: La construction de la liste d'objets est maintenant correcte
    objects_to_insert = []
    for p, emb in zip(paragraphes, embeddings):
        # Pour chaque paragraphe, on crée un objet de données complet...
        data_object = wcd.DataObject(
            properties={
                "content": p,
                "source": os.path.basename(chemin_pdf)
            },
            vector=emb.tolist()
        )
        # ...et on ajoute cet objet unique à la liste.
        objects_to_insert.append(data_object)
    
    pdf_collection.data.insert_many(objects_to_insert)
    
    return len(paragraphes)

# --- Exécution principale (modifiée pour la v4) ---
if __name__ == "__main__":
    # Connexion sur le port 8080 pour correspondre à votre docker-compose.yml
    with weaviate.connect_to_local(port=8080, grpc_port=50051) as client: 
        print("Connexion à Weaviate réussie.")

        if not client.collections.exists(CLASS_NAME):
            print(f"La collection '{CLASS_NAME}' n'existe pas. Création...")
            client.collections.create(
                name=CLASS_NAME,
                properties=[
                    wvc.Property(name="content", data_type=wvc.DataType.TEXT),
                    wvc.Property(name="source", data_type=wvc.DataType.TEXT),
                ],
                vectorizer_config=wvc.Configure.Vectorizer.none() 
            )
            print("Collection créée.")

        total_para = 0
        for nom_fichier in os.listdir(PDFS_DIRECTORY):
            if nom_fichier.lower().endswith(".pdf"):
                chemin = os.path.join(PDFS_DIRECTORY, nom_fichier)
                print(f"Traitement du fichier : {chemin}")
                try:
                    nb = traiter_pdf(client, chemin)
                    print(f" -> {nb} paragraphes indexés pour {nom_fichier}")
                    total_para += nb
                except Exception as e:
                    print(f"Erreur lors du traitement de {nom_fichier}: {e}")

        print(f"\nTotal des paragraphes indexés : {total_para}")