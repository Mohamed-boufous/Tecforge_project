import os
import win32com.client as win32
from pathlib import Path

# Le script cherchera un dossier nommé "documents" au même endroit que lui.
CHEMIN_DU_DOSSIER = os.path.join(os.path.dirname(__file__), "documents")

def convertir_et_supprimer(chemin_dossier):
    """
    Parcourt un dossier, convertit les .doc en .docx ET SUPPRIME les originaux.
    """
    word = None
    try:
        word = win32.DispatchEx("Word.Application")
    except Exception as e:
        print("Erreur : Microsoft Word n'est pas installé ou un problème est survenu.")
        print(e)
        return

    word.Visible = False

    try:
        if not os.path.exists(chemin_dossier):
            os.makedirs(chemin_dossier)
            print(f"Dossier '{chemin_dossier}' créé, car il n'existait pas.")

        print(f"Scan du dossier : {chemin_dossier}")
        for nom_fichier in os.listdir(chemin_dossier):
            if nom_fichier.lower().endswith(".doc"):
                
                chemin_doc = os.path.join(chemin_dossier, nom_fichier)
                chemin_docx = os.path.join(chemin_dossier, Path(nom_fichier).stem + ".docx")

                print(f"Conversion de '{nom_fichier}'...")

                doc = word.Documents.Open(os.path.abspath(chemin_doc))
                doc.SaveAs(os.path.abspath(chemin_docx), FileFormat=16)
                doc.Close()
                
                # MODIFICATION : La ligne de suppression est maintenant active.
                os.remove(os.path.abspath(chemin_doc))
                
                print(f"-> Succès : '{nom_fichier}' a été converti et l'original supprimé.")

    finally:
        if word:
            word.Quit()
        print("\nOpération terminée.")

# --- Point de départ du script ---
if __name__ == "__main__":
    # MODIFICATION : La vérification a été retirée pour une exécution directe.
    print("Démarrage du script de conversion et suppression...")
    convertir_et_supprimer(CHEMIN_DU_DOSSIER)