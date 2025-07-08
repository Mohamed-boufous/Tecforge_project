import streamlit as st
import weaviate
import weaviate.classes.query as wq
import weaviate.classes.config as wvc
from sentence_transformers import SentenceTransformer
import os
import requests
import zipfile
import io
import time
from pypdf import PdfReader
import docx
import pandas as pd
import shutil

# --- Configuration ---
NOM_DU_MODELE_DE_VECTEUR = 'BAAI/bge-base-en-v1.5'
CLASS_NAME = "DocumentParagraph"
FILES_DIRECTORY = os.path.join(os.path.dirname(__file__), "documents")

# --- Fonctions Utilitaires ---

@st.cache_resource
def load_model():
    """Charge le modèle de vectorisation une seule fois pour de meilleures performances."""
    return SentenceTransformer(NOM_DU_MODELE_DE_VECTEUR)

def generer_liens(lien_initial: str):
    """Génère un lien de téléchargement à partir d'un lien de consultation."""
    lien_demande = lien_initial.replace("entreprise.EntrepriseDetailsConsultation", "entreprise.EntrepriseDemandeTelechargementDce")
    lien_final = lien_demande.replace("entreprise.EntrepriseDemandeTelechargementDce", "entreprise.EntrepriseDownloadCompleteDce")
    lien_final = lien_final.replace("refConsultation=", "reference=")
    lien_final = lien_final.replace("orgAcronyme=", "orgAcronym=")
    return lien_final

# --- Fonctions d'Extraction de Texte ---

def extraire_texte_pdf(chemin_fichier):
    texte = ""
    try:
        with open(chemin_fichier, "rb") as f:
            reader = PdfReader(f)
            for page in reader.pages:
                contenu = page.extract_text()
                if contenu:
                    # MODIFIÉ : Utilisation d'un seul saut de ligne pour correspondre à la nouvelle logique de découpage.
                    texte += contenu + "\n"
    except Exception as e:
        st.warning(f"Erreur de lecture PDF pour {os.path.basename(chemin_fichier)}: {e}")
    return texte

def extraire_texte_docx(chemin_fichier):
    try:
        document = docx.Document(chemin_fichier)
        # MODIFIÉ : Utilisation d'un seul saut de ligne pour joindre les paragraphes.
        return "\n".join([para.text for para in document.paragraphs if para.text.strip()])
    except Exception as e:
        st.warning(f"Erreur de lecture DOCX pour {os.path.basename(chemin_fichier)}: {e}")
        return ""

def extraire_texte_excel(chemin_fichier):
    """Extrait le texte des fichiers .xlsx et .xls."""
    try:
        df = pd.read_excel(chemin_fichier, sheet_name=None, header=None)
        texte = ""
        for sheet_name in df:
            # MODIFIÉ : Utilisation d'un seul saut de ligne pour joindre le contenu des feuilles.
            texte += df[sheet_name].to_string(index=False, header=False) + "\n"
        return texte
    except Exception as e:
        st.warning(f"Erreur de lecture Excel pour {os.path.basename(chemin_fichier)}: {e}")
        return ""

def extraire_texte_fichier(chemin_fichier):
    """Choisit la bonne fonction d'extraction selon l'extension du fichier."""
    extension = os.path.splitext(chemin_fichier)[1].lower()
    if extension == ".pdf":
        return extraire_texte_pdf(chemin_fichier)
    elif extension == ".docx":
        return extraire_texte_docx(chemin_fichier)
    elif extension in [".xlsx", ".xls"]:
        return extraire_texte_excel(chemin_fichier)
    else:
        return ""

def decouper_texte(texte):
    """Découpe un texte en paragraphes en se basant sur les sauts de ligne."""
    # MODIFIÉ : Découpage par simple saut de ligne, comme demandé dans votre code de référence.
    return [p.strip() for p in texte.split("\n") if len(p.strip()) > 10]

# --- Fonctions Weaviate et Workflow ---

def traiter_fichier(client, chemin_fichier, model, st_status):
    """Extrait, vectorise et insère le contenu d'un fichier dans Weaviate."""
    nom_fichier = os.path.basename(chemin_fichier)
    st_status.update(label=f"Lecture de {nom_fichier}...")
    
    texte = extraire_texte_fichier(chemin_fichier)
    if not texte:
        st_status.update(label=f"⚠️ Aucun texte trouvé dans {nom_fichier}, fichier ignoré.")
        time.sleep(1)
        return 0

    st_status.update(label=f"Texte extrait de {nom_fichier}. Découpage en paragraphes...")
    paragraphes = decouper_texte(texte)
    
    if not paragraphes:
        st_status.update(label=f"⚠️ Aucun paragraphe valide trouvé dans {nom_fichier}, fichier ignoré.")
        time.sleep(1)
        return 0

    st_status.update(label=f"Vectorisation de {len(paragraphes)} paragraphes pour {nom_fichier}...")
    embeddings = model.encode(paragraphes, show_progress_bar=False)
    
    doc_collection = client.collections.get(CLASS_NAME)
    objects_to_insert = [
        weaviate.classes.data.DataObject(
            properties={"content": p, "source": nom_fichier},
            vector=emb.tolist()
        )
        for p, emb in zip(paragraphes, embeddings)
    ]
    
    if objects_to_insert:
        doc_collection.data.insert_many(objects_to_insert)
        return len(objects_to_insert)
    return 0

def telecharger_et_indexer_dossier(lien_initial, client, model):
    """Orchestre le nettoyage, le téléchargement, la décompression et l'indexation."""
    with st.status("🚀 Démarrage du processus...", expanded=True) as status:
        try:
            # Étape 1 : Nettoyage complet.
            status.update(label="🧹 Nettoyage de la base de données et des anciens fichiers...")
            if client.collections.exists(CLASS_NAME):
                client.collections.delete(CLASS_NAME)
            
            client.collections.create(
                name=CLASS_NAME,
                properties=[
                    wvc.Property(name="content", data_type=wvc.DataType.TEXT),
                    wvc.Property(name="source", data_type=wvc.DataType.TEXT)
                ],
                vectorizer_config=wvc.Configure.Vectorizer.none()
            )
            if os.path.exists(FILES_DIRECTORY):
                shutil.rmtree(FILES_DIRECTORY)
            os.makedirs(FILES_DIRECTORY)
            status.update(label="✅ Nettoyage terminé.")
            time.sleep(1)

            # Étape 2 : Téléchargement.
            url_dossier = generer_liens(lien_initial)
            status.update(label="📥 Téléchargement du dossier en cours...")
            response = requests.get(url_dossier, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
            response.raise_for_status()
            
            # Étape 3 : Décompression directe dans le dossier 'documents'.
            status.update(label="📦 Décompression des fichiers...")
            with zipfile.ZipFile(io.BytesIO(response.content), 'r') as zip_ref:
                zip_ref.extractall(FILES_DIRECTORY) # Le chemin est bien le dossier principal.
            
            fichiers_extraits = os.listdir(FILES_DIRECTORY)
            status.update(label=f"✨ {len(fichiers_extraits)} fichiers extraits.")
            time.sleep(1)

            # Étape 4 : Indexation.
            total_paragraphes = 0
            fichiers_a_traiter = [f for f in fichiers_extraits if f.lower().endswith((".pdf", ".docx", ".xlsx", ".xls"))]
            
            if not fichiers_a_traiter:
                status.update(label="⚠️ Aucun fichier compatible trouvé dans l'archive.")
                time.sleep(3)
                return

            for nom_fichier in fichiers_a_traiter:
                chemin_complet = os.path.join(FILES_DIRECTORY, nom_fichier)
                nb = traiter_fichier(client, chemin_complet, model, status)
                total_paragraphes += nb
            
            status.update(label=f"🎉 Processus terminé ! {total_paragraphes} paragraphes ont été indexés.", state="complete")
            st.rerun()

        except Exception as e:
            status.update(label=f"❌ Erreur critique : {e}", state="error")

# --- Application Streamlit ---
try:
    model = load_model()
    st.title("📂 Assistant d'Appels d'Offres")
    os.makedirs(FILES_DIRECTORY, exist_ok=True)
    
    with weaviate.connect_to_local(port=8080, grpc_port=50051) as client:
        # Section 1: Télécharger et remplacer
        st.header("1. Ajouter ou Remplacer un appel d'offres")
        lien_initial_utilisateur = st.text_input(
            "Collez le lien de la consultation ici :",
            "https://www.marchespublics.gov.ma/index.php?page=entreprise.EntrepriseDetailsConsultation&refConsultation=911673&orgAcronyme=g8e"
        )
        if st.button("Télécharger, Remplacer et Indexer"):
            if lien_initial_utilisateur and "entreprise.EntrepriseDetailsConsultation" in lien_initial_utilisateur:
                telecharger_et_indexer_dossier(lien_initial_utilisateur, client, model)
            else:
                st.error("Veuillez entrer un lien de consultation valide.")
        
        st.divider()

        # Section 2: État de la base de données
        with st.expander("Voir l'état de la base de données"):
            fichiers_supportes = [f for f in os.listdir(FILES_DIRECTORY) if f.lower().endswith((".pdf", ".docx", ".xlsx", ".xls"))]
            st.info(f"{len(fichiers_supportes)} fichier(s) supporté(s) dans le dossier local.")
            if client.collections.exists(CLASS_NAME):
                doc_collection = client.collections.get(CLASS_NAME)
                response = doc_collection.aggregate.over_all(total_count=True)
                st.info(f"{response.total_count} paragraphes au total dans Weaviate.")
        
        st.divider()

        # Section 3: Recherche Sémantique
        st.header("2. Rechercher dans les documents")
        requete_utilisateur = st.text_input("Que cherchez-vous ?", "Fourniture de bureau")
        if st.button("Lancer la recherche"):
            if requete_utilisateur and client.collections.exists(CLASS_NAME):
                vecteur_requete = model.encode(requete_utilisateur).tolist()
                doc_collection = client.collections.get(CLASS_NAME)
                response = doc_collection.query.near_vector(
                    near_vector=vecteur_requete,
                    limit=5,
                    return_metadata=wq.MetadataQuery(distance=True)
                )
                st.subheader("Résultats de la recherche :")
                if not response.objects:
                    st.warning("Aucun résultat trouvé.")
                else:
                    for item in response.objects:
                        st.info(f"**Distance :** {item.metadata.distance:.4f} (plus c'est bas, mieux c'est)")
                        st.write(f"📄 **Source** : {item.properties.get('source', 'Inconnue')}")
                        st.write(f"📌 **Paragraphe** : {item.properties.get('content', '')}")
                        st.divider()

except Exception as e:
    st.error(f"Une erreur critique est survenue : {e}")
