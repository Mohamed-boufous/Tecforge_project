import streamlit as st
import json
import math
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
from PIL import Image
import pytesseract
from pdf2image import convert_from_path
from datetime import datetime, timezone

# --- Configuration de la Page et des Outils ---
st.set_page_config(layout="wide", page_title="Assistant d'Appels d'Offres")

NOM_DU_MODELE_DE_VECTEUR = 'BAAI/bge-base-en-v1.5'
CLASS_NAME = "DocumentParagraph"
FILES_DIRECTORY = os.path.join(os.path.dirname(__file__), "documents")

# Configuration de Tesseract et Poppler (essentiel pour Windows)
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
POPPLER_PATH = r"C:\poppler-24.02.0\Library\bin"

# --- Fonctions ---

@st.cache_resource
def load_model():
    """Charge le modèle de vectorisation une seule fois."""
    return SentenceTransformer(NOM_DU_MODELE_DE_VECTEUR)

@st.cache_data
def load_and_prepare_data(file_path):
    """Charge les données JSON et prépare les listes pour les filtres."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        st.error(f"Erreur lors du chargement du fichier JSON : {e}")
        return [], {}

    acheteurs, provinces, domaines = set(), set(), set()
    for item in data:
        if item.get("acheteur"): acheteurs.add(item["acheteur"])
        if isinstance(item.get("provinces"), list): provinces.update(item["provinces"])
        if isinstance(item.get("domains"), list):
            for domain_item in item["domains"]:
                if domain_item.get("domain"): domaines.add(domain_item["domain"])
    
    return data, {
        "acheteurs": sorted(list(acheteurs)),
        "provinces": sorted(list(provinces)),
        "domaines": sorted(list(domaines))
    }

def format_date(date_string):
    """Formate une date ISO en format lisible."""
    if not date_string: return "N/A"
    try:
        dt_object = datetime.fromisoformat(date_string.replace('Z', '+00:00'))
        return dt_object.strftime("%A %d/%m/%Y %H:%M")
    except (ValueError, TypeError): return "Date invalide"

def jours_restants(date_string):
    """Calcule le nombre de jours restants avant une date."""
    if not date_string: return ""
    try:
        now = datetime.now(timezone.utc)
        end_date = datetime.fromisoformat(date_string.replace('Z', '+00:00'))
        delta = end_date - now
        if delta.days >= 0:
            return f"⏳ Il reste {delta.days} jour(s)"
        else:
            return "Terminé"
    except (ValueError, TypeError): return ""

# --- Fonctions d'Extraction de Texte (avec OCR) ---

def extraire_texte_images_pdf_ocr(chemin_fichier):
    texte_ocr = ""
    try:
        images = convert_from_path(chemin_fichier, poppler_path=POPPLER_PATH)
        for img in images:
            texte_ocr += pytesseract.image_to_string(img, lang='fra') + "\n"
    except Exception as e:
        st.warning(f"Erreur OCR sur {os.path.basename(chemin_fichier)}: {e}")
    return texte_ocr

def extraire_texte_pdf(chemin_fichier):
    texte_normal = ""
    try:
        with open(chemin_fichier, "rb") as f:
            reader = PdfReader(f)
            for page in reader.pages:
                contenu = page.extract_text()
                if contenu: texte_normal += contenu + "\n"
    except Exception: pass
    
    if len(texte_normal.strip()) < 100:
        st.info(f"Texte faible, tentative d'OCR sur {os.path.basename(chemin_fichier)}...")
        return extraire_texte_images_pdf_ocr(chemin_fichier)
    return texte_normal

def extraire_texte_docx(chemin_fichier):
    try:
        document = docx.Document(chemin_fichier)
        return "\n".join([para.text for para in document.paragraphs if para.text.strip()])
    except Exception as e: st.warning(f"Erreur DOCX: {e}"); return ""

def extraire_texte_excel(chemin_fichier):
    try:
        df = pd.read_excel(chemin_fichier, sheet_name=None, header=None)
        texte = ""
        for sheet_name in df:
            texte += df[sheet_name].to_string(index=False, header=False) + "\n"
        return texte
    except Exception as e: st.warning(f"Erreur Excel: {e}"); return ""

def extraire_texte_fichier(chemin_fichier):
    extension = os.path.splitext(chemin_fichier)[1].lower()
    if extension == ".pdf": return extraire_texte_pdf(chemin_fichier)
    elif extension == ".docx": return extraire_texte_docx(chemin_fichier)
    elif extension in [".xlsx", ".xls"]: return extraire_texte_excel(chemin_fichier)
    else: return ""

def decouper_texte(texte):
    return [p.strip() for p in texte.split("\n") if len(p.strip()) > 10]

# --- Fonctions Weaviate et Workflow ---

def traiter_fichier(client, chemin_fichier, model, progress_bar_placeholder):
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
        progress_bar.progress(progress_value, text=f"Vectorisation de {nom_fichier}... {int(progress_value * 100)}%")
    
    doc_collection = client.collections.get(CLASS_NAME)
    objects_to_insert = [
        weaviate.classes.data.DataObject(properties={"content": p, "source": nom_fichier}, vector=emb.tolist())
        for p, emb in zip(paragraphes, all_embeddings)
    ]
    if objects_to_insert:
        doc_collection.data.insert_many(objects_to_insert)
        return len(objects_to_insert)
    return 0
def generer_liens(lien_initial: str):
    """Génère un lien de téléchargement à partir d'un lien de consultation."""
    lien_demande = lien_initial.replace("entreprise.EntrepriseDetailsConsultation", "entreprise.EntrepriseDemandeTelechargementDce")
    lien_final = lien_demande.replace("entreprise.EntrepriseDemandeTelechargementDce", "entreprise.EntrepriseDownloadCompleteDce")
    lien_final = lien_final.replace("refConsultation=", "reference=")
    lien_final = lien_final.replace("orgAcronyme=", "orgAcronym=")
    return lien_final
def telecharger_et_indexer_dossier(lien_initial, client, model):
    with st.status("🚀 Démarrage du processus...", expanded=True) as status:
        try:
            status.update(label="🧹 Nettoyage de la base de données et des anciens fichiers...")
            if client.collections.exists(CLASS_NAME): client.collections.delete(CLASS_NAME)
            client.collections.create(
                name=CLASS_NAME,
                properties=[wvc.Property(name="content", data_type=wvc.DataType.TEXT), wvc.Property(name="source", data_type=wvc.DataType.TEXT)],
                vectorizer_config=wvc.Configure.Vectorizer.none()
            )
            if os.path.exists(FILES_DIRECTORY): shutil.rmtree(FILES_DIRECTORY)
            os.makedirs(FILES_DIRECTORY)
            status.update(label="✅ Nettoyage terminé.")
            time.sleep(1)

            url_dossier = generer_liens(lien_initial)
            status.update(label="📥 Téléchargement du dossier en cours...")
            response = requests.get(url_dossier, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
            response.raise_for_status()
            
            status.update(label="📦 Décompression des fichiers...")
            with zipfile.ZipFile(io.BytesIO(response.content), 'r') as zip_ref:
                for member in zip_ref.infolist():
                    if member.is_dir(): continue
                    file_name = os.path.basename(member.filename)
                    if not file_name: continue
                    target_path = os.path.join(FILES_DIRECTORY, file_name)
                    with zip_ref.open(member, 'r') as source, open(target_path, 'wb') as target:
                        shutil.copyfileobj(source, target)
            
            fichiers_extraits = os.listdir(FILES_DIRECTORY)
            status.update(label=f"✨ {len(fichiers_extraits)} fichiers extraits.")
            time.sleep(1)

            total_paragraphes = 0
            fichiers_a_traiter = [f for f in fichiers_extraits if f.lower().endswith((".pdf", ".docx", ".xlsx", ".xls"))]
            if not fichiers_a_traiter:
                status.update(label="⚠️ Aucun fichier compatible trouvé.", state="error"); time.sleep(3); return

            progress_bar_placeholder = st.empty()
            for nom_fichier in fichiers_a_traiter:
                chemin_complet = os.path.join(FILES_DIRECTORY, nom_fichier)
                nb = traiter_fichier(client, chemin_complet, model, progress_bar_placeholder)
                total_paragraphes += nb
            
            progress_bar_placeholder.empty()
            status.update(label=f"🎉 Processus terminé ! {total_paragraphes} paragraphes ont été indexés.", state="complete")
            st.balloons()
            time.sleep(2)
            # MODIFIÉ : On ne change plus de vue automatiquement.
            # L'application va se rafraîchir et afficher les nouvelles sections ci-dessous.

        except Exception as e:
            status.update(label=f"❌ Erreur critique : {e}", state="error")

# --- Vues de l'Application ---

def display_list_view(data, filter_options):
    st.sidebar.header("🔎 Filtres")
    keyword_filter = st.sidebar.text_input("Rechercher par Réf, ID ou Objet")
    acheteur_filter = st.sidebar.multiselect("Filtrer par Acheteur", options=filter_options["acheteurs"])
    province_filter = st.sidebar.multiselect("Filtrer par Province", options=filter_options["provinces"])
    domaine_filter = st.sidebar.multiselect("Filtrer par Domaine", options=filter_options["domaines"])

    filtered_data = data
    if keyword_filter:
        keyword_lower = keyword_filter.lower()
        filtered_data = [item for item in filtered_data if keyword_lower in str(item.get("consId", "")).lower() or keyword_lower in item.get("reference", "").lower() or any(keyword_lower in lot.get("lotObject", "").lower() for lot in item.get("lots", []))]
    if acheteur_filter: filtered_data = [item for item in filtered_data if item.get("acheteur") in acheteur_filter]
    if province_filter: filtered_data = [item for item in filtered_data if any(p in province_filter for p in item.get("provinces", []))]
    if domaine_filter: filtered_data = [item for item in filtered_data if any(d.get("domain") in domaine_filter for d in item.get("domains", []))]

    st.title("📄 Appels d'Offres Publics")
    st.write(f"**{len(filtered_data)}** résultat(s) trouvé(s)")
    st.divider()

    ITEMS_PER_PAGE = 10
    total_items = len(filtered_data)
    total_pages = math.ceil(total_items / ITEMS_PER_PAGE) if total_items > 0 else 1
    if 'page' not in st.session_state or st.session_state.page > total_pages:
        st.session_state.page = 1
    start_index = (st.session_state.page - 1) * ITEMS_PER_PAGE
    paginated_data = filtered_data[start_index:start_index + ITEMS_PER_PAGE]

    for item in paginated_data:
        with st.container(border=True):
            col_header_text, col_header_badge = st.columns([0.8, 0.2])
            with col_header_text:
                st.markdown(f'<h5>{item.get("AchAbr", "")} - {item.get("acheteur", "N/A")}</h5>', unsafe_allow_html=True)
                st.caption(f"Publié le : {format_date(item.get('publishedDate'))}")
            with col_header_badge:
                st.markdown('<div style="background-color:#dcfce7;color:#166534;padding:5px 12px;border-radius:15px;font-weight:bold;text-align:center;margin-top:10px;">EN COURS</div>', unsafe_allow_html=True)
            
            st.divider()

            col_info, col_boutons = st.columns([0.7, 0.3])
            with col_info:
                st.markdown(f"""
                <div style="line-height:1.8; font-size:0.95rem;">
                    <span>📋 {item.get("procedureType", "N/A")}</span><br>
                    <span><strong>Référence :</strong> {item.get("reference", "N/A")}</span><br>
                    <span>📍 {', '.join(item.get("provinces", []))}</span><br>
                    <span><strong>Date limite :</strong> {format_date(item.get("endDate"))}</span><br>
                    <span><strong>Réponse :</strong> {item.get("reponseType", "").replace("-", " ").title()}</span><br>
                    <strong style="color: #d9480f;">{jours_restants(item.get('endDate'))}</strong>
                </div>
                """, unsafe_allow_html=True)
            with col_boutons:
                st.link_button("🔗 Page de Consultation", item.get("detailsUrl", "#"), use_container_width=True)
                if st.button("⚙️ Traiter ce Dossier", key=f"process_{item.get('consId')}", use_container_width=True):
                    st.session_state.view = 'process'
                    st.session_state.lien_a_traiter = item.get("detailsUrl")
                    st.rerun()

            for lot in item.get("lots", []):
                st.markdown(f'<div style="font-size:1.2rem;font-weight:bold;color:#374151;text-align:center;margin:20px 0;padding:10px;background-color:#f9fafb;border-radius:8px;">{lot.get("lotObject", "Non spécifié")}</div>', unsafe_allow_html=True)
                lot_col1, lot_col2, lot_col3 = st.columns(3)
                lot_col1.metric("Catégorie", lot.get("lotCategory", "N/A"))
                lot_col2.metric("Estimation", f"{lot.get('lotEstimation', 0):,.2f} MAD".replace(",", " "))
                lot_col3.metric("Caution", f"{lot.get('lotCaution', 0):,.2f} MAD".replace(",", " "))
        st.write("") 

    if total_pages > 1:
        st.divider()
        col_prev, col_page, col_next = st.columns([1, 1, 1])
        with col_prev:
            if st.button("⬅️ Précédent", disabled=(st.session_state.page <= 1), use_container_width=True):
                st.session_state.page -= 1; st.rerun()
        with col_page:
            st.write(f"<div style='text-align:center;margin-top:8px;'><b>Page {st.session_state.page} sur {total_pages}</b></div>", unsafe_allow_html=True)
        with col_next:
            if st.button("Suivant ➡️", disabled=(st.session_state.page >= total_pages), use_container_width=True):
                st.session_state.page += 1; st.rerun()

def display_process_view(client, model):
    """Affiche la vue de traitement pour un appel d'offres spécifique."""
    st.title("⚙️ Traitement et Indexation d'un Appel d'Offres")
    if st.button("⬅️ Retour à la liste"):
        st.session_state.view = 'list'
        if 'lien_a_traiter' in st.session_state:
            del st.session_state.lien_a_traiter
        st.rerun()
    lien = st.session_state.get("lien_a_traiter", "")
    st.text_input("Lien de la consultation à traiter :", value=lien, disabled=True)
    
    if st.button("Lancer le Traitement", type="primary"):
        if lien:
            telecharger_et_indexer_dossier(lien, client, model)
            # MODIFIÉ : On rafraîchit la page pour afficher les nouvelles sections
            st.rerun()
        else:
            st.error("Aucun lien à traiter.")
            
    st.divider()
    
    # --- AJOUT : État de la base de données et recherche ---
    st.header("📊 État de la base de données")
    col1, col2 = st.columns(2)
    
    with col1:
        fichiers_supportes = [f for f in os.listdir(FILES_DIRECTORY) if f.lower().endswith((".pdf", ".docx", ".xlsx", ".xls"))]
        st.metric(label="📄 Fichiers Locaux", value=len(fichiers_supportes))

    with col2:
        total_paragraphs = 0
        if client.collections.exists(CLASS_NAME):
            doc_collection = client.collections.get(CLASS_NAME)
            response = doc_collection.aggregate.over_all(total_count=True)
            total_paragraphs = response.total_count
        st.metric(label="✍️ Paragraphes dans Weaviate", value=total_paragraphs)
    
    st.divider()

    st.header("🔎 Rechercher dans les documents")
    requete_utilisateur = st.text_input("Que cherchez-vous ?", "Fourniture de bureau", key="search_process_view")
    if st.button("Lancer la recherche", key="search_button_process"):
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

# --- Exécution Principale ---
if 'view' not in st.session_state: st.session_state.view = 'list'
if 'page' not in st.session_state: st.session_state.page = 1

data, filter_options = load_and_prepare_data("resultats_uniques.json")
model = load_model()

try:
    with weaviate.connect_to_local(port=8080, grpc_port=50051) as client:
        st.markdown("""
        <style>
            .stButton>button {
                border-radius: 8px;
                padding: 10px 24px;
                font-weight: bold;
            }
        </style>
        """, unsafe_allow_html=True)
        
        if st.session_state.view == 'list':
            display_list_view(data, filter_options)
        elif st.session_state.view == 'process':
            display_process_view(client, model)
except Exception as e:
    st.error(f"Erreur de connexion à Weaviate ou critique : {e}")
