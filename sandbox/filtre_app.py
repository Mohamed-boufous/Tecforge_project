import streamlit as st
import json
import math
from datetime import datetime, timezone

# --- Configuration de la Page ---
st.set_page_config(layout="wide", page_title="Filtre d'Appels d'Offres")

# --- Fonctions ---

@st.cache_data
def load_and_prepare_data(file_path):
    """
    Charge les données et prépare les listes de filtres en une seule fois.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        st.error(f"Le fichier '{file_path}' est introuvable. Assurez-vous qu'il est dans le même dossier que le script.")
        return [], {}
    except json.JSONDecodeError:
        st.error(f"Erreur de décodage du fichier JSON. Vérifiez que le fichier '{file_path}' est valide.")
        return [], {}

    acheteurs = set()
    provinces = set()
    domaines = set()

    for item in data:
        if item.get("acheteur"):
            acheteurs.add(item["acheteur"])
        if isinstance(item.get("provinces"), list):
            provinces.update(item["provinces"])
        if isinstance(item.get("domains"), list):
            for domain_item in item["domains"]:
                if domain_item.get("domain"):
                    domaines.add(domain_item["domain"])

    filter_options = {
        "acheteurs": sorted(list(acheteurs)),
        "provinces": sorted(list(provinces)),
        "domaines": sorted(list(domaines))
    }
    
    return data, filter_options

def format_date(date_string):
    """Formate une date ISO en format lisible."""
    if not date_string:
        return "N/A"
    try:
        dt_object = datetime.fromisoformat(date_string.replace('Z', '+00:00'))
        return dt_object.strftime("%A %d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return "Date invalide"

def jours_restants(date_string):
    """Calcule le nombre de jours restants avant une date."""
    if not date_string:
        return ""
    try:
        now = datetime.now(timezone.utc)
        end_date = datetime.fromisoformat(date_string.replace('Z', '+00:00'))
        delta = end_date - now
        if delta.days >= 0:
            return f"⏳ Il reste {delta.days} jour(s)"
        else:
            return "Terminé"
    except (ValueError, TypeError):
        return ""

# --- Interface Utilisateur ---

# MODIFIÉ : Injection de CSS pour un style plus proche de l'image
st.markdown("""
<style>
    .card {
        background-color: #ffffff;
        border: 1px solid #e0e0e0;
        border-radius: 10px;
        padding: 25px;
        margin-bottom: 25px; /* Espace entre les cartes */
        box-shadow: 0 4px 8px rgba(0,0,0,0.05);
    }
    /* MODIFIÉ : Nouveau style pour l'en-tête de la carte */
    .card-header {
        font-size: 1.4rem;
        font-weight: bold;
        color: #1e3a8a; /* Bleu foncé */
        margin-bottom: 10px;
    }
    .lot-object {
        font-size: 1.2rem;
        font-weight: bold;
        color: #374151;
        text-align: center;
        margin-top: 20px;
        margin-bottom: 20px;
        padding: 10px;
        background-color: #f9fafb; /* Fond légèrement gris */
        border-radius: 8px;
    }
    .info-text {
        color: #4b5563;
        font-size: 0.95rem;
        line-height: 1.8; /* Espace entre les lignes */
    }
    .status-badge {
        background-color: #dcfce7;
        color: #166534;
        padding: 5px 12px;
        border-radius: 15px;
        font-weight: bold;
        font-size: 0.9rem;
        text-align: center;
        float: right; /* Aligner à droite */
    }
    /* MODIFIÉ : Style pour la pagination */
    .pagination-container {
        display: flex;
        justify-content: center;
        align-items: center;
        padding: 15px;
        background-color: #ffffff;
        border-radius: 10px;
        margin-top: 20px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
</style>
""", unsafe_allow_html=True)

# --- Chargement des Données ---
data, filter_options = load_and_prepare_data("resultats_uniques.json")

# --- Barre Latérale avec les Filtres ---
st.sidebar.header("🔎 Filtres")

if not data:
    st.warning("Aucune donnée à afficher. Vérifiez votre fichier JSON.")
else:
    if 'page' not in st.session_state:
        st.session_state.page = 1

    # Champs de filtrage
    keyword_filter = st.sidebar.text_input("Rechercher par Réf, ID ou Objet")
    acheteur_filter = st.sidebar.multiselect("Filtrer par Acheteur", options=filter_options["acheteurs"])
    province_filter = st.sidebar.multiselect("Filtrer par Province", options=filter_options["provinces"])
    domaine_filter = st.sidebar.multiselect("Filtrer par Domaine", options=filter_options["domaines"])

    # --- Logique de Filtrage Optimisée ---
    filtered_data = data

    # MODIFIÉ : La recherche par mot-clé inclut la référence et l'ID
    if keyword_filter:
        keyword_lower = keyword_filter.lower()
        filtered_data = [
            item for item in filtered_data
            if keyword_lower in str(item.get("consId", "")).lower()
            or keyword_lower in item.get("reference", "").lower()
            or any(keyword_lower in lot.get("lotObject", "").lower() for lot in item.get("lots", []))
        ]

    if acheteur_filter:
        filtered_data = [item for item in filtered_data if item.get("acheteur") in acheteur_filter]
    if province_filter:
        filtered_data = [item for item in filtered_data if any(p in province_filter for p in item.get("provinces", []))]
    if domaine_filter:
        filtered_data = [item for item in filtered_data if any(d.get("domain") in domaine_filter for d in item.get("domains", []))]

    # --- Affichage Principal ---
    st.title("📄 Appels d'Offres Publics")
    st.write(f"**{len(filtered_data)}** résultat(s) trouvé(s)")
    st.divider()

    # --- Logique de Pagination ---
    ITEMS_PER_PAGE = 10
    total_items = len(filtered_data)
    total_pages = math.ceil(total_items / ITEMS_PER_PAGE) if total_items > 0 else 1

    if st.session_state.page > total_pages:
        st.session_state.page = 1
    
    start_index = (st.session_state.page - 1) * ITEMS_PER_PAGE
    end_index = start_index + ITEMS_PER_PAGE
    paginated_data = filtered_data[start_index:end_index]

    # --- Affichage des cartes redessinées ---
    for item in paginated_data:
        # MODIFIÉ : En-tête de la carte avec AchAbr et acheteur
        st.markdown(f'<p class="card-header">{item.get("AchAbr", "")} - {item.get("acheteur", "N/A")}</p>', unsafe_allow_html=True)
        
        with st.container():
            
            
            # Ligne du haut : Date de publication et statut
            col_date, col_statut = st.columns([0.7, 0.3])
            with col_date:
                st.write(f"Publié le : {format_date(item.get('publishedDate'))}")
            with col_statut:
                st.markdown('<div class="status-badge">EN COURS</div>', unsafe_allow_html=True)
            
            st.divider()

            # Ligne principale : Informations et boutons
            col_info, col_boutons = st.columns([0.7, 0.3])
            with col_info:
                st.markdown(f"""
                <div class="info-text">
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
                st.link_button("📥 Télécharger le Dossier", item.get("urldossierDirect", "#"), use_container_width=True)
            
            # Section des lots
            for lot in item.get("lots", []):
                st.markdown(f'<p class="lot-object">{lot.get("lotObject", "Non spécifié")}</p>', unsafe_allow_html=True)
                
                lot_col1, lot_col2, lot_col3 = st.columns(3)
                lot_col1.metric("Catégorie", lot.get("lotCategory", "N/A"))
                lot_col2.metric("Estimation", f"{lot.get('lotEstimation', 0):,.2f} MAD".replace(",", " "))
                lot_col3.metric("Caution", f"{lot.get('lotCaution', 0):,.2f} MAD".replace(",", " "))

            st.markdown('</div>', unsafe_allow_html=True)
        
    st.divider()

    # --- Contrôles de Pagination Stylisés ---
    if total_pages > 1:
        st.markdown('<div class="pagination-container">', unsafe_allow_html=True)
        
        col_prev, col_page, col_next = st.columns([3, 1, 3])

        if col_prev.button("⬅️ Précédent", disabled=(st.session_state.page <= 1), use_container_width=True):
            st.session_state.page -= 1
            st.rerun()

        col_page.write(f"<div style='text-align: center; margin-top: 8px;'><b>{st.session_state.page} / {total_pages}</b></div>", unsafe_allow_html=True)

        if col_next.button("Suivant ➡️", disabled=(st.session_state.page >= total_pages), use_container_width=True):
            st.session_state.page += 1
            st.rerun()
            
        st.markdown('</div>', unsafe_allow_html=True)
