# GreenLine ETA API

API évolutive pour la gestion de l’ETA (heure d’arrivée estimée) des interventions.

## Démarrage local

Prérequis : Python 3.12+. Docker Compose est requis seulement pour le démarrage conteneurisé.

1. Copier `.env.example` vers `.env` et renseigner les secrets si nécessaire.
2. Démarrer l’API et PostgreSQL :

   ```bash
   docker compose up --build
   ```

3. Ouvrir l’interface de test : <http://localhost:8000/>
4. Ouvrir la documentation interactive : <http://localhost:8000/docs>
5. Vérifier l’état de l’API : <http://localhost:8000/api/v1/health>
6. Consulter la référence des endpoints : <http://localhost:8000/api-reference>
7. Gérer les tokens API et leurs quotas : <http://localhost:8000/token-management>
8. Tester adresses, parcs et itinéraires : <http://localhost:8000/route-tester>

## Format des réponses

Toutes les routes JSON utilisent la même enveloppe : `message` décrit le résultat, `errors` contient les erreurs éventuelles, `data` contient la réponse métier (ou `null` en cas d’erreur) et `pagination` contient les métadonnées de pagination (ou `null` quand la route n’est pas paginée).

Exemple de succès :

```json
{
  "message": "ETA calculée avec succès.",
  "errors": [],
  "data": {
    "eta_at": "2026-11-19T14:30:00Z",
    "duration_seconds": 900,
    "distance_meters": 4200,
    "encoded_polyline": "..."
  },
  "pagination": null
}
```

En cas d’erreur, le code HTTP reste adapté à la situation et `errors` contient des objets avec `code`, `message` et, pour une erreur de validation, `field`.

Pour lancer uniquement l’API depuis un environnement Python, le projet utilise SQLite dans `greenline.db` par défaut :

```bash
python -m venv .venv
# Activer l’environnement, puis :
pip install -e .
uvicorn greenline_api.main:app --reload --app-dir src
```

Le fichier SQLite est créé automatiquement au démarrage et ignoré par Git. Docker Compose définit séparément `DATABASE_URL` sur PostgreSQL; la valeur SQLite du fichier `.env` n’affecte donc pas le conteneur.

## Interface et carte Google

La page `/` utilise Google Maps JavaScript API pour afficher la carte. Cliquez sur « Départ » ou « Arrivée », puis sur la carte pour définir les coordonnées, ou saisissez-les directement. « Calculer l’ETA » appelle `POST /api/v1/eta` et trace la géométrie de route retournée par Google Routes.

Renseignez `GOOGLE_MAPS_API_KEY` dans `.env` avec une clé dédiée à la carte navigateur. Dans Google Cloud, activez Maps JavaScript API et la facturation ; restreignez cette clé au référent de l’application (pour un test local : `http://localhost:8000/*`) et à Maps JavaScript API. Cette clé est visible dans le navigateur par conception et ne sert qu’à la carte.

Le calcul d’itinéraire utilise les identifiants Google côté serveur. Activez Routes API et la facturation dans le projet associé au compte de service. Pour Python lancé localement, placez le fichier JSON du compte de service dans `credentials/` (par exemple `credentials/service-account.json`) et définissez `GOOGLE_APPLICATION_CREDENTIALS=./credentials/service-account.json` dans `.env`. Le dossier `credentials/` est ignoré par Git pour éviter de publier les identifiants.

Les nouvelles routes d’adresse et d’ETA hybride se testent sur `/route-tester`. Pour la conversion d’adresse, activez Geocoding API et renseignez `GOOGLE_GEOCODING_API_KEY` avec une clé serveur restreinte à cette API. Elle n’est jamais exposée au navigateur. Conservez `GOOGLE_MAPS_API_KEY` pour Maps JavaScript côté navigateur.

- **Python local sous Windows :** le chemin configuré dans `.env` est transmis au client Google. Démarrez ensuite Uvicorn depuis la racine du projet.
- **Docker Compose sous Windows :** exécutez `gcloud auth application-default login` sur l’hôte avant `docker compose up --build`. Compose monte en lecture seule `%APPDATA%\gcloud\application_default_credentials.json` dans le conteneur.

Ne confondez pas la clé navigateur `GOOGLE_MAPS_API_KEY` avec les identifiants du serveur : la clé ne donne pas accès au calcul d’itinéraire. Pour un déploiement, préférez l’identité de service ou le mécanisme d’identifiants fourni par l’environnement.

## Calcul d’ETA

`POST /api/v1/eta` reçoit les coordonnées GPS de départ et d’arrivée. Les détails de l’itinéraire (heure d’arrivée estimée en UTC, durée, distance et géométrie encodée) sont fournis dans `data` de l’enveloppe standard. Le calcul utilise le client Python `google-maps-routing`, en mode voiture et avec estimation tenant compte du trafic lorsque les données sont disponibles.

Exemple de corps JSON :

```json
{
  "origin": { "latitude": 48.8566, "longitude": 2.3522 },
  "destination": { "latitude": 48.8584, "longitude": 2.2945 }
}
```

`POST /api/v1/geocode` convertit une adresse en coordonnées GPS et renvoie son libellé normalisé. `POST /api/v1/eta/locations` calcule une ETA avec une adresse, un véhicule Hiboo, ou un mélange des deux à chaque extrémité :

```json
{
  "origin": { "parc_id": "PF-1233" },
  "destination": { "address": "10 rue de Rivoli, Paris" }
}
```

Pour chaque `parc_id`, l’API vérifie l’existence dans l’instantané Hiboo puis récupère la dernière position GPS. Si le véhicule n’est pas équipé ou qu’aucune position exploitable n’est disponible, le calcul est refusé avec HTTP 422 et un message explicite. L’interface `/route-tester` comprend la conversion unitaire, le test ETA hybride et une simulation animée sur le trajet calculé.

## Télématique Hiboo

Configurez `HIBOO_API_NAME` et `HIBOO_API_KEY` dans `.env` avec les identifiants API Hiboo. L’API se connecte à `POST /login`, renouvelle le JWT après une réponse 401 et garde le token en mémoire jusqu’à neuf jours. `HIBOO_API_BASE_URL` vaut `https://api.hiboo.io` par défaut; utilisez l’URL sandbox fournie par Hiboo pour des identifiants de test.

`POST /api/v1/telematics/check` vérifie un ou plusieurs numéros de parc. `POST /api/v1/telematics/positions` renvoie la dernière position GPS disponible pour les véhicules équipés. Pour un véhicule, transmettez `parc_id`; pour plusieurs, transmettez `parc_ids` :

```json
{
  "parc_ids": ["PF-1233", "ST-1233"]
}
```

Pour un seul véhicule, le corps peut aussi être `{ "parc_id": "PF-1233" }`.

Une interface de test est disponible sur <http://localhost:8000/telematics>. Elle permet de lancer chaque appel, consulter les résultats et ouvrir les coordonnées sur Google Maps.

La liste des équipements Hiboo est préchargée en tâche de fond, paginée par lots de 50, puis conservée 24 heures dans la mémoire et dans la base configurée. Elle est restaurée au redémarrage; si elle est encore valide, elle est réutilisée sans retélécharger la flotte. Chaque page téléchargée est aussi enregistrée comme point de reprise avec son offset confirmé. Après une coupure réseau ou un redémarrage pendant le téléchargement, la prochaine tentative repart de cet offset, sans recommencer les pages déjà reçues. Une fois la liste complète enregistrée, le point de reprise est supprimé. Les erreurs réseau et réponses HTTP temporaires (429, 5xx) sont retentées jusqu’à trois fois avec un délai croissant. Après le premier chargement, les routes télématiques continuent à utiliser le dernier instantané pendant son actualisation; un échec complet sera retenté après cinq minutes. Au tout premier démarrage sans instantané existant, seule la première requête télématique peut attendre la fin du chargement. Les autres routes de l’API restent disponibles. Les positions GPS sont récupérées auprès de Hiboo à chaque appel. Pour un véhicule sans télématique, `equipped` vaut `false` et `position` vaut `null`; un véhicule équipé sans position disponible garde `equipped: true` avec `position: null`.

## Accès API, tokens et quotas

Définissez un secret long dans `API_ADMIN_TOKEN` avant de démarrer l’application. La page <http://localhost:8000/token-management> utilise ce secret pour créer et révoquer des tokens, consulter leur activité et régler les quotas. Le secret administrateur est transmis dans `X-Admin-Token`; il ne remplace pas un token d’accès client.

Les routes ETA et télématique exigent un token client dans `X-API-Token` ou `Authorization: Bearer <token>`. Le secret complet d’un token client n’est affiché qu’à sa création; la base ne conserve que son hash. Les routes santé et configuration publique restent sans authentification.

Chaque token dispose d’un quota journalier indépendant pour chaque route protégée. `API_DAILY_LIMIT_DEFAULT` (1000 par défaut) règle la limite générale; la page d’administration permet de définir une surcharge par endpoint. Les compteurs et dates de quota sont en UTC. Un dépassement renvoie HTTP 429. Les tables d’accès sont créées automatiquement au démarrage dans la base configurée.

## Structure

Le diagramme des composants et des flux est disponible dans [ARCHITECTURE.md](ARCHITECTURE.md).

- `src/greenline_api/api/v1/` : routes HTTP versionnées
- `src/greenline_api/core/` : configuration et préoccupations transverses
- `src/greenline_api/db/` : moteur et sessions SQLAlchemy asynchrones
- `src/greenline_api/services/` : logique métier et intégrations externes
- `src/greenline_api/templates/base.html` et `templates/components/` : structure et composants HTML partagés
- `src/greenline_api/templates/pages/` : une page par interface
- `src/greenline_api/static/css/` et `static/js/` : styles et scripts découplés par page
- `src/greenline_api/main.py` : assemblage de l’application

Les nouveaux domaines métier (interventions, planning, équipes) pourront être ajoutés sous `src/greenline_api/` sans concentrer la logique dans les routes.

## Configuration

Les paramètres sont lus depuis les variables d’environnement ou `.env` : `APP_NAME`, `APP_ENV`, `API_V1_PREFIX`, `DATABASE_URL`, `GOOGLE_MAPS_API_KEY`, `GOOGLE_GEOCODING_API_KEY`, `HIBOO_API_BASE_URL`, `HIBOO_API_NAME`, `HIBOO_API_KEY`, `API_ADMIN_TOKEN` et `API_DAILY_LIMIT_DEFAULT`. Ne jamais committer de secrets réels.

Pour passer d’une base locale SQLite à PostgreSQL, modifiez `DATABASE_URL` (par exemple `postgresql+asyncpg://greenline:greenline@localhost:5432/greenline`) et démarrez l’application : les tables seront créées dans PostgreSQL. Cela ne copie pas les données SQLite existantes; il faudra transférer séparément les quotas, les statistiques et les hashes de tokens, ou recréer les tokens clients.
