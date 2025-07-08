import streamlit as st
import weaviate
import weaviate.classes.query as wq  # Modification : import plus spécifique pour la clarté
from sentence_transformers import SentenceTransformer
import os

# --- Configuration (Corrigée pour être cohérente) ---
NOM_DU_MODELE_DE_VECTEUR = 'BAAI/bge-base-en-v1.5'
# Commentaire : Le nom de la classe est maintenant celui que nous utilisons partout.
CLASS_NAME = "DocumentParagraph"
# Commentaire : Le nom du dossier est maintenant celui que nous utilisons partout.
FILES_DIRECTORY = os.path.join(os.path.dirname(__file__), "documents")

# --- Fonctions ---
# Commentaire : Le cache est une excellente pratique, on le garde.
# Il accélère l'application en ne chargeant le modèle qu'une seule fois.
@st.cache_resource
def load_model():
    """Charge le modèle de vectorisation une seule fois."""
    return SentenceTransformer(NOM_DU_MODELE_DE_VECTEUR)

# --- Application Principale ---
try:
    # On charge le modèle et on met le titre de la page
    model = load_model()
    st.title("📂 Recherche et Vérification de Documents")

    # Commentaire : Le bloc 'with' gère automatiquement la connexion et la déconnexion.
    # C'est plus simple et plus sûr que le bloc try/finally.
    with weaviate.connect_to_local(port=8080, grpc_port=50051) as client:
        st.success("✅ Connecté à Weaviate !")

        # --- Partie 1: Vérification des fichiers ---
        st.header("Vérification de la synchronisation")

        try:
            # Commentaire : On cherche maintenant tous les types de fichiers compatibles.
            local_files = {f for f in os.listdir(FILES_DIRECTORY) if f.lower().endswith((".pdf", ".docx", ".xlsx"))}
            st.info(f"{len(local_files)} fichier(s) trouvé(s) dans le dossier local.")
        except FileNotFoundError:
            local_files = set()
            st.error(f"Le dossier '{FILES_DIRECTORY}' n'a pas été trouvé.")

        if not client.collections.exists(CLASS_NAME):
            st.error(f"La collection '{CLASS_NAME}' n'existe pas dans Weaviate.")
        else:
            doc_collection = client.collections.get(CLASS_NAME)
            
            # Récupère toutes les sources uniques de la collection
            response = doc_collection.query.fetch_objects(limit=10000, return_properties=['source'])
            sources_in_weaviate = {item.properties['source'] for item in response.objects}

            # --- Affichage des résultats de la vérification ---
            missing_in_weaviate = local_files - sources_in_weaviate
            extra_in_weaviate = sources_in_weaviate - local_files

            if not missing_in_weaviate:
                st.success("✅ Tous les fichiers locaux sont bien présents dans Weaviate.")
            else:
                st.error(f"❌ {len(missing_in_weaviate)} fichier(s) manquant(s) dans Weaviate : {missing_in_weaviate}")

            if extra_in_weaviate:
                st.warning(f"⚠️ {len(extra_in_weaviate)} source(s) existe(nt) en trop dans Weaviate : {extra_in_weaviate}")

        st.divider() # Ajoute une ligne de séparation visuelle

        # --- Partie 2: Recherche ---
        st.header("💬 Recherche Sémantique")
        requete_utilisateur = st.text_input("Que cherchez-vous ?", "Fourniture de bureau")

        if st.button("Lancer la recherche"):
            if not requete_utilisateur:
                st.warning("Veuillez entrer un texte à rechercher.")
            else:
                # Vectorisation de la requête de l'utilisateur
                vecteur_requete = model.encode(requete_utilisateur).tolist()
                
                # Récupération de la collection (au cas où elle n'était pas définie avant)
                doc_collection = client.collections.get(CLASS_NAME)

                # Commentaire : C'est la recherche par similarité vectorielle.
                response = doc_collection.query.near_vector(
                    near_vector=vecteur_requete,
                    limit=5,
                    # Commentaire : On demande la 'distance'. Plus elle est proche de 0, plus le résultat est similaire.
                    return_metadata=wq.MetadataQuery(distance=True)
                )
                
                st.subheader("Résultats de la recherche :")
                if not response.objects:
                    st.warning("Aucun résultat trouvé.")
                else:
                    for item in response.objects:
                        # Commentaire : On récupère et affiche la distance.
                        distance = item.metadata.distance
                        st.info(f"**Distance :** {distance:.4f} (plus c'est bas, mieux c'est)")
                        st.write(f"📄 **Source** : {item.properties.get('source', 'Inconnue')}")
                        st.write(f"📌 **Paragraphe** : {item.properties.get('content', '')}")
                        st.divider()

except Exception as e:
    st.error(f"Une erreur critique est survenue : {e}")