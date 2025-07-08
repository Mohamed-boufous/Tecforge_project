import weaviate
import os
import random

# --- Configuration ---
CLASS_NAME = "DocumentParagraph" 
FILES_DIRECTORY = os.path.join(os.path.dirname(__file__), "documents")

# 1. Lister tous les fichiers locaux compatibles
try:
    local_files = {f for f in os.listdir(FILES_DIRECTORY) if f.lower().endswith((".pdf", ".docx", ".xlsx"))}
    print(f"✅ {len(local_files)} fichier(s) trouvé(s) dans le dossier local.")
except FileNotFoundError:
    print(f"🔴 Erreur : Le dossier '{FILES_DIRECTORY}' n'a pas été trouvé.")
    local_files = set()

# 2. Connexion à Weaviate et vérification
try:
    with weaviate.connect_to_local(port=8080, grpc_port=50051) as client:
        print("✅ Connexion à Weaviate réussie.")

        if not client.collections.exists(CLASS_NAME):
            print(f"🔴 La collection '{CLASS_NAME}' n'existe pas. Aucune donnée à vérifier.")
        else:
            doc_collection = client.collections.get(CLASS_NAME)

            # --- CORRECTION : Remplacement de l'iterator ---
            # Commentaire : On utilise fetch_objects pour récupérer les objets et leurs vecteurs de manière plus fiable.
            response = doc_collection.query.fetch_objects(
                limit=5000, # Commentaire : Fixez une limite assez haute pour récupérer tous vos objets.
                include_vector=True
            )
            objets_weaviate = response.objects
            # --- FIN DE LA CORRECTION ---

            # On reconstruit l'ensemble des sources à partir des objets récupérés
            sources_in_weaviate = {item.properties['source'] for item in objets_weaviate}
            
            print(f"✅ {len(objets_weaviate)} objets trouvés dans Weaviate.")
            print(f"✅ {len(sources_in_weaviate)} source(s) de document unique(s).")

            # --- Vérification de la synchronisation ---
            print("\n--- RÉSULTAT DE LA VÉRIFICATION ---")
            missing_in_weaviate = local_files - sources_in_weaviate
            extra_in_weaviate = sources_in_weaviate - local_files

            if not missing_in_weaviate:
                print("✅ Tous les fichiers locaux sont bien présents dans Weaviate.")
            else:
                print(f"🔴 {len(missing_in_weaviate)} fichier(s) manquant(s) dans Weaviate : {missing_in_weaviate}")

            if not extra_in_weaviate:
                print("✅ Aucune source en trop dans Weaviate.")
            else:
                print(f"🟡 {len(extra_in_weaviate)} source(s) existe(nt) en trop dans Weaviate : {extra_in_weaviate}")

            # --- Visualisation de quelques exemples ---
            print("\n--- EXEMPLES DE VECTEURS ---")

            # Ce bloc fonctionnera maintenant car les vecteurs sont chargés.
            objets_avec_vecteur = [item for item in objets_weaviate if item.vector]

            if not objets_avec_vecteur:
                print("🟡 Aucun objet avec un vecteur trouvé. Vérifiez votre script d'indexation.")
            else:
                nb_exemples = min(5, len(objets_avec_vecteur))
                exemples = random.sample(objets_avec_vecteur, nb_exemples)
                
                print(f"Affichage de {nb_exemples} exemple(s) aléatoire(s) :")
                for idx, item in enumerate(exemples, 1):
                    source = item.properties.get('source', 'Inconnue')
                    content = item.properties.get('content', '')[:80].replace("\n", " ") + '...'
                    
                    # Accès au vecteur via sa clé 'default'
                    vector_sample = item.vector['default'][:5] 
                    
                    print(f"Exemple {idx}:")
                    print(f"   📄 Source      : {source}")
                    print(f"   📌 Paragraphe  : {content}")
                    print(f"   🔑 Vecteur     : {vector_sample}")
                    print("-" * 40)

except Exception as e:
    print(f"❌ Une erreur est survenue : {e}")