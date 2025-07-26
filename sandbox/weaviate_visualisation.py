from sentence_transformers import SentenceTransformer
import weaviate
import weaviate.classes.query as wq # Ajout de l'import pour les métadonnées

# --- Initialisation ---
# MODIFIÉ : Le nom de la classe doit correspondre à celui utilisé lors de l'indexation.
CLASS_NAME = "DocumentParagraph"
model = SentenceTransformer("BAAI/bge-base-en-v1.5")

def lister_objets(doc_collection, limit=5):
    """
    Cette fonction récupère et affiche un nombre limité d'objets
    stockés dans votre collection Weaviate.
    """
    # On récupère les objets de la collection.
    result = doc_collection.query.fetch_objects(
        limit=limit,
        include_vector=True # Important pour que le vecteur soit retourné.
    )
    if not result.objects:
        print("Aucun objet trouvé.")
    else:
        print(f"\n--- Affichage de {len(result.objects)} objet(s) ---")
        for obj in result.objects:
            print(f"Source : {obj.properties.get('source', 'N/A')}")
            print(f"Content : {obj.properties.get('content', '')[:100]}...")
            # On vérifie que le vecteur existe avant de l'afficher.
            if obj.vector:
                # MODIFIÉ : Le vecteur par défaut est stocké sous la clé 'default'.
                vector_preview = obj.vector.get('default', [])[:5]
                print(f"Vecteur (5 premiers éléments) : {vector_preview} ...")
            print("-" * 50)

def recherche_vectorielle(doc_collection, texte, limit=3):
    """
    Cette fonction vectorise un texte de recherche et trouve les objets
    les plus similaires dans Weaviate.
    """
    # On transforme le texte de la requête en vecteur.
    query_vector = model.encode(texte)
    
    # On effectue la recherche par similarité vectorielle.
    result = doc_collection.query.near_vector(
        near_vector=query_vector.tolist(),
        limit=limit,
        return_metadata=wq.MetadataQuery(distance=True) # On demande la distance pour mesurer la similarité.
    )
    
    if not result.objects:
        print("Aucun résultat trouvé pour cette recherche.")
    else:
        print(f"\n--- {len(result.objects)} résultat(s) trouvé(s) ---")
        for obj in result.objects:
            print(f"Source : {obj.properties.get('source', 'N/A')}")
            print(f"Content : {obj.properties.get('content', '')[:100]}...")
            # La distance se trouve dans les métadonnées de l'objet.
            if obj.metadata:
                # MODIFIÉ : Accès correct à la distance via obj.metadata.distance.
                print(f"Distance : {obj.metadata.distance:.4f} (plus c'est bas, mieux c'est)")
            print("-" * 50)

if __name__ == "__main__":
    # La connexion à Weaviate est gérée par le bloc 'with'.
    with weaviate.connect_to_local(port=8080, grpc_port=50051) as client:
        print("✅ Connexion à Weaviate réussie.")
        
        # On vérifie si la collection existe avant de continuer.
        if not client.collections.exists(CLASS_NAME):
            print(f"🔴 La collection '{CLASS_NAME}' n'existe pas. Veuillez d'abord exécuter le script d'indexation.")
        else:
            # On récupère l'objet de la collection pour l'utiliser dans les fonctions.
            doc_collection = client.collections.get(CLASS_NAME)
            
            # Boucle du menu interactif.
            while True:
                print("\n=== MENU ===")
                print("1. Lister les objets stockés")
                print("2. Faire une recherche vectorielle")
                print("3. Quitter")
                choix = input("Votre choix : ").strip()
                
                if choix == "1":
                    limit_input = input("Combien d'objets voulez-vous lister ? (défaut 5) : ").strip()
                    limit = int(limit_input) if limit_input.isdigit() else 5
                    lister_objets(doc_collection, limit)
                
                elif choix == "2":
                    texte_input = input("Entrez votre texte de recherche : ").strip()
                    if texte_input:
                        limit_input = input("Combien de résultats voulez-vous ? (défaut 3) : ").strip()
                        limit = int(limit_input) if limit_input.isdigit() else 3
                        recherche_vectorielle(doc_collection, texte_input, limit)
                    else:
                        print("Texte vide, recherche annulée.")
                
                elif choix == "3":
                    print("Au revoir !")
                    break
                
                else:
                    print("Choix non reconnu.")
