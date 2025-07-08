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
                    texte += contenu + "\n"
    except Exception as e:
        st.warning(f"Erreur de lecture PDF pour {os.path.basename(chemin_fichier)}: {e}")
    return texte

def extraire_texte_docx(chemin_fichier):
    try:
        document = docx.Document(chemin_fichier)
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
    return [p.strip() for p in texte.split("\n") if len(p.strip()) > 10]

# --- Fonctions Weaviate et Workflow ---

def traiter_fichier(client, chemin_fichier, model, progress_bar_placeholder):
    """Extrait, vectorise et insère le contenu d'un fichier dans Weaviate."""
    nom_fichier = os.path.basename(chemin_fichier)
    
    texte = extraire_texte_fichier(chemin_fichier)
    if not texte: return 0

    paragraphes = decouper_texte(texte)
    if not paragraphes: return 0

    progress_bar = progress_bar_placeholder.progress(0, text=f"Vectorisation de {nom_fichier}...")
    
    all_embeddings = []
    batch_size = 32
    
    for i in range(0, len(paragraphes), batch_size):
        batch = paragraphes[i:i + batch_size]
        batch_embeddings = model.encode(batch, show_progress_bar=False)
        all_embeddings.extend(batch_embeddings)
        
        progress_value = (i + len(batch)) / len(paragraphes)
        progress_text = f"Vectorisation de {nom_fichier}... {int(progress_value * 100)}%"
        progress_bar.progress(progress_value, text=progress_text)

    embeddings = all_embeddings

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
            
            # MODIFIÉ : Étape 3 - Décompression intelligente pour éviter les sous-dossiers.
            status.update(label="📦 Décompression des fichiers...")
            with zipfile.ZipFile(io.BytesIO(response.content), 'r') as zip_ref:
                for member in zip_ref.infolist():
                    # Ne pas traiter les dossiers contenus dans le ZIP
                    if member.is_dir():
                        continue
                    
                    # Extraire seulement le nom du fichier, en ignorant les dossiers parents de l'archive
                    file_name = os.path.basename(member.filename)
                    
                    if not file_name:
                        continue

                    # Créer le chemin de destination final directement dans le dossier 'documents'
                    target_path = os.path.join(FILES_DIRECTORY, file_name)
                    
                    # Ouvrir le fichier source dans le ZIP et le copier dans la destination
                    with zip_ref.open(member, 'r') as source, open(target_path, 'wb') as target:
                        shutil.copyfileobj(source, target)
            
            fichiers_extraits = os.listdir(FILES_DIRECTORY)
            status.update(label=f"✨ {len(fichiers_extraits)} fichiers extraits.")
            time.sleep(1)

            # Étape 4 : Indexation.
            total_paragraphes = 0
            fichiers_a_traiter = [f for f in fichiers_extraits if f.lower().endswith((".pdf", ".docx", ".xlsx", ".xls"))]
            
            if not fichiers_a_traiter:
                status.update(label="⚠️ Aucun fichier compatible trouvé dans l'archive.", state="error")
                time.sleep(3)
                return

            progress_bar_placeholder = st.empty()

            for nom_fichier in fichiers_a_traiter:
                chemin_complet = os.path.join(FILES_DIRECTORY, nom_fichier)
                nb = traiter_fichier(client, chemin_complet, model, progress_bar_placeholder)
                total_paragraphes += nb
            
            progress_bar_placeholder.empty()
            status.update(label=f"🎉 Processus terminé ! {total_paragraphes} paragraphes ont été indexés.", state="complete")
            st.balloons()
            time.sleep(2)
            st.rerun()

        except Exception as e:
            status.update(label=f"❌ Erreur critique : {e}", state="error")

# --- Application Streamlit ---
try:
    st.set_page_config(layout="wide", page_title="Assistant AO")
    
    st.markdown("""
        <style>
        /* Style général des titres */
        h1, h2 {
            color: #1e3a8a; /* Bleu foncé */
            font-weight: bold;
        }

        /* Style pour centrer les boutons */
        .stButton {
            display: flex;
            justify-content: center;
            margin-top: 1rem;
            margin-bottom: 1rem;
        }

        .stButton > button {
            background-color: #000000; /* Noir */
            color: white;
            border-radius: 8px;
            border: none;
            padding: 10px 24px;
            font-weight: bold;
            transition: color 0.2s, background-color 0.2s; /* Transition douce pour les deux propriétés */
        }

        .stButton > button:hover {
            background-color: #333333; /* Gris foncé au survol */
            /* MODIFIÉ : Le texte devient vert au survol */
            color: #22c55e; 
        }

        /* MODIFIÉ : Style pour les conteneurs de métriques avec un fond neutre */
        div[data-testid="stMetric"] {
            background-color: #000000;  /* Fond blanc propre */
            border: 1px solid #e0e0e0;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.05);
        }
        
        /* AJOUT : Style pour que seule la valeur de la métrique soit en vert */
        div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
            color: #16a34a; /* Vert pour la valeur (le chiffre) */
        }

        /* AJOUT : Style pour que l'étiquette reste dans une couleur neutre */
        div[data-testid="stMetric"] div[data-testid="stMetricLabel"] {
            color: #4b5563; /* Gris pour l'étiquette (le texte) */
        }

        /* Style pour les résultats de recherche */
        div[data-testid="stInfo"] {
            background-color: #eef2ff;
            border-left: 5px solid #4f46e5;
            padding: 1rem;
            border-radius: 8px;
            color: #1f2937; /* Texte en gris foncé */
        }
        </style>
        """, unsafe_allow_html=True)



    model = load_model()
    
    col_titre, col_logo = st.columns([0.85, 0.15])
    with col_titre:
        st.title("📂 Assistant d'Appels d'Offres")
    with col_logo:
        if os.path.exists("tec.png"):
            st.image("tec.png", width=120)

    os.makedirs(FILES_DIRECTORY, exist_ok=True)
    
    with weaviate.connect_to_local(port=8080, grpc_port=50051) as client:
        st.header("1. Ajouter ou Remplacer un appel d'offres")
        lien_initial_utilisateur = st.text_input(
            "Collez le lien de la consultation ici :",
            "https://www.marchespublics.gov.ma/index.php?page=entreprise.EntrepriseDetailsConsultation&refConsultation=908012&orgAcronyme=g8e",
            label_visibility="collapsed"
        )
        if st.button("Lancer le Traitement"):
            if lien_initial_utilisateur and "entreprise.EntrepriseDetailsConsultation" in lien_initial_utilisateur:
                telecharger_et_indexer_dossier(lien_initial_utilisateur, client, model)
            else:
                st.error("Veuillez entrer un lien de consultation valide.")
        
        st.divider()

        st.header("📊 État de la base de données")
        col1, col2 = st.columns(2)
        
        with col1:
            fichiers_supportes = [f for f in os.listdir(FILES_DIRECTORY) if f.lower().endswith((".pdf", ".docx", ".xlsx", ".xls"))]
            st.metric(label="� Fichiers Locaux", value=len(fichiers_supportes))

        with col2:
            total_paragraphs = 0
            if client.collections.exists(CLASS_NAME):
                doc_collection = client.collections.get(CLASS_NAME)
                response = doc_collection.aggregate.over_all(total_count=True)
                total_paragraphs = response.total_count
            st.metric(label="✍️ Paragraphes dans Weaviate", value=total_paragraphs)
        
        st.divider()

        st.header("2. Rechercher dans les documents")
        requete_utilisateur = st.text_input("Que cherchez-vous ?", "Fourniture de bureau", label_visibility="collapsed")
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
