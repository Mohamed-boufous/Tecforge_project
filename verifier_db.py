import weaviate
import os

# --- Configuration ---
CLASS_NAME = "PDFParagraph"
PDFS_DIRECTORY = "./pdfs"

# 1. Lister tous les fichiers PDF sur votre disque dur
try:
    local_files = {f for f in os.listdir(PDFS_DIRECTORY) if f.lower().endswith(".pdf")}
    print(f"Trouvé {len(local_files)} fichier(s) PDF dans le dossier local.")
except FileNotFoundError:
    print(f"Erreur : Le dossier '{PDFS_DIRECTORY}' n'a pas été trouvé.")
    local_files = set()

# --- Connexion à Weaviate ---
try:
    with weaviate.connect_to_local(port=8080, grpc_port=50051) as client:
        print("Connexion à Weaviate réussie.")
        
        # Vérifier si la collection existe
        if not client.collections.exists(CLASS_NAME):
            print(f"La collection '{CLASS_NAME}' n'existe pas. Aucune donnée à vérifier.")
        else:
            pdf_collection = client.collections.get(CLASS_NAME)
            
            # 2. Récupérer toutes les sources distinctes de Weaviate
            sources_in_weaviate = set()
            # L'itérateur parcourt tous les objets sans surcharger la mémoire
            for item in pdf_collection.iterator():
                sources_in_weaviate.add(item.properties['source'])
            
            print(f"Trouvé {len(sources_in_weaviate)} source(s) de document dans Weaviate.")

            # 3. Comparer les deux listes
            print("\n--- RÉSULTAT DE LA VÉRIFICATION ---")
            
            # Fichiers qui sont sur le disque mais pas dans Weaviate
            missing_in_weaviate = local_files - sources_in_weaviate
            if not missing_in_weaviate:
                print("✅ Tous les fichiers PDF locaux sont bien présents dans Weaviate.")
            else:
                print(f"🔴 {len(missing_in_weaviate)} fichier(s) manquant(s) dans Weaviate :")
                for f in missing_in_weaviate:
                    print(f"   - {f}")
            
            # Fichiers qui sont dans Weaviate mais plus sur le disque (optionnel)
            extra_in_weaviate = sources_in_weaviate - local_files
            if extra_in_weaviate:
                print(f"\n🟡 Information : {len(extra_in_weaviate)} source(s) existe(nt) dans Weaviate mais plus dans le dossier local :")
                for f in extra_in_weaviate:
                    print(f"   - {f}")

except Exception as e:
    print(f"\nUne erreur est survenue : {e}")