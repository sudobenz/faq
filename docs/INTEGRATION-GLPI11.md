# Intégration FAQ Portal avec GLPI 11.0.11+

## Positionnement

FAQ Portal demeure autonome et héberge le contenu, le CMS, la recherche, les médias, les versions et les statistiques. Aucun article n'est créé, synchronisé ou stocké dans la base de connaissances native GLPI. Aucun formulaire ni mécanisme de création de ticket GLPI n'est modifié.

## Parcours utilisateur

1. L'utilisateur ouvre le Catalogue de services / self-service GLPI.
2. Il saisit sa recherche dans le champ natif GLPI.
3. GLPI continue de filtrer ses formulaires normalement.
4. Le plugin affiche en parallèle les articles publiés de FAQ Portal dans un panneau distinct sous la barre de recherche.
5. L'ouverture d'un résultat mène à l'article original sur FAQ Portal.
6. Si aucune réponse ne convient, le bouton « Accéder aux formulaires GLPI » revient au Catalogue ou à la destination configurée.

L'accès direct `https://faq...` reste possible sans passer par GLPI.

## Architecture

- FAQ Portal 0.8.4 : endpoint HTTP en lecture seule `/api/integrations/glpi/v1/search`.
- GLPI `faqportal` 1.0.0 : hook `display_service_catalog`, panneau de résultats, script de suivi de la recherche, relais PHP cURL.
- Authentification API : clé Bearer dédiée, côté serveur uniquement.
- Transport : HTTPS recommandé et validation TLS activée sur le relais PHP.
- Défaillance : le panneau affiche un message si FAQ Portal est indisponible ; les formulaires GLPI restent accessibles.

Le hook `display_service_catalog` a été ajouté au système de hooks GLPI en 11.0.7. Le sélecteur natif de saisie du Catalogue de services est `data-glpi-service-catalog-filter-items`. La livraison relève toutefois la version minimale à 11.0.11 comme demandé.

## Déploiement FAQ Portal

Dans le fichier `.env` de FAQ Portal :

```dotenv
GLPI_API_TOKEN=SECRET_HEXADECIMAL_LONG
GLPI_API_MAX_RESULTS=8
```

Générez le secret :

```bash
openssl rand -hex 32
```

Recréez uniquement le service FAQ Portal :

```bash
docker compose up -d --build faq
```

Ne supprimez aucun volume Docker.

Test API depuis un serveur ayant accès à FAQ Portal :

```bash
curl -sS -H "Authorization: Bearer $GLPI_API_TOKEN" \
  --get --data-urlencode "q=connexion vpn" \
  "https://faq.example.com/api/integrations/glpi/v1/search"
```

Sans clé ou avec une clé erronée, l'API renvoie HTTP 401 (ou HTTP 503 si aucune clé n'est configurée côté FAQ).

## Installation du plugin GLPI

1. Faire une sauvegarde de la base GLPI et de ses fichiers.
2. Extraire `faqportal` dans `GLPI/plugins/`.
3. Vérifier le chemin `GLPI/plugins/faqportal/setup.php`.
4. Vérifier que PHP cURL est activé sur le serveur GLPI.
5. Dans **Configuration > Plugins**, installer puis activer **FAQ Portal**.
6. Ouvrir la configuration du plugin.
7. Renseigner l'URL racine de FAQ Portal, la clé API, le nombre de résultats et l'URL cible du bouton GLPI.
8. Activer le Catalogue de services pour l'entité des utilisateurs self-service.

Configuration type :

| Paramètre | Valeur exemple |
|---|---|
| URL FAQ Portal | `https://faq.example.com` |
| Clé API | La même valeur que `GLPI_API_TOKEN` |
| Nombre de résultats | `8` |
| Destination GLPI | `/ServiceCatalog` |

Le compte qui configure le plugin doit disposer du droit de configuration GLPI.

## Sécurité et limites

- L'endpoint de relais côté GLPI est accessible seulement à un utilisateur connecté dans l'interface `helpdesk`.
- La clé API ne figure ni dans le HTML, ni dans les attributs `data-*`, ni dans le JavaScript.
- Le serveur GLPI transmet la clé par en-tête HTTP Bearer.
- Les liens et images de réponse sont limités à l'hôte de FAQ Portal.
- Les résultats du navigateur sont construits avec `textContent` (pas d'injection de HTML d'article).
- Le connecteur est en lecture seule : il ne crée pas de ticket et n'écrit rien dans la KB GLPI.
- Le panneau de résultats ne remplace pas les résultats ni les formulaires du Catalogue.

## Compatibilité

Le plugin déclare `min=11.0.11` et `max=12.0.0`. Il vise les versions GLPI 11.0.11 et ultérieures de la branche 11.x. GLPI 12.x doit faire l'objet d'une validation séparée avant de modifier la plage de compatibilité.

## Validation à effectuer sur l'instance réelle

Cette livraison a été vérifiée statiquement. Elle n'a pas pu être activée sur une instance GLPI 11.0.11 dans l'environnement de construction. Il reste à vérifier sur l'instance cible : activation du plugin, affichage sous la recherche, réponses API, lien article, destination ticket, et comportement en cas d'indisponibilité FAQ Portal.
