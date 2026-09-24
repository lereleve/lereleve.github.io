# Le Relevé

Site de transparence parlementaire. Les votes, députés et groupes viennent des données ouvertes
officielles de l'Assemblée nationale (Licence Ouverte), téléchargées et recalculées chaque nuit.

## Ce que contient ce dossier

- `site/index.html` : le site.
- `site/contenu/` : les contenus éditoriaux que vous rédigez (fiches loi, fiches d'écart, corrections, mentions légales).
- `scripts/construire_donnees.py` : télécharge les données officielles, calcule les indicateurs et vérifie vos contenus.
- `.github/workflows/mise-a-jour.yml` : l'automatisation qui lance le script chaque nuit et publie le site.
- `modeles/` : modèles vierges de fiches.

## Publier une fiche loi

1. Ouvrez `modeles/fiche-loi.json`, copiez tout son contenu.
2. Ouvrez `site/contenu/lois.json` sur GitHub, cliquez sur le crayon.
3. Collez la fiche entre les crochets `[ ]`. S'il y a déjà une fiche, séparez-les par une virgule.
4. Remplissez chaque champ, mettez `"publie": true`, puis « Commit changes ».
5. Le site se met à jour en quelques minutes. En cas d'erreur de saisie, l'onglet Actions affiche la ligne en cause
   et le site en ligne reste inchangé.

Le numéro `scrutin` est celui du scrutin officiel (visible dans l'onglet Votes du site).
L'identifiant `depute` (PA suivi de chiffres) figure dans l'adresse de la fiche du député sur le site.

## Règles à ne jamais contourner

- Le dépôt est public : ne préparez jamais une fiche d'écart ici. Rédigez-la ailleurs, et ne l'ajoutez à
  `revirements.json` qu'après vérification par une seconde personne, sollicitation du député (48 heures ouvrées)
  et, pour les premières fiches, relecture juridique.
- Toute citation est intégrale et liée à sa source horodatée, avec une copie archivée.
- Avant d'ouvrir le site au public : remplissez `site/contenu/site.json` (directeur de la publication, contact),
  puis retirez la ligne `<meta name="robots" content="noindex, nofollow">` de `site/index.html`.
