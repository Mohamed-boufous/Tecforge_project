def generer_liens(lien_initial):
    # Étape 1 : Générer le lien de demande de téléchargement
    lien_demande = lien_initial.replace(
        "entreprise.EntrepriseDetailsConsultation",
        "entreprise.EntrepriseDemandeTelechargementDce"
    )

    # Étape 2 : Générer le lien de téléchargement complet
    lien_final = lien_demande.replace(
        "entreprise.EntrepriseDemandeTelechargementDce",
        "entreprise.EntrepriseDownloadCompleteDce"
    )
    lien_final = lien_final.replace("refConsultation=", "reference=")
    lien_final = lien_final.replace("orgAcronyme=", "orgAcronym=")

    return lien_demande, lien_final

# Exemple d'utilisation
lien_depart = "https://www.marchespublics.gov.ma/index.php?page=entreprise.EntrepriseDetailsConsultation&refConsultation=911673&orgAcronyme=g8e"
lien_demande, lien_telechargement = generer_liens(lien_depart)

print(lien_demande)
print(lien_telechargement)
