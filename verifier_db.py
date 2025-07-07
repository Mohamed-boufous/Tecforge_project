import weaviate
import os
import random

# --- Configuration ---
CLASS_NAME = "PDFParagraph"
PDFS_DIRECTORY = os.path.join(os.path.dirname(__file__), "pdfs")

# 1. Lister tous les fichiers PDF locaux
try:
    local_files = {f for f in os.listdir(PDFS_DIRECTORY) if f.lower().endswith(".pdf")}
    print(f"✅ {len(local_files)} fichier(s) PDF trouvés dans le dossier local.")
except FileNotFoundError:
    print(f"🔴 Erreur : Le dossier '{PDFS_DIRECTORY}' n'a pas été trouvé.")
    local_files = set()

# 2. Connexion à Weaviate et vérification
try:
    with weaviate.connect_to_local(port=8080, grpc_port=50051) as client:
        print("✅ Connexion à Weaviate réussie.")

        if not client.collections.exists(CLASS_NAME):
            print(f"🔴 La collection '{CLASS_NAME}' n'existe pas. Aucune donnée à vérifier.")
        else:
            pdf_collection = client.collections.get(CLASS_NAME)

            sources_in_weaviate = set()
            objets_weaviate = []

            for item in pdf_collection.iterator(include_vector=True): 
                sources_in_weaviate.add(item.properties['source'])
                objets_weaviate.append(item) 

            print(f"✅ {len(objets_weaviate)} objets trouvés dans Weaviate.")
            print(f"✅ {len(sources_in_weaviate)} source(s) de document unique(s).")

            # --- Vérification ---
            print("\n--- RÉSULTAT DE LA VÉRIFICATION ---")
            missing_in_weaviate = local_files - sources_in_weaviate
            extra_in_weaviate = sources_in_weaviate - local_files

            if not missing_in_weaviate:
                print("✅ Tous les fichiers PDF locaux sont bien présents dans Weaviate.")
            else:
                print(f"🔴 {len(missing_in_weaviate)} fichier(s) manquant(s) dans Weaviate : {missing_in_weaviate}")

            if extra_in_weaviate:
                print(f"🟡 {len(extra_in_weaviate)} source(s) existe(nt) en trop dans Weaviate : {extra_in_weaviate}")

            # --- Visualisation de quelques exemples ---
            print("\n--- EXEMPLES DE VECTEURS ---")
            
            objets_avec_vecteur = [item for item in objets_weaviate if item.vector]

            if not objets_avec_vecteur:
                print("🟡 Aucun objet avec un vecteur trouvé à afficher.")
            else:
                nb_exemples = min(5, len(objets_avec_vecteur))
                exemples = random.sample(objets_avec_vecteur, nb_exemples)
                
                print(f"Affichage de {nb_exemples} exemple(s) aléatoire(s) avec vecteurs :")
                for idx, item in enumerate(exemples, 1):
                    source = item.properties.get('source', 'Inconnue')
                    content = item.properties.get('content', '')[:80].replace("\n", " ") + '...'
                    
                    # CORRECTION: On accède au vecteur via la clé 'default' avant de le découper.
                    vector_sample = item.vector['default'][:5] 
                    
                    print(f"Exemple {idx}:")
                    print(f"   📄 Source     : {source}")
                    print(f"   📌 Paragraphe: {content}")
                    print(f"   🔑 Vecteur    : {vector_sample}")
                    print("-" * 40)

except Exception as e:
    print(f"❌ Une erreur est survenue : {e}")