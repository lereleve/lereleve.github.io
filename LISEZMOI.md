# Le Relevé

Site de transparence parlementaire. Votes, députés, groupes et lois viennent exclusivement des données ouvertes
officielles de l'Assemblée nationale (Licence Ouverte), de la 14e législature (2012) à aujourd'hui.
Les données sont téléchargées et recalculées automatiquement deux fois par jour (vers 7 h 15 et 21 h 15).

## Contenu du dossier

- `site/index.html` : le site.
- `site/contenu/site.json` : mentions légales (à remplir avant toute ouverture publique).
- `site/contenu/lois.json` : résumés de lois rédigés par la rédaction (facultatif).
- `site/contenu/corrections.json` : journal des corrections.
- `scripts/construire_donnees.py` : téléchargement des données officielles et calcul des indicateurs.
- `.github/workflows/mise-a-jour.yml` : automatisation (dossier caché sur Mac : Cmd + Maj + point pour l'afficher).

## Publier un résumé de loi

Copiez `modeles/fiche-loi.json` dans `site/contenu/lois.json` (entre les crochets), remplissez chaque champ,
mettez `"publie": true`. L'auteur et le vérificateur doivent être deux personnes différentes.
En cas d'erreur de saisie, l'onglet Actions affiche la ligne en cause et le site en ligne reste inchangé.

## Avant l'ouverture publique

1. Remplir `site/contenu/site.json` (éditeur, directeur de la publication, contact).
2. Faire relire les mentions légales et la méthode par un juriste (une clinique juridique universitaire convient).
3. Retirer la ligne `<meta name="robots" content="noindex, nofollow">` de `site/index.html`.
