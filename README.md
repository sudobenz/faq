# FAQ Portal — version 0.8.4

**Version actuelle : 0.8.4 — API de recherche sécurisée pour l’intégration GLPI 11.0.11+.**

Application de base de connaissances publique, avec authentification OIDC pour les demandes utilisateur et l'administration. Le projet est volontairement livré comme un **MVP fonctionnel** : il permet de valider l'architecture, les parcours et les premiers écrans avant d'ajouter les fonctions métier plus avancées.



## 0.8.3 — Contrôle précis du bandeau et des images de fond

La direction artistique permet désormais de régler indépendamment l’image de fond du bandeau et celle du site : mode de dimensionnement (`cover`, `contain`, `auto`, `100% 100%`), répétition, position horizontale et verticale, teinte de superposition et opacité.

Le bandeau dispose en plus de réglages de hauteur minimale, de marges intérieures et d'une forme décorative inférieure activable/désactivable et dimensionnable. Cette forme est désactivée par défaut afin qu'elle ne masque plus l'image de fond. Un aperçu du bandeau et du fond général se met à jour pendant la modification des paramètres. Les valeurs sont validées côté serveur et les choix CSS sont limités à une liste autorisée.

Aucune migration destructive n'est requise : les nouveaux paramètres sont stockés dans `app_settings` et reçoivent des valeurs par défaut au premier chargement.

## 0.7.0. Import DOCX et visionneuse PDF intégrée

L'import accepte les documents Word **DOCX** (20 Mo maximum), les PDF (30 Mo maximum), ainsi que les imports groupés CSV/JSON (5 Mo maximum). Les anciens fichiers Word `.doc` doivent être enregistrés au format `.docx` avant import.

- Un DOCX est converti en contenu HTML éditable via Mammoth. Les images compatibles sont extraites dans le stockage média ; le HTML est assaini avant enregistrement.
- Un PDF crée une fiche FAQ brouillon avec une visionneuse PDF.js intégrée : navigation page par page, zoom et plein écran. Aucun bouton Télécharger ou Imprimer n'est affiché.
- Les PDF résident dans le volume `faq_documents`, monté sur `/app/app/private_documents`, et ne sont jamais servis par la route statique générique.
- Le flux PDF est fourni avec `Content-Disposition: inline`, `Cache-Control: no-store` et `X-Content-Type-Options: nosniff`. L'accès aux fichiers rattachés à un article brouillon reste réservé aux administrateurs.

**Limite de protection :** un navigateur qui affiche un PDF doit recevoir ses octets. Le lecteur masque les actions Télécharger et Imprimer, mais n'empêche pas une récupération technique du flux par une personne autorisée, ni les captures d'écran. Il ne s'agit pas d'une DRM.

La visionneuse charge PDF.js 4.10.38 depuis cdnjs ; le proxy réseau doit autoriser ce CDN. Les scripts sont distincts de l'API de l'application et doivent être disponibles pour les navigateurs clients.

## 1 bis. Accès personnels dans l'en-tête — v0.4.1

Les liens « Mes fiches » et « Mes questions » sont présentés comme deux boutons distincts, chacun avec son libellé à l'intérieur, une icône, un contraste renforcé et un état de focus clavier. Ils restent visibles sur mobile et s'adaptent à la largeur disponible. Le lien du compte et le bouton de déconnexion sont conservés.

## 1. Fonctionnalités présentes

- FAQ publique avec recherche plein texte simple, catégories, fiches mises à la une et compteur de consultations.
- Articles avec brouillon / publication, résumé, catégorie, mots-clés et URL lisible.
- Éditeur riche Quill : titres, gras, listes, liens, blocs de code, citations et insertion d'images (PNG, JPEG, WEBP, GIF).
- Import d'articles au format CSV ou JSON ; mise à jour possible sur la base du slug.
- Personnalisation intégrale depuis l’administration : identité, menus, accès rapides, textes publics, couleurs, typographie, blocs visibles et pied de page.
- Pages CMS libres avec éditeur enrichi, publication et liens dans la navigation ou le pied de page.
- Authentification OIDC : compatible avec les fournisseurs conformes OIDC, notamment Authentik et Keycloak.
- Compte administrateur local de secours, avec mot de passe haché PBKDF2-HMAC-SHA256, verrouillage temporaire après cinq échecs et changement de mot de passe depuis l’administration.
- Modes d’authentification configurables : OIDC seul, OIDC + compte local, ou compte local seul.
- Création de questions et suivi personnel réservés aux utilisateurs authentifiés.
- Console d'administration protégée par une adresse e-mail autorisée ou un groupe/role OIDC configuré.
- PostgreSQL avec volume persistant ; stockage des images et des PDF dans des volumes distincts. Les PDF sont stockés hors du répertoire statique public.

## 2. Démarrage Docker

```bash
cp .env.example .env
```

Ne publiez jamais le fichier `.env` : il contient les secrets et paramètres propres à votre installation. Seul `.env.example`, qui ne contient que des valeurs fictives, doit être versionné.

Modifier au minimum les valeurs suivantes dans `.env` :

- `SECRET_KEY` : secret long et aléatoire.
- `POSTGRES_PASSWORD` et le mot de passe correspondant dans `DATABASE_URL`.
- `APP_URL` : URL réellement utilisée par les navigateurs, sans slash final.
- `OIDC_DISCOVERY_URL`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`.
- `ADMIN_EMAILS` et/ou `ADMIN_GROUPS`.
- `AUTH_MODE` : `oidc` (défaut), `both` ou `local`.
- Pour activer un compte local au premier démarrage : `LOCAL_ADMIN_USERNAME` et `LOCAL_ADMIN_PASSWORD` (14 caractères minimum).

Le fichier `.env.example` active `SEED_DEMO=true` pour afficher trois fiches de démonstration au premier démarrage. Passez cette valeur à `false` pour un déploiement vierge.

Le service FAQ rejoint un réseau Docker externe partagé avec le reverse proxy. Le nom par défaut est `reverse-proxy` ; créez-le si nécessaire, ou renseignez `PROXY_NETWORK` dans `.env` avec le nom du réseau déjà utilisé par votre proxy :

```bash
docker network create reverse-proxy
```

Démarrer :

```bash
docker compose up -d --build
```

Consulter les logs :

```bash
docker compose logs -f faq
```

L’application est accessible sur le réseau Docker partagé avec le reverse proxy à l’adresse `http://faq:8000`. Pour un accès direct depuis l’hôte, décommentez le mapping `ports` dans `docker-compose.yml` et définissez le port souhaité.

## 3. Configuration OIDC

Créer un client/confidential client dans Authentik ou Keycloak.

- Client ID : valeur à reporter dans `OIDC_CLIENT_ID`.
- Client secret : valeur à reporter dans `OIDC_CLIENT_SECRET`.
- Redirect URI exacte : `https://faq.example.com/auth/callback` (adapter au domaine réel).
- Web origin : domaine du portail si le fournisseur le demande.
- Scopes : `openid profile email`.
- Discovery URL : URL `.well-known/openid-configuration` du provider/realm.

Exemples de discovery URL :

- Authentik : `https://auth.example.com/application/o/faq/.well-known/openid-configuration`
- Keycloak : `https://sso.example.com/realms/MON-REALM/.well-known/openid-configuration`

L'utilisateur clique sur « Connexion entreprise ». Si une session existe déjà chez l'Identity Provider, le SSO peut être transparent. Le contenu FAQ reste public : la connexion n'est demandée qu'au moment de créer ou consulter ses questions.

### Attribution de l'administration

Deux possibilités sont prévues :

- `ADMIN_EMAILS=admin1@example.com,admin2@example.com`
- `ADMIN_GROUPS=faq-admins,faq-supervisors`

Le claim OIDC `groups`, `roles` ou `memberOf` est inspecté. Selon le fournisseur et le mapper OIDC, il peut être nécessaire d'ajouter le groupe dans les claims envoyés au client. Pour un déploiement de production, privilégier un groupe dédié et contrôler les claims réellement émis.


### Modes d'authentification et compte administrateur local

Le paramètre `AUTH_MODE` détermine les méthodes acceptées :

| Valeur | Comportement |
|---|---|
| `oidc` | OIDC uniquement. C'est le mode par défaut et le comportement historique. |
| `both` | OIDC pour les utilisateurs et possibilité de connexion avec le compte administrateur local de secours. |
| `local` | OIDC est désactivé ; seul le compte administrateur local peut se connecter. |

Pour activer le compte local, configurez par exemple :

```dotenv
AUTH_MODE=both
LOCAL_ADMIN_USERNAME=faqadmin
LOCAL_ADMIN_PASSWORD=un-mot-de-passe-unique-de-14-caracteres-minimum
```

Au tout premier démarrage avec `AUTH_MODE=both` ou `AUTH_MODE=local`, l'application crée le compte dans PostgreSQL et enregistre uniquement son hachage de mot de passe. Après cette création, retirez `LOCAL_ADMIN_PASSWORD` du fichier `.env` : le compte existant est conservé dans la base et le secret en clair n'est plus nécessaire. Le mot de passe peut être modifié dans **Administration → Sécurité** après connexion locale.

Pour désactiver OpenID Connect, passez `AUTH_MODE=local`, puis recréez le conteneur :

```bash
docker compose up -d --build faq
```

**Attention :** en mode `local`, seul le compte administrateur local est prévu pour s'authentifier. Les utilisateurs ordinaires ne pourront pas déposer ni suivre des questions tant qu'un fournisseur OIDC n'est pas réactivé. Pour conserver le SSO des utilisateurs tout en disposant d'un accès administrateur de secours, utilisez plutôt `AUTH_MODE=both`. Le mode d'authentification est volontairement défini dans `.env` et non modifiable depuis l'interface, afin d'éviter qu'un changement puisse verrouiller l'administration.

Les tentatives de connexion locales sont verrouillées pendant 15 minutes après cinq mots de passe incorrects. Les mots de passe sont hachés avec PBKDF2-HMAC-SHA256 et un sel aléatoire.

## 4. Import de contenu : fichiers, lots et Markdown

Dans `/admin/import`, vous pouvez importer un fichier, sélectionner plusieurs fichiers en une fois ou envoyer une archive ZIP contenant un lot de documents. Les ZIP sont parcourus sans extraction sur le système de fichiers ; les sous-dossiers sont pris en charge.

| Format | Limite par fichier | Traitement |
|---|---:|---|
| DOCX | 20 Mo | Conversion en article HTML éditable, brouillon par défaut |
| PDF | 30 Mo | Article brouillon avec visionneuse PDF intégrée |
| Markdown (`.md`, `.markdown`) | 5 Mo | Conversion HTML via Mistune, puis assainissement HTML |
| CSV / JSON | 5 Mo | Import de plusieurs articles structurés |
| ZIP | 150 Mo | Jusqu'à 100 documents ; 250 Mo décompressés maximum |

La taille cumulée des fichiers sélectionnés est limitée à 180 Mo par opération. Les archives peuvent contenir des DOCX, PDF, Markdown, CSV et JSON. Les répertoires et formats inconnus ne sont pas importés.

### Métadonnées Markdown

Un bloc front matter facultatif au début du fichier peut définir les propriétés de l'article :

```yaml
---
title: "Accéder au portail"
slug: acceder-au-portail
summary: "Procédure d'accès au portail."
category: "Comptes et accès"
tags: "portail, authentification"
status: draft
featured: false
---

# Accéder au portail

Le contenu de l'article en Markdown.
```

Les titres, paragraphes, listes, tableaux, liens, citations, blocs de code et texte barré sont convertis. Le HTML généré est nettoyé côté serveur. Sans front matter, le titre est extrait du premier H1 ou du nom de fichier ; le statut par défaut est `draft`.

### CSV / JSON

Champs reconnus :

| Champ | Description |
|---|---|
| `title` | Titre obligatoire |
| `slug` | Identifiant URL ; généré depuis le titre s'il est absent |
| `summary` | Résumé |
| `content_html` ou `content` | Contenu HTML nettoyé côté serveur |
| `content_markdown` | Contenu Markdown converti côté serveur |
| `format` | Valeur `markdown` pour interpréter `content` comme du Markdown |
| `category` | Catégorie, « Général » par défaut |
| `tags` | Mots-clés séparés par des virgules |
| `status` | `published` pour publier, sinon brouillon |
| `featured` | `true` / `1` pour mettre à la une |

Le mode `upsert` met à jour un brouillon existant ayant le même slug. Une fiche publiée n'est jamais écrasée par un import : un nouvel article est créé avec un slug suffixé. Le mode `create` crée une nouvelle fiche et ne remplace aucun contenu existant.

Un exemple JSON est disponible dans `app/static/import-exemple.json`. Le kit de validation séparé contient cinq articles équivalents en DOCX et Markdown, ainsi qu'une archive prête à importer pour chacun des deux formats.

## 5. Développement local sans Docker

Python 3.12 recommandé.

```bash
python -m venv .venv
```

Windows :

```powershell
.venv\Scripts\Activate.ps1
```

Linux :

```bash
source .venv/bin/activate
```

Puis :

```bash
pip install -r requirements.txt
```

Configurer `DATABASE_URL` vers une instance PostgreSQL accessible, puis démarrer :

```bash
uvicorn app.main:app --reload
```

## 6. Routes principales

| Route | Accès | Fonction |
|---|---|---|
| `/` | Public | Accueil, recherche et catégories |
| `/faq/{slug}` | Public | Lecture d'une fiche |
| `/auth/login` | Public | Démarrage OIDC ou redirection vers la connexion locale en mode `local` |
| `/auth/local/login` | Public, si activé | Connexion du compte administrateur local |
| `/questions/nouvelle` | Connecté | Dépôt d'une question |
| `/mes-questions` | Connecté | Suivi de ses demandes |
| `/admin` | Administrateur | Tableau de bord |
| `/admin/articles` | Administrateur | Gestion des fiches |
| `/admin/import` | Administrateur | Import multiple DOCX / PDF / Markdown / CSV / JSON et ZIP |
| `/admin/questions` | Administrateur | Traitement des questions |
| `/admin/branding` | Administrateur | Personnalisation visuelle |
| `/admin/security` | Administrateur | État des méthodes de connexion et changement du mot de passe local |
| `/api/integrations/glpi/v1/search` | GLPI (clé Bearer) | Recherche externe en lecture seule des articles publiés |
| `/health` | Interne | Vérification applicative / base |


## 8. Intégration indépendante à GLPI 11.0.11+

FAQ Portal reste le référentiel documentaire unique. Cette intégration ne crée et ne synchronise aucun article dans la base de connaissances native GLPI.

La version 0.8.4 expose une API de recherche en lecture seule :

```http
GET /api/integrations/glpi/v1/search?q=connexion%20vpn&limit=8
Authorization: Bearer <GLPI_API_TOKEN>
```

La clé API est configurée exclusivement côté serveur dans `.env` :

```dotenv
GLPI_API_TOKEN=COLLER_UN_SECRET_GENERE_AVEC_OPENSSL
GLPI_API_MAX_RESULTS=8
```

Générez une clé distincte pour cette intégration :

```bash
openssl rand -hex 32
```

Si `GLPI_API_TOKEN` est vide, l'API répond HTTP 503 et l'intégration est inactive. Une clé absente ou incorrecte donne HTTP 401. La recherche expose uniquement les articles publiés ; les résultats contiennent titre, résumé texte, catégorie, URL canonique et image de couverture facultative. Les contenus HTML complets, brouillons, questions, révisions et fichiers PDF privés ne sont pas exposés.

Le plugin GLPI `faqportal` version 1.0.0 se place dans `GLPI/plugins/faqportal`. Il utilise le hook `display_service_catalog` pour insérer un panneau indépendant sous la recherche du Catalogue de services, puis un endpoint PHP côté GLPI relaie la requête au moteur FAQ. La clé API n'est jamais envoyée au navigateur. Les formulaires natifs GLPI conservent leur filtrage et leur fonctionnement.

Le plugin est déclaré pour GLPI 11.0.11 et toute version ultérieure de la branche 11.x (maximum exclusif : 12.0.0). La compatibilité GLPI 12.x n'est pas revendiquée dans cette livraison, en attente d'une validation du cycle de hooks et du rendu sur cette branche majeure.

Voir `docs/INTEGRATION-GLPI11.md` et le README du plugin pour les procédures d'installation.

## 10. Points à finaliser avant production

Ce premier brouillon n'est pas encore un produit prêt à exposer sur Internet. Avant mise en production, prévoir notamment :

1. Une vraie chaîne de migrations SQL (Alembic) au lieu de `create_all`.
2. Un reverse proxy HTTPS (Traefik ou NGINX), HSTS, politique CSP, cookies sécurisés et limitation de débit.
3. Une validation des claims/groupes OIDC adaptée aux attributs réellement émis par l'IdP ; éventuellement une synchronisation du profil utilisateur.
4. Un système d'autorisation plus fin : administrateur global, rédacteur, valideur, contributeur et gestionnaire de questions.
5. Une gestion des pièces jointes avec quota, contrôle de type réel, antivirus et politique de conservation.
6. Un workflow éditorial (soumission, validation, publication, historique/versioning et archivage).
7. Notifications e-mail, SLA, affectation des demandes et possibilité de transformer une question récurrente en article FAQ.
8. Journal d'audit, sauvegardes PostgreSQL testées, restauration documentée et supervision.
9. Tests automatisés, tests de sécurité, pagination, recherche PostgreSQL full-text et éventuellement moteur de recherche dédié.
10. Évaluation de la configuration CORS/CSRF, des liens externes et de l'assainissement HTML avant d'autoriser l'intégration de médias externes.

## 11. Limites fonctionnelles connues du brouillon

- L'import ne lit pas directement une sauvegarde native phpMyFAQ : il attend un CSV/JSON normalisé selon le schéma décrit ci-dessus. Un convertisseur spécifique pourra être ajouté après identification du format d'export source.
- Les réponses aux questions sont visibles dans l'espace « Mes questions », mais aucune notification e-mail n'est encore envoyée.
- Les demandes ne sont pas encore routées automatiquement par catégorie ou équipe.
- Le moteur de recherche est une recherche SQL `ILIKE` ; il ne gère pas encore les synonymes, la pondération, ni la recherche linguistique.
- L'éditeur est chargé depuis le CDN jsDelivr dans ce brouillon ; il faudra le servir localement pour les environnements isolés.

---

**Nom de travail :** FAQ Portal  
**Version historique :** 0.3.0 — authentification OIDC/locale, refonte graphique et statistiques d’usage  
**Stack :** FastAPI · PostgreSQL · SQLAlchemy · Jinja2 · Quill · OIDC

## 9. Correctif v0.1.1

- Ajout de `httpx` aux dépendances Python : Authlib importe ce client HTTP pour initialiser son intégration Starlette/OIDC. Sans ce paquet, le processus Uvicorn s’arrête dès l’import de `app.auth` avec `ModuleNotFoundError: No module named 'httpx'`.
- Après mise à jour, reconstruire l’image de l’application avec `docker compose up -d --build faq`.


## 10. Direction artistique v0.3.0

La page publique a été revue à partir de la référence visuelle fournie : en-tête blanc avec recherche centrale, navigation horizontale, bandeau dégradé bleu/prune/rouge, bloc de mise en avant, accès rapides et cartes éditoriales responsive. Le logo peut être remplacé dans `/admin/branding`. Pour illustrer les cartes de la page d'accueil, la première image intégrée dans le contenu Quill de la fiche est utilisée comme vignette ; en l'absence d'image, une illustration de catégorie est affichée.

## 11. Statistiques d'usage et pilotage des services (v0.3.0)

L'espace `/admin/analytics` fournit un tableau de bord filtrable sur 7, 30, 90 ou 365 jours :

- consultations de chaque fiche FAQ et visiteurs uniques par fiche ;
- volume des recherches, expressions les plus recherchées et recherches sans résultat ;
- consultations, visiteurs, recherches et questions ouvertes par service/direction ;
- activité quotidienne sur les 30 derniers jours ;
- catégories les plus consultées ;
- fiches FAQ les plus suivies par les utilisateurs ;
- export CSV agrégé des consultations, visiteurs uniques et abonnements.

### Fonctionnement de la mesure

Les événements sont enregistrés dans les tables `analytics_events` et `article_follows`. Un identifiant aléatoire de navigateur est conservé dans un cookie first-party `faq_visitor`, puis haché avec HMAC-SHA256 avant stockage. Les identifiants OIDC ne sont pas enregistrés dans les événements ni dans les abonnements. Aucune adresse IP ni empreinte navigateur n'est stockée dans les événements analytiques. Les recherches sont normalisées, limitées à 180 caractères et les e-mails/numéros de téléphone détectés sont masqués.

Par défaut, le bandeau de consentement demande l'accord avant la mesure. Le signal `Do Not Track: 1` désactive également la mesure pour la requête. Le cookie de mesure expire après 180 jours. Les événements analytiques sont purgés au démarrage lorsque leur ancienneté dépasse `ANALYTICS_RETENTION_DAYS` (365 jours par défaut, minimum 30). L'utilisateur peut modifier son choix depuis le lien « Préférences de statistiques » en pied de page. Les données historiques ne sont pas rétroactives : les compteurs analytiques commencent à la mise en service de la version 0.3.0 et après consentement.

### Configuration des services

Dans `.env` :

```dotenv
ANALYTICS_ENABLED=true
ANALYTICS_REQUIRE_CONSENT=true
ANALYTICS_SERVICE_CLAIM=department
ANALYTICS_SALT=GENERER-UNE-VALEUR-ALEATOIRE-STABLE
ANALYTICS_RETENTION_DAYS=365
```

Générer le sel avec `openssl rand -hex 32`. Il doit rester stable entre les redéploiements : changer ce sel réinitialise la reconnaissance pseudonymisée des visiteurs et des abonnements existants.

Le fournisseur OIDC doit transmettre un claim (par défaut `department`) contenant le service ou la direction de l'utilisateur dans l'UserInfo. Dans Authentik ou Keycloak, mapper l'attribut AD correspondant vers ce claim. Si le claim n'est pas transmis, les événements authentifiés sont classés dans `Non renseigné`. Les utilisateurs anonymes sont classés dans `Public / non connecté`.

Les utilisateurs authentifiés peuvent sélectionner « Suivre cette fiche » sur une FAQ. Le suivi est révocable depuis la fiche et la liste `/mes-fiches-suivies`. Le tableau de bord classe les fiches selon le nombre d'abonnements actifs.

**Vie privée :** la mesure est désactivable avec `ANALYTICS_ENABLED=false`. Avant exposition publique ou déploiement généralisé, faire valider le paramétrage, le texte d'information, la base légale et la durée de conservation par le DPO. Ne pas considérer ce mécanisme comme une validation juridique automatique.

### Routes ajoutées

| Route | Accès | Fonction |
|---|---|---|
| `/admin/analytics` | Administrateur | Tableau de bord analytique |
| `/admin/analytics/export.csv` | Administrateur | Export agrégé des consultations par FAQ |
| `/faq/{slug}/suivre` | Connecté | Activer/désactiver le suivi d'une fiche |
| `/mes-fiches-suivies` | Connecté | Liste personnelle des fiches suivies |
| `/analytics/consent` | Public | Enregistrer le choix de mesure d'audience |
| `/analytics/preferences` | Public | Consulter et modifier le choix de mesure d'audience |

L'initialisation `Base.metadata.create_all()` crée automatiquement les deux nouvelles tables dans une base PostgreSQL existante sans supprimer les tables ni les volumes actuels. Une stratégie Alembic restera à prévoir avant les futures évolutions structurelles.

---

## 12. Version 0.4.0 — personnalisation intégrale et CMS

La version 0.4.0 ajoute un éditeur global accessible depuis **Administration → Personnalisation complète** (`/admin/portal`). Il permet de modifier sans intervention sur le code :

- le nom du portail, le logo, le sous-titre, la recherche et les libellés de connexion ;
- les entrées et l'ordre du menu principal ;
- les accès rapides (libellé, URL et icône) ;
- les textes principaux de la page d'accueil, de la mise en avant, du catalogue, des fiches populaires et du bloc de contact ;
- les textes et boutons des fiches FAQ, du suivi, du formulaire de question, des pages « Mes questions », « Mes fiches suivies » et de la connexion locale ;
- les couleurs principales et secondaires, les trois couleurs du dégradé, les fonds, la couleur de texte, la police, la largeur maximale, le nombre de colonnes des cartes et leur arrondi ;
- l'affichage ou le masquage de la navigation, de la recherche, du bandeau d'accueil, des accès rapides, des catégories, des fiches populaires, du bloc de question, des compteurs, des suivis et des contenus associés ;
- les textes et le lien du pied de page ;
- un bloc HTML complémentaire dans la page d'accueil (nettoyé avant enregistrement).

Tous ces paramètres sont stockés dans `app_settings` (PostgreSQL), et non dans le fichier `.env`. Les changements sont appliqués immédiatement après enregistrement.

### Pages personnalisées

Le nouveau module **Administration → Pages personnalisées** (`/admin/pages`) permet de créer, modifier, publier, dépublier et supprimer des pages autonomes avec titre, URL, résumé, contenu riche (titres, listes, liens, tableaux et images) et inclusion facultative au pied de page. Une page publiée est accessible à `/contenu/<slug>`. Pour l'ajouter au menu principal, ajouter une ligne `Libellé | /contenu/<slug>` dans l'éditeur de navigation.

Les images importées sont stockées dans le volume `faq_uploads` via `/admin/upload-image`. Les pages personnalisées utilisent le même assainissement HTML que les articles FAQ.

### Catégories et fiches

Les contenus FAQ (titre, résumé, texte enrichi, catégorie, tags, publication et mise en avant) restent gérés individuellement depuis **Administration → Articles FAQ**. Les catégories proposées sur le site sont dérivées des catégories des articles publiés : renommer une catégorie consiste à modifier la catégorie des articles concernés.

### Migration et mise à jour depuis 0.3.0

La table `cms_pages` est ajoutée par `Base.metadata.create_all()` au démarrage. Les réglages existants et les volumes PostgreSQL ne sont pas supprimés. L'ancienne route `/admin/branding` redirige vers le nouvel éditeur global.

Reconstruction de l'application :

```bash
docker compose up -d --build faq
docker compose logs -f faq
```

Ne pas utiliser `docker compose down -v` : cela supprimerait les volumes de données.

### Vérifications v0.4.0

- compilation Python ;
- chargement des 21 templates Jinja ;
- tests de fumée HTTP avec SQLite temporaire : accueil, éditeur global, liste et formulaire de pages, sauvegarde de configuration, publication et consultation d'une page ;
- validation de la persistance des réglages et de la page créée.

Le test Docker/PostgreSQL/OIDC complet doit toujours être réalisé dans l'environnement cible avant mise en production. Le CDN Quill utilisé par l'éditeur nécessite un accès à jsDelivr ; pour un réseau isolé, distribuer les fichiers Quill localement.


## 13. CMS Studio — expérience d'édition v0.5.0

La version 0.5.0 remplace les formulaires linéaires par un espace de rédaction commun aux articles FAQ et aux pages libres.

### Espace d'édition

- En-tête fixe avec retour bibliothèque, statut de sauvegarde, aperçu et actions d'enregistrement/publication.
- Zone de document centrée avec titre, URL, résumé et éditeur Quill 2.
- Barre d'outils : titres, gras, italique, souligné, barré, listes, checklist, citation/encadré, code, liens, images, alignement et nettoyage de mise en forme.
- Actions rapides pour insérer un encadré, une liste d'étapes à cocher et un séparateur.
- Glisser-déposer et collage d'images ; limites appliquées par le point d'upload : PNG/JPEG/WEBP/GIF, 5 Mo maximum.
- Compteur de mots, estimation du temps de lecture et plan automatique à partir des titres H2/H3/H4.
- Aperçu isolé dans une fenêtre modale, sans publier le contenu.
- Panneau latéral : publication, mise en avant ou affichage au pied de page, organisation et aperçu de référencement.
- Raccourcis : Ctrl/Cmd+S pour enregistrer ; Ctrl/Cmd+Maj+P pour ouvrir l'aperçu.

### Autosauvegarde et versions

La sauvegarde automatique est déclenchée après une période d'inactivité. Pour un nouveau contenu, le premier autosave crée un brouillon PostgreSQL avec un identifiant stable. Pour un contenu déjà existant, les autosaves créent des instantanés dans `content_revisions` sans écraser la version publique. L'administrateur peut restaurer un instantané dans l'éditeur puis l'enregistrer ou le publier explicitement. Les 30 versions les plus récentes par contenu sont conservées.

Une copie locale peut être conservée dans le navigateur si le serveur est momentanément indisponible. Elle est proposée à la récupération au prochain chargement de l'éditeur.

### Bibliothèques de contenus

Les listes des articles FAQ et des pages proposent désormais une recherche instantanée, des filtres par statut, un tri (titre, modification, ancienneté et, pour les FAQ, consultations), des indicateurs de volume et des cartes de contenu avec actions directes.

### Données et mise à jour

La table `content_revisions` est créée automatiquement par `Base.metadata.create_all()` au démarrage. Aucune table existante ni aucun volume PostgreSQL n'est supprimé. Les pages et articles actuels sont conservés.

```bash
docker compose up -d --build faq
```

Après déploiement, effectuer un rechargement forcé du navigateur (`Ctrl+F5`) pour renouveler les fichiers CSS et JavaScript.

### Vérifications v0.5.0

- Compilation de l'ensemble du code Python.
- Vérification syntaxique des scripts JavaScript.
- Chargement des templates Jinja.
- Création et lecture du modèle de révision avec SQLite de test.
- Test de l'autosauvegarde d'un nouveau brouillon.
- Test de non-écrasement d'un article publié pendant un autosave.
- Vérification de l'exposition des routes autosave et historique.

Le démarrage Docker/PostgreSQL/OIDC complet et le test navigateur final doivent être effectués sur l'environnement cible. Quill 2 est encore chargé depuis jsDelivr dans cette version ; il faudra le distribuer localement sur les réseaux sans accès Internet.

## Version 0.6.0 — ergonomie du CMS

- Personnalisation du portail organisée en six onglets : Identité, Accueil, Contenus, Apparence, Affichage et Pied de page.
- Barre d'onglets persistante et barre d'enregistrement fixe : plus besoin de parcourir une longue page pour atteindre les réglages ou enregistrer.
- Paramètres de l'éditeur de contenu répartis en onglets Publication, Organisation, Référencement et Historique.
- Bibliothèque des pages avec parcours guidé en trois étapes : créer, rédiger, prévisualiser et publier.
- Aide contextuelle pour distinguer une page institutionnelle d'une fiche FAQ.

### Mise à jour

```bash
docker compose up -d --build faq
```

Aucune suppression de volume ni migration destructive n'est nécessaire.


## Version 0.7.0 — Import Word et visionneuse PDF

### Formats d'import
- **DOCX** : conversion Word vers HTML éditable via Mammoth. Les titres, paragraphes, listes, tableaux, liens et images compatibles sont importés. Le contenu est créé en brouillon pour relecture avant publication. Le format Word binaire `.doc` n'est pas pris en charge ; enregistrer le document en `.docx` avant import.
- **PDF** : création d'une fiche FAQ en brouillon avec lecteur PDF intégré (PDF.js), navigation par page, zoom et plein écran. L'interface de lecture ne propose ni téléchargement ni impression.
- **CSV / JSON** : import groupé conservé.

Les PDF sont stockés hors du répertoire statique dans `/app/app/private_documents`, au moyen du volume Docker `faq_documents`. Ils sont servis à la demande avec `Content-Disposition: inline`, `Cache-Control: no-store` et `X-Content-Type-Options: nosniff`. Ils ne disposent pas d'une URL statique prévisible.

**Limite de sécurité importante :** un navigateur qui reçoit un PDF pour l'afficher reçoit nécessairement les octets du document. L'interface peut supprimer les commandes de téléchargement et d'impression, mais ne peut pas empêcher techniquement une personne autorisée de récupérer le flux via les outils du navigateur, une capture d'écran ou un autre logiciel. Pour une interdiction stricte de copie, il faut une solution DRM ou ne pas transmettre le PDF original (par exemple un rendu page par page sous forme d'images avec contrôle d'accès, qui n'empêche pas non plus les captures).

### Mise à jour

```bash
docker compose up -d --build faq
```

Le nouveau volume `faq_documents` est créé automatiquement. Ne supprimez pas les volumes PostgreSQL ni les volumes des médias existants. Le lecteur PDF charge PDF.js depuis cdnjs ; l'accès au CDN doit être autorisé par le proxy réseau.


## Correctif 0.7.1 — accès à l'écran d'import

Le menu d'administration ouvre `/admin/import` en GET. La version précédente ne déclarait que la route POST de réception des fichiers, ce qui provoquait une réponse HTTP 405. La version 0.7.1 ajoute la route GET protégée par les droits administrateur ; le traitement des fichiers reste assuré par la route POST existante.

Mise à jour :

```bash
docker compose up -d --build faq
```


## Version 0.7.2 — Correctif import et PDF à la création

- Correction de l'import PDF : le titre est renseigné dès la construction de l'objet Article, avant tout `flush()` SQLAlchemy. Cela évite la violation NOT NULL sur `articles.title` sous PostgreSQL.
- Ajout d'un champ facultatif « Document PDF associé » dans l'éditeur d'article.
- Le PDF est validé (extension, signature `%PDF-`, limite 30 Mo), stocké dans `private_documents` et affiché via la visionneuse intégrée.
- Le champ PDF est disponible à la création comme à la modification d'un article.
- Lorsqu'un nouveau PDF est choisi, l'ancien document associé à la fiche est remplacé.

Mise à jour : `docker compose up -d --build faq`. Conserver tous les volumes.


## Version 0.8.0 — Import multiple, ZIP et Markdown

- Sélection de plusieurs fichiers dans une seule opération d'import.
- Import des archives ZIP contenant jusqu'à 100 documents pris en charge, avec parcours des sous-dossiers et limites de taille contrôlées.
- Prise en charge de Markdown (`.md` et `.markdown`) avec front matter éditorial facultatif.
- Prise en charge de `content_markdown` et du champ `format: markdown` dans les imports JSON / CSV.
- Résultat détaillé par fichier : import réussi ou motif d'échec.
- Conservation de la règle de protection des fiches publiées : elles ne sont jamais écrasées par un import `upsert`.
- Les formulaires d'import historiques utilisant un champ unique `file` restent acceptés en complément du nouveau champ multiple `files`.

La conversion Markdown s'appuie sur `mistune` (dépendance ajoutée à `requirements.txt`) et le HTML produit est nettoyé avec Bleach avant enregistrement.


## Version 0.8.1 — Images personnalisées des tuiles et aperçu CMS

- Ajout d'une image de couverture propre à chaque article FAQ, téléversée depuis l'onglet Organisation de l'éditeur. Formats PNG, JPEG, WEBP et GIF, 5 Mo maximum.
- L'image personnalisée remplace l'illustration générique sur la tuile de la page d'accueil et sur la fiche mise à la une. Si aucune image n'est définie, le comportement visuel précédent est conservé.
- L'image est conservée dans le stockage média déjà monté (`faq_uploads`) ; seule son URL est enregistrée en base.
- Ajout non destructif de la colonne `articles.cover_image` au démarrage pour les bases existantes. Aucune suppression ou recréation de volume n'est requise.
- Correction de l'aperçu de l'éditeur : le document de prévisualisation est désormais initialisé de façon synchrone après ouverture de la fenêtre. L'ancien code pouvait manquer l'événement `load` et tenter d'accéder au DOM d'une iframe sandboxée, ce qui laissait l'aperçu vide ou incomplet.
- L'aperçu conserve les styles de lecture et affiche le contenu actuellement présent dans l'éditeur, sans publier les modifications.

Mise à jour : `docker compose up -d --build faq`. Conserver tous les volumes.

## Version 0.8.2 — apparence avancée et affichage adaptatif

- L’image personnalisée d’une tuile FAQ est également affichée en haut de la fiche lorsqu’elle est ouverte.
- Personnalisation du bandeau d’accueil par image de fond, avec superposition sombre pour conserver le contraste.
- Personnalisation du fond général par image, avec voile clair pour préserver la lisibilité ; les couleurs unies et dégradés restent disponibles en alternative.
- Import d’une police personnalisée WOFF2, WOFF, TTF ou OTF (5 Mo maximum), stockée dans le volume persistant `faq_uploads`.
- Mise en page adaptative renforcée pour grands écrans, ordinateurs portables, tablettes et mobiles : grilles fluides, navigation repliable, cartes sans débordement et images responsives.
- Les images de fond et la police sont conservées dans le volume d’uploads ; aucune donnée existante n’est supprimée.

Déploiement : `docker compose up -d --build faq`, puis rechargement forcé du navigateur (`Ctrl+F5`).


**Consigne de sécurité GLPI :** autoriser l'accès réseau à l'endpoint d'API uniquement depuis le serveur GLPI lorsque le reverse proxy ou le pare-feu le permet. Ne pas transmettre `GLPI_API_TOKEN` aux utilisateurs, au navigateur ou à un dépôt de code.
