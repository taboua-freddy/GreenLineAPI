# Architecture GreenLine ETA API

## Vue d’ensemble

```mermaid
flowchart LR
    Client[Client API]
    subgraph Runtime[Application GreenLine — FastAPI]
        UI[Interfaces HTML servies par l’API<br/>ETA · simulation · adresses/parcs<br/>télématique · référence · tokens]
        API[Routes HTTP v1<br/>health · config · ETA · géocodage<br/>ETA hybride · télématique · admin]
        Access[Accès API<br/>token client + quotas par route<br/>ou secret administrateur]
        Logic[Services<br/>itinéraires · géocodage · Hiboo]
        Persistence[SQLAlchemy asynchrone<br/>sessions et modèles]
        UI -->|appels API| API
        API -->|routes protégées| Access
        Access --> Persistence
        API --> Logic
        Logic --> Persistence
    end

    DB[(Base de données<br/>PostgreSQL sous Docker<br/>SQLite en local<br/>tokens · quotas · usages · cache Hiboo)]
    RoutesAPI[Google Routes API<br/>route voiture avec trafic]
    GeoAPI[Google Geocoding API<br/>adresse → coordonnées]
    Maps[Google Maps JavaScript API<br/>carte dans le navigateur]
    Hiboo[API Hiboo<br/>JWT · flotte · positions GPS]

    Client -->|HTTP / JSON| API
    Client -->|pages HTML| UI
    Persistence --> DB
    Logic -->|ADC côté serveur| RoutesAPI
    Logic -->|clé serveur| GeoAPI
    Logic -->|HTTPS avec JWT| Hiboo
    Logic -.->|cache flotte en mémoire<br/>et instantané persistant| DB
    UI -->|clé navigateur| Maps
```

## Chemins métier

### Calcul d’ETA

```mermaid
sequenceDiagram
    participant C as Client / interface
    participant A as Route POST /api/v1/eta
    participant T as Contrôle token et quota
    participant G as Google Routes API
    participant D as Base de données

    C->>A: Coordonnées départ et arrivée + token client
    A->>T: Vérification du token
    T->>D: Vérifier le hash et incrémenter le quota journalier
    D-->>T: Token valide et quota disponible
    A->>G: Calcul voiture avec trafic
    G-->>A: Durée, distance et polyline
    A-->>C: ETA UTC et détails du trajet
```

### ETA depuis des adresses et/ou des véhicules

```mermaid
sequenceDiagram
    participant C as Interface / client
    participant A as POST /api/v1/eta/locations
    participant T as Contrôle token et quota
    participant G as Google Geocoding API
    participant H as Service Hiboo
    participant X as API Hiboo
    participant R as Google Routes API

    C->>A: Origine et destination (adresse et/ou parc_id)
    A->>T: Vérification du token et quota
    T-->>A: Accès autorisé
    par Résolution des deux emplacements
        A->>G: Géocoder chaque adresse
        G-->>A: Coordonnées GPS
    and
        A->>H: Chercher les équipements pour chaque parc_id
        H->>X: Positions GPS récentes
        X-->>H: Position du véhicule
        H-->>A: Coordonnées GPS
    end
    A->>R: Calcul de route à partir des coordonnées résolues
    R-->>A: Durée, distance et polyline
    A-->>C: ETA et détails des emplacements et du trajet
```

### Télématique

```mermaid
sequenceDiagram
    participant C as Client
    participant A as Routes /api/v1/telematics/*
    participant T as Contrôle token et quota
    participant H as Service Hiboo
    participant D as Base de données
    participant X as API Hiboo

    C->>A: Numéro(s) de parc + token client
    A->>T: Vérification du token
    T->>D: Vérifier le hash et incrémenter le quota journalier
    D-->>T: Token valide et quota disponible
    A->>H: Résoudre les équipements de la flotte
    H->>D: Charger / enregistrer l’instantané de flotte
    H->>X: Connexion Hiboo (si nécessaire) puis lecture des positions
    X-->>H: Équipements et positions
    H-->>A: Résultats normalisés
    A-->>C: Réponse JSON enveloppée
```

## Composants et déploiement

- **API et interfaces** : FastAPI sert les routes versionnées, la documentation et les pages de test (`/`, `/live`, `/route-tester`, `/telematics`, `/api-reference`, `/token-management`). Les réponses JSON partagent une enveloppe et les erreurs sont normalisées.
- **Routes** : `/api/v1/eta` calcule depuis des coordonnées; `/api/v1/geocode` convertit une adresse; `/api/v1/eta/locations` résout séparément chaque adresse ou parc Hiboo puis calcule l’itinéraire. Les routes télématiques vérifient l’équipement ou renvoient les positions.
- **Accès** : ETA, géocodage, ETA hybride et télématique requièrent un token client et un quota journalier par endpoint. `/api/v1/admin/*` utilise le secret administrateur; santé et configuration publique restent ouvertes.
- **Persistance** : SQLAlchemy asynchrone stocke les tokens (hashés), quotas, usages et instantané Hiboo. SQLite est utilisé en lancement Python local; Docker Compose relie l’API à PostgreSQL.
- **Google** : Routes API calcule les trajets via les identifiants ADC du serveur. Geocoding API utilise une clé serveur dédiée. Maps JavaScript utilise une clé navigateur publique pour afficher la carte.
- **Hiboo** : le service gère le JWT, les reprises sur erreurs temporaires et le cache de flotte (mémoire, durée de vie de 24 h, persistance en base). La flotte se rafraîchit en arrière-plan; les positions sont demandées à Hiboo à chaque appel.
- **Démarrage et conteneurs** : au démarrage, l’application crée le schéma d’accès et restaure le cache Hiboo, puis lance son actualisation si Hiboo est configuré. Docker Compose lance l’API sur le port `8000` et PostgreSQL `16-alpine` sur `5432`; la base utilise un volume et une sonde de santé. Le fichier ADC de l’hôte est monté en lecture seule dans l’API.
