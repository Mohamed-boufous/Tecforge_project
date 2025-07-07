from sentence_transformers import SentenceTransformer
from PyPDF2 import PdfReader
import weaviate
import weaviate.classes.config as wvc
import weaviate.classes.data as wcd # Importation pour la création d'objets de données
import os

# --- Initialisation (inchangée) ---
model = SentenceTransformer("BAAI/bge-base-en-v1.5")
CLASS_NAME = "PDFParagraph" 
PDFS_DIRECTORY = os.path.join(os.path.dirname(__file__), "pdfs")

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

# --- Fonctions Weaviate (CORRIGÉE) ---
def traiter_pdf(client, chemin_pdf):
    texte = extraire_texte_pdf(chemin_pdf)
    if not texte:
        print(f"❗ Aucun texte extrait de {chemin_pdf}.")
        return 0

    paragraphes = decouper_texte(texte)
    if not paragraphes:
        print(f"❗ Aucun paragraphe trouvé dans {chemin_pdf}.")
        return 0

    print(f"   -> Vectorisation de {len(paragraphes)} paragraphes...")
    embeddings = model.encode(paragraphes, show_progress_bar=True)

    if embeddings is None or len(embeddings) == 0:
        print(f"❗ Aucun vecteur généré pour {chemin_pdf}.")
        return 0

    pdf_collection = client.collections.get(CLASS_NAME)

    objects_to_insert = []
    for p, emb in zip(paragraphes, embeddings):
        emb_list = emb.tolist()
        # Commentaire: Ajout d'une impression pour vérifier le vecteur avant insertion.
        # print(f"Vecteur généré pour le paragraphe (début) : {emb_list[:5]}...") 
        if not emb_list or all(v == 0 for v in emb_list):
            print(f"⚠ Vecteur vide ou nul pour un paragraphe : {p[:50]}...")
            continue # ne pas insérer cet objet

        data_object = wcd.DataObject(
            properties={
                "content": p,
                "source": os.path.basename(chemin_pdf)
            },
            # Commentaire: 'vector=emb_list' est essentiel pour l'insertion du vecteur.
            vector=emb_list
        )
        # Commentaire: Ajout de l'objet à la liste pour une insertion en masse.
        objects_to_insert.append(data_object) 

    if not objects_to_insert:
        print(f"❗ Aucun objet à insérer pour {chemin_pdf}.")
        return 0

    # Commentaire: La ligne suivante a été déplacée ici.
    # C'est l'appel principal pour insérer tous les objets collectés en une seule fois.
    pdf_collection.data.insert_many(objects_to_insert) 
    print(f"✅ {len(objects_to_insert)} paragraphes insérés pour {chemin_pdf}.")
    return len(objects_to_insert)

# --- Exécution principale (CORRIGÉE) ---
if __name__ == "__main__":
    # Connexion sur le port 8080 pour correspondre à votre docker-compose.yml
    with weaviate.connect_to_local(port=8080, grpc_port=50051) as client: 
        print("Connexion à Weaviate réussie.")

        # Commentaire: Ajout de cette condition pour supprimer la collection si elle existe,
        # cela permet de repartir d'une base propre à chaque exécution pour éviter les doublons.
        if client.collections.exists(CLASS_NAME):
            print(f"Suppression de la collection existante '{CLASS_NAME}'...")
            client.collections.delete(CLASS_NAME)
            print("Collection supprimée.")

        if not client.collections.exists(CLASS_NAME):
            print(f"La collection '{CLASS_NAME}' n'existe pas. Création...")
            client.collections.create(
                name=CLASS_NAME,
                properties=[
                    wvc.Property(name="content", data_type=wvc.DataType.TEXT),
                    wvc.Property(name="source", data_type=wvc.DataType.TEXT)
                ],
                # Commentaire: 'vectorizer_config=wvc.Configure.Vectorizer.none()'
                # indique que tu fournis les vecteurs manuellement (avec SentenceTransformer).
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