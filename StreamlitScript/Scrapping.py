import streamlit as st
import json
import math
import weaviate
import queue
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
from pathlib import Path
import concurrent.futures
from pymongo import MongoClient
import certifi
from dotenv import load_dotenv
import subprocess

# --- Imports spécifiques à Windows ---
if os.name == 'nt':
    import win32com.client as win32
    import pythoncom

# --- Configuration de la Page et des Constantes ---
st.set_page_config(layout="wide", page_title="Assistant d'Appels d'Offres")

NOM_DU_MODELE_DE_VECTEUR = 'BAAI/bge-base-en-v1.5'
CLASS_NAME = "DocumentParagraph"
def find_project_root(start_path):
    # On commence depuis le chemin du script actuel
    current_path = Path(start_path).resolve()
    # On remonte les dossiers parents un par un
    while current_path != current_path.parent:
        # Si on trouve un dossier .git, c'est la racine du projet
        if (current_path / ".git").is_dir():
            return current_path
        current_path = current_path.parent
    # Si on ne trouve pas de .git, on retourne le dossier de travail actuel par sécurité
    return Path.cwd()

# MODIFIÉ : On utilise la nouvelle fonction pour définir les chemins
# Cette ligne trouve la racine du projet (ex: /chemin/vers/Tecforge_project)
ROOT_DIRECTORY = find_project_root(__file__)
# Cette ligne définit le dossier des documents à la racine
FILES_DIRECTORY = ROOT_DIRECTORY / "documents"
# --- Configurez ces chemins selon votre installation ---
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
POPPLER_PATH = r"C:\poppler-24.02.0\Library\bin"

# --- Fonctions Utilitaires et de Chargement ---

@st.cache_resource
def load_model():
    """Charge le modèle de vectorisation une seule fois."""
    return SentenceTransformer(NOM_DU_MODELE_DE_VECTEUR)

@st.cache_data(ttl=3600)
def load_data_from_mongo():
    """Charge les données des appels d'offres directement depuis MongoDB Atlas."""
    # MODIFIÉ : Utilisation de la nouvelle variable d'environnement MONGO2_URI
    MONGO_URI = os.getenv("MONGO2_URI")
    if not MONGO_URI:
        st.error("La variable d'environnement MONGO2_URI n'est pas définie !")
        return [], {}
    try:
        client = MongoClient(MONGO_URI, tls=True, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=10000)
        db = client.marchespublics_db
        collection = db.consultations
        # MODIFIÉ : On récupère toutes les données sans tri, le tri se fera en Python
        data = list(collection.find({}))
        client.close()

        # MODIFIÉ : Le tri est fait ici car le format de date "jj/mm/aaaa" n'est pas triable directement dans MongoDB
        data.sort(key=lambda x: datetime.strptime(x.get('date_publication', '01/01/1970'), "%d/%m/%Y"), reverse=True)

        acheteurs, provinces, domaines = set(), set(), set()
        for item in data:
            # MODIFIÉ : Utilisation des nouveaux noms de champs de la base de données
            if item.get("acheteur_public"): acheteurs.add(item["acheteur_public"])
            if item.get("domaine"): domaines.add(item["domaine"])
            # MODIFIÉ : On traite la chaîne de caractères "lieu_execution" pour extraire une liste de provinces
            if item.get("lieu_execution"):
                # On crée une nouvelle clé "provinces_list" pour une utilisation facile plus tard
                item['provinces_list'] = [p.strip() for p in item["lieu_execution"].split(',') if p.strip() and p.strip() != '-']
                provinces.update(item['provinces_list'])

        return data, {
            "acheteurs": sorted(list(acheteurs)),
            "provinces": sorted(list(provinces)),
            "domaines": sorted(list(domaines))
        }
    except Exception as e:
        st.error(f"Erreur de connexion à MongoDB : {e}")
        return [], {}

def format_date(date_string):
    """Formate une date en format lisible."""
    if not date_string: return "N/A"
    try:
        # MODIFIÉ : Essaye de lire le format "jj/mm/aaaa HH:MM"
        dt_object = datetime.strptime(date_string, "%d/%m/%Y %H:%M")
        return dt_object.strftime("%A %d/%m/%Y %H:%M")
    except ValueError:
        try:
            # MODIFIÉ : Essaye de lire le format "jj/mm/aaaa" si le premier échoue
            dt_object = datetime.strptime(date_string, "%d/%m/%Y")
            return dt_object.strftime("%A %d/%m/%Y")
        except (ValueError, TypeError):
            return "Date invalide"

def jours_restants(date_string):
    """Calcule le nombre de jours restants avant une date."""
    if not date_string: return ""
    try:
        # MODIFIÉ : La date est maintenant lue au format "jj/mm/aaaa HH:MM"
        end_date = datetime.strptime(date_string, "%d/%m/%Y %H:%M")
        now = datetime.now() # On utilise la date et heure actuelles (naïve)
        delta = end_date - now
        return f"⏳ Il reste {delta.days} jour(s)" if delta.days >= 0 else "Terminé"
    except (ValueError, TypeError):
        return ""

# --- Fonctions d'Extraction de Texte (INCHANGÉES) ---
# Intérêt du code : Ajoute une fonction dédiée à la lecture du texte contenu dans les fichiers images.
def extraire_texte_image_ocr(chemin_fichier):
    """
    Extrait le texte d'un fichier image en utilisant Pytesseract (OCR).
    """
    try:
        # On utilise la librairie Pillow (Image) pour ouvrir le fichier image
        img = Image.open(chemin_fichier)
        # On utilise pytesseract pour convertir l'image en chaîne de caractères
        texte = pytesseract.image_to_string(img, lang='fra')
        # On retourne le texte et on indique que l'OCR a été utilisé
        return texte, True
    except Exception as e:
        st.warning(f"Avertissement OCR sur l'image {os.path.basename(chemin_fichier)}: {e}")
        return "", True 
    
def extraire_texte_images_pdf_ocr(chemin_fichier):
    texte_ocr = ""
    try:
        images = convert_from_path(chemin_fichier, poppler_path=POPPLER_PATH)
        for img in images:
            texte_ocr += pytesseract.image_to_string(img, lang='fra') + "\n"
    except Exception as e:
        st.warning(f"Avertissement OCR sur {os.path.basename(chemin_fichier)}: {e}")
    return texte_ocr

def extraire_texte_pdf(chemin_fichier):
    texte_normal = ""
    ocr_utilise = False
    try:
        with open(chemin_fichier, "rb") as f:
            reader = PdfReader(f)
            for page in reader.pages:
                contenu = page.extract_text()
                if contenu: texte_normal += contenu + "\n"
    except Exception: pass

    if len(texte_normal.strip()) < 100:
        texte_ocr = extraire_texte_images_pdf_ocr(chemin_fichier)
        if texte_ocr:
            ocr_utilise = True
            return texte_ocr, ocr_utilise
    return texte_normal, ocr_utilise

def extraire_texte_docx(chemin_fichier):
    try:
        document = docx.Document(chemin_fichier)
        return "\n".join([para.text for para in document.paragraphs if para.text.strip()])
    except Exception as e: raise Exception(f"Erreur DOCX: {e}")

def extraire_texte_excel(chemin_fichier):
    try:
        df = pd.read_excel(chemin_fichier, sheet_name=None, header=None)
        texte = ""
        for sheet_name, sheet_df in df.items():
            texte += sheet_df.to_string(index=False, header=False) + "\n"
        return texte
    except Exception as e: raise Exception(f"Erreur Excel: {e}")

def decouper_texte(texte):
    return [p.strip() for p in texte.split("\n") if len(p.strip()) > 10]


# --- Fonctions de Traitement et d'Indexation (INCHANGÉES) ---

# Intérêt du code : Met à jour la fonction principale de traitement pour qu'elle gère aussi les images.
def traiter_fichier(client, chemin_fichier, model, progress_queue):
    nom_fichier = os.path.basename(chemin_fichier)
    try:
        ocr_utilise = False
        extension = os.path.splitext(chemin_fichier)[1].lower()
        texte = ""
        progress_queue.put((nom_fichier, 5, "Extraction du texte..."))

        # MODIFIÉ : On définit une liste d'extensions d'images reconnues
        extensions_images = ('.png', '.jpg', '.jpeg', '.bmp', '.tiff')

        if extension == ".pdf":
            texte, ocr_utilise = extraire_texte_pdf(chemin_fichier)
        elif extension == ".docx":
            texte = extraire_texte_docx(chemin_fichier)
        elif extension in [".xlsx", ".xls"]:
            texte = extraire_texte_excel(chemin_fichier)
        # MODIFIÉ : On ajoute une condition pour traiter les fichiers images
        elif extension in extensions_images:
            # On appelle la nouvelle fonction pour extraire le texte des images
            texte, ocr_utilise = extraire_texte_image_ocr(chemin_fichier)
        
        if not texte:
            progress_queue.put((nom_fichier, 100, "Fichier vide ou illisible"))
            return 0, ocr_utilise

        # Le reste de la fonction ne change pas...
        paragraphes = decouper_texte(texte)
        if not paragraphes:
            progress_queue.put((nom_fichier, 100, "Aucun paragraphe trouvé"))
            return 0, ocr_utilise

        total_paragraphes = len(paragraphes)
        batch_size = 32
        doc_collection = client.collections.get(CLASS_NAME)

        for i in range(0, total_paragraphes, batch_size):
            batch_paragraphes = paragraphes[i:i + batch_size]
            batch_embeddings = model.encode(batch_paragraphes, show_progress_bar=False)
            objects_to_insert = [
                weaviate.classes.data.DataObject(properties={"content": p, "source": nom_fichier}, vector=emb.tolist())
                for p, emb in zip(batch_paragraphes, batch_embeddings)
            ]
            if objects_to_insert:
                doc_collection.data.insert_many(objects_to_insert)

            progress_percentage = 10 + int(((i + len(batch_paragraphes)) / total_paragraphes) * 85)
            progress_queue.put((nom_fichier, progress_percentage, f"Traitement... {i + len(batch_paragraphes)}/{total_paragraphes}"))

        progress_queue.put((nom_fichier, 100, f"✅ Terminé ({total_paragraphes} paragraphes)"))
        return total_paragraphes, ocr_utilise

    except Exception as e:
        progress_queue.put((nom_fichier, -1, str(e)))
        return 0, False

def convertir_vers_docx(dossier_path):
    extensions = (".doc", ".rtf")
    fichiers_a_convertir = [f for f in os.listdir(dossier_path) if f.lower().endswith(extensions) and not f.startswith('~$')]
    if not fichiers_a_convertir:
        st.info("Aucun fichier .doc ou .rtf à convertir.")
        return
    placeholder = st.empty()
    fichiers_convertis = 0
    for nom_fichier in fichiers_a_convertir:
        chemin_original = os.path.join(dossier_path, nom_fichier)
        placeholder.info(f"🔄 Conversion de {nom_fichier} avec LibreOffice...")
        try:
            commande = [
                "soffice", "--headless", "--convert-to", "docx", "--outdir", dossier_path, chemin_original
            ]
            result = subprocess.run(commande, check=True, capture_output=True, timeout=120)
            os.remove(chemin_original)
            fichiers_convertis += 1
        except FileNotFoundError:
            st.error("❌ Commande 'soffice' introuvable. Assurez-vous que LibreOffice est installé et dans le PATH.")
            return
        except subprocess.CalledProcessError as e:
            st.warning(f"⚠️ La conversion de '{nom_fichier}' a échoué. Erreur : {e.stderr.decode()}")
        except Exception as e:
            st.warning(f"⚠️ Une erreur est survenue lors de la conversion de '{nom_fichier}': {e}")
    placeholder.empty()
    if fichiers_convertis > 0:
        st.success(f"{fichiers_convertis} fichier(s) ont été convertis en .docx.")


def extraire_et_aplatir_zip(zip_file_object, destination_folder):
    for member in zip_file_object.infolist():
        if member.is_dir():
            continue
        file_name = os.path.basename(member.filename)
        if not file_name:
            continue
        target_path = os.path.join(destination_folder, file_name)
        counter = 1
        original_target_path = target_path
        while os.path.exists(target_path):
            name, ext = os.path.splitext(original_target_path)
            target_path = f"{name} ({counter}){ext}"
            counter += 1
        source = zip_file_object.open(member)
        if member.filename.lower().endswith('.zip'):
            nested_zip_data = io.BytesIO(source.read())
            with zipfile.ZipFile(nested_zip_data, 'r') as nested_zip_ref:
                extraire_et_aplatir_zip(nested_zip_ref, destination_folder)
        else:
            with open(target_path, "wb") as target:
                shutil.copyfileobj(source, target)


def process_files_threaded(client, model, fichiers_paths):
    st.subheader("📊 Progression du Traitement des Fichiers")
    progress_queue = queue.Queue()
    total_paragraphes_total = 0
    progress_placeholders = {
        os.path.basename(p): (st.text(f"⏳ En attente: {os.path.basename(p)}"), st.progress(0))
        for p in fichiers_paths
    }
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(traiter_fichier, client, path, model, progress_queue): os.path.basename(path)
            for path in fichiers_paths
        }
        tasks_done = 0
        total_tasks = len(fichiers_paths)
        while tasks_done < total_tasks:
            try:
                nom_fichier, progress, message = progress_queue.get(timeout=0.1)
                status_text, progress_bar = progress_placeholders[nom_fichier]
                if progress < 0:
                    status_text.error(f"❌ Erreur sur {nom_fichier}")
                    st.error(f"Détail de l'erreur pour '{nom_fichier}': {message}")
                    progress_bar.empty()
                    tasks_done += 1
                else:
                    status_text.text(f"{nom_fichier}: {message}")
                    progress_bar.progress(progress / 100.0)
                    if progress == 100:
                        tasks_done += 1
            except queue.Empty:
                continue
        for future in futures:
            try:
                nb_paras, ocr_utilise = future.result()
                if ocr_utilise:
                    st.session_state.ocr_files.add(futures[future])
                total_paragraphes_total += nb_paras
            except Exception:
                pass
    return total_paragraphes_total

# MODIFIÉ : La fonction utilise maintenant le lien de téléchargement direct
def telecharger_et_indexer_dossier(lien_dossier, client, model):
    with st.status("🚀 Démarrage du processus...", expanded=True) as status:
        try:
            status.update(label="🧹 Nettoyage de la base de données et des anciens fichiers...")
            if client.collections.exists(CLASS_NAME): client.collections.delete(CLASS_NAME)
            client.collections.create(
                name=CLASS_NAME,
                properties=[
                    wvc.Property(name="content", data_type=wvc.DataType.TEXT),
                    wvc.Property(name="source", data_type=wvc.DataType.TEXT)
                ],
                vectorizer_config=wvc.Configure.Vectorizer.none()
            )
            if os.path.exists(FILES_DIRECTORY): shutil.rmtree(FILES_DIRECTORY)
            os.makedirs(FILES_DIRECTORY)
            time.sleep(1)

            status.update(label="📥 Téléchargement du dossier...")
            # MODIFIÉ : Utilise directement le lien du dossier sans le générer
            response = requests.get(lien_dossier, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
            response.raise_for_status()
            
            status.update(label="📦 Décompression intelligente des fichiers...")
            with zipfile.ZipFile(io.BytesIO(response.content), 'r') as zip_ref:
                extraire_et_aplatir_zip(zip_ref, FILES_DIRECTORY)
            
            with st.expander("🔄 Fichiers .doc en cours de conversion", expanded=True):
                convertir_vers_docx(FILES_DIRECTORY)
                if st.session_state.get('conversion_files'):
                    st.success(f"{len(st.session_state.conversion_files)} fichier(s) converti(s) en .docx.")
            
            extensions_valides = (".pdf", ".docx", ".xlsx", ".xls", ".png", ".jpg", ".jpeg", ".bmp", ".tiff")
            all_files_in_dir = os.listdir(FILES_DIRECTORY)
            fichiers_a_traiter_paths = [
                os.path.join(FILES_DIRECTORY, f) 
                for f in all_files_in_dir 
                if f.lower().endswith(extensions_valides) and not f.startswith('~$')
            ]

            if not fichiers_a_traiter_paths:
                status.update(label="⚠️ Aucun fichier compatible trouvé dans le ZIP.", state="complete")
                time.sleep(3)
                st.rerun()
                return

            total_paragraphes = process_files_threaded(client, model, fichiers_a_traiter_paths)
            
            with st.expander("👁️ Fichiers PDF ayant nécessité une lecture OCR", expanded=True):
                if st.session_state.get('ocr_files'):
                    for f in st.session_state.ocr_files: st.write(f"• {f}")
                else: st.info("Aucun PDF n'a nécessité d'OCR.")

            status.update(label=f"🎉 Processus terminé ! {total_paragraphes} paragraphes indexés.", state="complete")
            st.balloons()
            time.sleep(3)
            st.rerun()

        except Exception as e:
            status.update(label=f"❌ Erreur critique : {e}", state="error")


def display_list_view(data, filter_options):
    st.markdown("""
    <style>
    .card:hover { box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06); }
    .badge-en-cours { background-color:#dcfce7; color:#166534; padding: 5px 12px; border-radius: 9999px; font-weight: 600; text-align: center; font-size: 0.875rem; margin-top: 10px; }
    .lot-title { font-size:1.2rem; font-weight:bold; color:#374151; text-align:center; margin:20px 0; padding:10px; background-color:#f9fafb; border-radius:8px; }
    </style>""", unsafe_allow_html=True)
    st.sidebar.header("🔎 Filtres")
    keyword_filter = st.sidebar.text_input("Rechercher par Réf, ID ou Objet")
    # MODIFIÉ : Utilisation des nouvelles options de filtres
    acheteur_filter = st.sidebar.multiselect("Filtrer par Acheteur", options=filter_options["acheteurs"])
    province_filter = st.sidebar.multiselect("Filtrer par Province", options=filter_options["provinces"])
    domaine_filter = st.sidebar.multiselect("Filtrer par Domaine", options=filter_options["domaines"])

    filtered_data = data
    if keyword_filter:
        kw = keyword_filter.lower()
        # MODIFIÉ : La recherche par mot-clé se fait sur les nouveaux champs : _id, reference, objet
        filtered_data = [item for item in filtered_data if kw in str(item.get("_id", "")).lower() or kw in item.get("reference", "").lower() or kw in item.get("objet", "").lower()]
    if acheteur_filter: 
        # MODIFIÉ : Le filtre utilise le champ "acheteur_public"
        filtered_data = [item for item in filtered_data if item.get("acheteur_public") in acheteur_filter]
    if province_filter: 
        # MODIFIÉ : Le filtre utilise la liste de provinces que nous avons créée
        filtered_data = [item for item in filtered_data if any(p in province_filter for p in item.get("provinces_list", []))]
    if domaine_filter: 
        # MODIFIÉ : Le filtre utilise le champ "domaine"
        filtered_data = [item for item in filtered_data if item.get("domaine") in domaine_filter]

    st.title("📄 Appels d'Offres Publics")
    st.write(f"**{len(filtered_data)}** résultat(s) trouvé(s)")
    st.divider()

    ITEMS_PER_PAGE = 10
    total_pages = math.ceil(len(filtered_data) / ITEMS_PER_PAGE) if filtered_data else 1
    if 'page' not in st.session_state or st.session_state.page > total_pages: st.session_state.page = 1
    start_index = (st.session_state.page - 1) * ITEMS_PER_PAGE
    paginated_data = filtered_data[start_index:start_index + ITEMS_PER_PAGE]

    for item in paginated_data:
        # MODIFIÉ : L'identifiant unique pour la clé est maintenant "_id"
        with st.container(border=True, key=str(item.get('_id'))):
            col1, col2 = st.columns([0.8, 0.2])
            with col1:
                # MODIFIÉ : Affiche "acheteur_public" et supprime l'abréviation qui n'existe plus
                st.markdown(f'<h5>{item.get("acheteur_public", "N/A")}</h5>', unsafe_allow_html=True)
                # MODIFIÉ : Utilise "date_publication" avec la fonction de formatage mise à jour
                st.caption(f"Publié le : {format_date(item.get('date_publication'))}")
            with col2: st.markdown('<div class="badge-en-cours">EN COURS</div>', unsafe_allow_html=True)
            st.divider()
            
            # MODIFIÉ : Affichage de l'objet principal car il n'y a plus de "lots"
            st.markdown(f'<div class="lot-title">{item.get("objet", "Non spécifié")}</div>', unsafe_allow_html=True)

            col_info, col_boutons = st.columns([0.7, 0.3])
            # Intérêt du code : Affiche les informations détaillées de chaque appel d'offres.
            with col_info:
                st.markdown(f"""
                <div style="line-height:1.8; font-size:0.95rem;">
                    <span>📋 {item.get("type_procedure", "N/A")}</span><br>
                    <span><strong>Référence :</strong> {item.get("reference", "N/A")}</span><br>
                    <span>📍 {', '.join(item.get("provinces_list", []))}</span><br>
                    <span><strong>Date limite :</strong> {format_date(item.get("date_limite_remise_plis"))}</span><br>
                    <strong style="color: #d9480f;">{jours_restants(item.get('date_limite_remise_plis'))}</strong>
                </div>""", unsafe_allow_html=True)
            with col_boutons:
                # MODIFIÉ : Le bouton de détails utilise le nouveau champ "lien_details"
                st.link_button("🔗 Page de Consultation", item.get("lien_details", "#"), use_container_width=True)
                # MODIFIÉ : Le bouton de traitement utilise "_id" pour sa clé unique
                if st.button("⚙️ Traiter ce Dossier", key=f"process_{item.get('_id')}", use_container_width=True):
                    st.session_state.view = 'process'
                    # On sauvegarde un dictionnaire avec les DEUX liens
                    st.session_state.item_a_traiter = {
                        "details": item.get("lien_details"),
                        "download": item.get("lien_dossier_direct")
                    }
                    st.rerun()
    if total_pages > 1:
        st.divider()
        col_prev, col_input, col_next = st.columns([3, 1, 3])
        if col_prev.button("⬅️ Précédent", disabled=(st.session_state.page <= 1), use_container_width=True):
            st.session_state.page -= 1; st.rerun()
        page_input = col_input.number_input("Page", min_value=1, max_value=total_pages, value=st.session_state.page, key="page_input", label_visibility="collapsed")
        if page_input != st.session_state.page:
            st.session_state.page = page_input; st.rerun()
        if col_next.button("Suivant ➡️", disabled=(st.session_state.page >= total_pages), use_container_width=True):
            st.session_state.page += 1; st.rerun()
        _, col_text_total, _ = st.columns([3, 1, 3])
        col_text_total.markdown(f"<div style='text-align:center;'>sur {total_pages}</div>", unsafe_allow_html=True)

def display_process_view(client, model):
    st.title("⚙️ Traitement et Indexation d'un Appel d'Offres")
    if st.button("⬅️ Retour à la liste"):
        st.session_state.view = 'list'
        if 'lien_a_traiter' in st.session_state: del st.session_state.lien_a_traiter
        st.rerun()
    item_a_traiter = st.session_state.get("item_a_traiter", {})
    lien_details = item_a_traiter.get("details", "Lien non trouvé")
    st.text_input("Lien du dossier à traiter :", value=lien_details, disabled=True)
    
    if st.button("Lancer le Traitement", type="primary"):
        lien_download = item_a_traiter.get("download")
        if lien_download:
            st.session_state.conversion_files = []
            st.session_state.ocr_files = set()
            # MODIFIÉ : Appel de la fonction avec le lien direct
            telecharger_et_indexer_dossier(lien_download, client, model)
        else: st.error("Aucun lien à traiter.")
            
    st.divider()
    st.header("📊 État de la base de données")
    col1, col2 = st.columns(2)
    fichiers_locaux = 0
    if os.path.exists(FILES_DIRECTORY):
        fichiers_locaux = len([f for f in os.listdir(FILES_DIRECTORY) if f.lower().endswith((".pdf", ".docx", ".xlsx", ".xls"))])
    col1.metric(label="📄 Fichiers Locaux Prêts", value=fichiers_locaux)
    
    total_paragraphs = 0
    if client.collections.exists(CLASS_NAME):
        doc_collection = client.collections.get(CLASS_NAME)
        response = doc_collection.aggregate.over_all(total_count=True)
        total_paragraphs = response.total_count
    col2.metric(label="✍️ Paragraphes dans Weaviate", value=total_paragraphs)
    
    st.divider()
    st.header("🔎 Rechercher dans les documents")
    requete_utilisateur = st.text_input("Que cherchez-vous ?", "Fourniture de bureau")
    if st.button("Lancer la recherche"):
        if requete_utilisateur and total_paragraphs > 0:
            vecteur_requete = model.encode(requete_utilisateur).tolist()
            doc_collection = client.collections.get(CLASS_NAME)
            response = doc_collection.query.near_vector(near_vector=vecteur_requete, limit=5, return_metadata=wq.MetadataQuery(distance=True))
            st.subheader("Résultats de la recherche :")
            if not response.objects: st.warning("Aucun résultat trouvé.")
            else:
                for item in response.objects:
                    st.info(f"**Pertinence (distance) :** {item.metadata.distance:.4f} (plus c'est bas, mieux c'est)")
                    st.write(f"📄 **Source** : {item.properties.get('source', 'Inconnue')}")
                    st.write(f"📌 **Paragraphe** : {item.properties.get('content', '')}")
                    st.divider()
        elif not requete_utilisateur: st.warning("Veuillez entrer une requête de recherche.")
        else: st.warning("La base de données est vide. Veuillez d'abord traiter un dossier.")

# --- Exécution Principale ---
if 'view' not in st.session_state: st.session_state.view = 'list'
if 'page' not in st.session_state: st.session_state.page = 1

load_dotenv()
data, filter_options = load_data_from_mongo()
model = load_model()

try:
    with weaviate.connect_to_local(port=8080, grpc_port=50051) as client:
        if st.session_state.view == 'list':
            display_list_view(data, filter_options)
        elif st.session_state.view == 'process':
            display_process_view(client, model)
except Exception as e:
    st.error(f"Erreur critique de connexion à Weaviate : {e}")
    st.info("Veuillez vous assurer que votre instance Weaviate est bien en cours d'exécution sur le port 8080.")