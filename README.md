# GreenLine ETA API

API évolutive pour la gestion de l’ETA (heure d’arrivée estimée) des interventions.

## Démarrage local

Prérequis : Python 3.12+ et Docker Compose.

1. Copier `.env.example` vers `.env` et adapter les valeurs si nécessaire.
2. Démarrer l’API et PostgreSQL :

   ```bash
   docker compose up --build
   ```

3. Ouvrir l’interface de test : <http://localhost:8000/>
4. Ouvrir la documentation interactive : <http://localhost:8000/docs>
5. Vérifier l’état de l’API : <http://localhost:8000/api/v1/health>

Pour lancer uniquement l’API depuis un environnement Python :

```bash
python -m venv .venv
# Activer l’environnement, puis :
pip install -e .
uvicorn greenline_api.main:app --reload --app-dir src
```

## Interface et carte Google

La page `/` utilise Google Maps JavaScript API pour afficher la carte. Cliquez sur « Départ » ou « Arrivée », puis sur la carte pour définir les coordonnées, ou saisissez-les directement. « Calculer l’ETA » appelle `POST /api/v1/eta` et trace la géométrie de route retournée par Google Routes.

Renseignez `GOOGLE_MAPS_API_KEY` dans `.env` avec une clé dédiée à la carte navigateur. Dans Google Cloud, activez Maps JavaScript API et la facturation ; restreignez cette clé au référent de l’application (pour un test local : `http://localhost:8000/*`) et à Maps JavaScript API. Cette clé est visible dans le navigateur par conception et ne sert qu’à la carte.

Le calcul d’itinéraire utilise séparément les identifiants Application Default Credentials (ADC) du serveur. Activez Routes API et la facturation dans le même projet Google Cloud, puis créez les identifiants sur la machine qui exécute l’API :

- **Python local sous Windows :** exécutez `gcloud auth application-default login` dans PowerShell. Le client Google détectera le fichier ADC de votre profil Windows.
- **Docker Compose sous Windows :** exécutez la même commande sur l’hôte avant `docker compose up --build`. Compose monte en lecture seule `%APPDATA%\gcloud\application_default_credentials.json` dans le conteneur et définit `GOOGLE_APPLICATION_CREDENTIALS` pour le client.

Ne confondez pas la clé navigateur `GOOGLE_MAPS_API_KEY` avec les identifiants ADC : la première ne donne pas accès au calcul serveur. Pour un déploiement, utilisez l’identité de service ou le mécanisme d’identifiants ADC fourni par l’environnement plutôt que de copier les identifiants personnels du poste de développement.

## Calcul d’ETA

`POST /api/v1/eta` reçoit les coordonnées GPS de départ et d’arrivée et retourne l’heure d’arrivée estimée en UTC, la durée, la distance et la géométrie encodée de l’itinéraire. Le calcul utilise le client Python `google-maps-routing`, en mode voiture et avec estimation tenant compte du trafic lorsque les données sont disponibles.

Exemple de corps JSON :

```json
{
  "origin": { "latitude": 48.8566, "longitude": 2.3522 },
  "destination": { "latitude": 48.8584, "longitude": 2.2945 }
}
```

## Structure

- `src/greenline_api/api/v1/` : routes HTTP versionnées
- `src/greenline_api/core/` : configuration et préoccupations transverses
- `src/greenline_api/db/` : moteur et sessions SQLAlchemy asynchrones
- `src/greenline_api/services/` : logique métier et intégrations externes
- `src/greenline_api/static/` : interface de test
- `src/greenline_api/main.py` : assemblage de l’application

Les nouveaux domaines métier (interventions, planning, équipes) pourront être ajoutés sous `src/greenline_api/` sans concentrer la logique dans les routes.

## Configuration

Les paramètres sont lus depuis les variables d’environnement ou `.env` : `APP_NAME`, `APP_ENV`, `API_V1_PREFIX`, `DATABASE_URL` et `GOOGLE_MAPS_API_KEY`. Ne jamais committer de secrets réels.
