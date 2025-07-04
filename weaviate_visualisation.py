from sentence_transformers import SentenceTransformer
import weaviate
# L'import 'os' n'était pas utilisé.

CLASS_NAME = "PDFParagraph"
model = SentenceTransformer("BAAI/bge-base-en-v1.5")

def lister_objets(pdf_collection, limit=5):
    # CORRECTION : Il faut ajouter 'include_vector=True' pour que le vecteur soit retourné.
    result = pdf_collection.query.fetch_objects(
        limit=limit,
        include_vector=True
    )
    if not result.objects:
        print("Aucun objet trouvé.")
    else:
        for obj in result.objects:
            print(f"Source : {obj.properties.get('source', 'N/A')}")
            print(f"Content : {obj.properties.get('content', '')[:100]}...")
            # On vérifie que le vecteur existe avant de l'afficher
            if obj.vector:
                print(f"Vector (5 premiers éléments) : {list(obj.vector.values())[:5]} ...")
            print("-" * 50)

def recherche_vectorielle(pdf_collection, texte, limit=3):
    # OPTIMISATION : Pas besoin de mettre le texte dans une liste pour 'encode'.
    query_vector = model.encode(texte)
    result = pdf_collection.query.near_vector(
        near_vector=query_vector.tolist(),
        limit=limit,
        return_metadata=["distance"] # On demande explicitement la distance
    )
    if not result.objects:
        print("Aucun résultat trouvé pour cette recherche.")
    else:
        for obj in result.objects:
            print(f"Source : {obj.properties.get('source', 'N/A')}")
            print(f"Content : {obj.properties.get('content', '')[:100]}...")
            # CORRECTION : La distance se trouve dans les métadonnées de l'objet.
            if obj.metadata:
                print(f"Distance : {obj.metadata.distance:.4f}") # :.4f pour un affichage plus propre
            print("-" * 50)

if __name__ == "__main__":
    with weaviate.connect_to_local(port=8080, grpc_port=50051) as client:
        if not client.collections.exists(CLASS_NAME):
            print(f"La collection {CLASS_NAME} n'existe pas.")
        else:
            pdf_collection = client.collections.get(CLASS_NAME)
            
            while True:
                print("\n=== MENU ===")
                print("1. Lister les objets stockés")
                print("2. Faire une recherche vectorielle")
                print("3. Quitter")
                choix = input("Votre choix : ").strip()
                
                if choix == "1":
                    limit = input("Combien d'objets voulez-vous lister ? (défaut 5) : ").strip()
                    limit = int(limit) if limit.isdigit() else 5
                    lister_objets(pdf_collection, limit)
                
                elif choix == "2":
                    texte = input("Entrez votre texte de recherche : ").strip()
                    if texte:
                        limit = input("Combien de résultats voulez-vous ? (défaut 3) : ").strip()
                        limit = int(limit) if limit.isdigit() else 3
                        recherche_vectorielle(pdf_collection, texte, limit)
                    else:
                        print("Texte vide, recherche annulée.")
                
                elif choix == "3":
                    print("Au revoir !")
                    break
                
                else:
                    print("Choix non reconnu.")