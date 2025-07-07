import streamlit as st
import weaviate
import weaviate.classes as wvc
from sentence_transformers import SentenceTransformer
import os
import random

# --- Configuration ---
NOM_DU_MODELE_DE_VECTEUR = 'BAAI/bge-base-en-v1.5'
CLASS_NAME = "PDFParagraph"
# Le chemin vers le dossier contenant les PDFs
PDFS_DIRECTORY = os.path.join(os.path.dirname(__file__), "pdfs")

try:
    # MODIFIÉ : On met le chargement du modèle dans une fonction avec un cache.
    # L'intérêt est de ne charger ce gros modèle qu'une seule fois au démarrage de l'app,
    # ce qui la rend beaucoup plus rapide lors des interactions.
    @st.cache_resource
    def load_model():
        return SentenceTransformer(NOM_DU_MODELE_DE_VECTEUR)

    model = load_model()

    # MODIFIÉ : C'est la nouvelle façon de se connecter à une instance Weaviate locale.
    # L'ancienne méthode `weaviate.Client(...)` n'est plus valide.
    client = weaviate.connect_to_local()

    st.title("📂 Vérification et Recherche dans Weaviate")

    # --- Partie 1: Vérification des fichiers ---
    st.header("Vérification de la synchronisation")

    try:
        local_files = {f for f in os.listdir(PDFS_DIRECTORY) if f.lower().endswith(".pdf")}
        st.success(f"{len(local_files)} fichier(s) PDF trouvés dans le dossier local.")
    except FileNotFoundError:
        local_files = set()
        st.error(f"Le dossier '{PDFS_DIRECTORY}' n'a pas été trouvé.")

    if not client.collections.exists(CLASS_NAME):
        st.error(f"La collection '{CLASS_NAME}' n'existe pas dans Weaviate.")
    else:
        pdf_collection = client.collections.get(CLASS_NAME)

        sources_in_weaviate = set()
        
        # MODIFIÉ : On ne demande que la propriété 'source' pour que ce soit plus rapide,
        # car on n'a pas besoin du contenu ou du vecteur pour cette vérification.
        for item in pdf_collection.iterator(return_properties=['source']):
            sources_in_weaviate.add(item.properties.get('source', 'Inconnue'))

        st.success(f"{len(sources_in_weaviate)} source(s) de document unique(s) trouvées dans Weaviate.")

        missing_in_weaviate = local_files - sources_in_weaviate
        extra_in_weaviate = sources_in_weaviate - local_files

        if not missing_in_weaviate:
            st.success("✅ Tous les fichiers PDF locaux sont bien présents dans Weaviate.")
        else:
            st.error(f"❌ {len(missing_in_weaviate)} fichier(s) manquant(s) dans Weaviate : {missing_in_weaviate}")

        if extra_in_weaviate:
            st.warning(f"⚠️ {len(extra_in_weaviate)} source(s) existe(nt) en trop dans Weaviate : {extra_in_weaviate}")

    # --- Partie 2: Recherche ---
    st.header("💬 Recherche vectorielle")
    requete_utilisateur = st.text_input("Entrez votre requête textuelle :", "Appel d'offres")

    if st.button("Lancer la recherche"):
        if not requete_utilisateur:
            st.warning("Veuillez entrer un texte à rechercher.")
        else:
            vecteur_requete = model.encode(requete_utilisateur).tolist()
            resultat = pdf_collection.query.near_vector(
                near_vector=vecteur_requete,
                limit=5,
                return_metadata=wvc.query.MetadataQuery(certainty=True)
            )
            
            st.subheader("Résultats de la recherche :")
            if not resultat.objects:
                st.warning("Aucun résultat trouvé.")
            else:
                for item in resultat.objects:
                    certitude = item.metadata.certainty * 100
                    st.info(f"**Certitude :** {certitude:.2f}%")
                    st.write(f"📄 **Source** : {item.properties.get('source', 'Inconnue')}")
                    st.write(f"📌 **Paragraphe** : {item.properties.get('content', '')}")
                    st.divider()

except Exception as e:
    st.error(f"Une erreur est survenue : {e}")

finally:
    # MODIFIÉ : C'est une bonne pratique de toujours fermer la connexion à la fin.
    if 'client' in locals() and client.is_connected():
        client.close()
