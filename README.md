# Souvenir AI - MVP

> Restauration de photos anciennes par IA. Application mobile Flutter + backend Python FastAPI.

## Architecture

```
NewImage/
  api/                       # FastAPI app (Vercel serverless entry)
    index.py                 # Routes /api/restore, /api/health
    _services/
      restore_service.py     # Pipeline LITE / BASIC / ADVANCED
      supabase_client.py     # Storage + Postgres
  backend/                   # Local dev (uvicorn) + tests
    main.py                  # Lance api.index:app en local
    tests/                   # pytest
  mobile/                    # App Flutter
  supabase/                  # Schema SQL + doc
  .github/workflows/         # CI: tests + build APK
  vercel.json                # Config Vercel
  requirements.txt           # Deps LITE (Vercel)
  .env.example               # Variables d'env
```

**Stack cloud** : GitHub (source + CI) → Vercel (API) → Supabase (storage/DB/auth) → App Flutter.

Voir [DEPLOYMENT.md](DEPLOYMENT.md) pour le guide de mise en production complet.

---

## 1. Demarrer le backend (local)

Prerequis : **Python 3.10+**

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r backend\requirements-dev.txt
python backend\main.py
```

Le serveur ecoute sur `http://0.0.0.0:8000`.

Test :
```powershell
curl.exe http://localhost:8000/api/health
curl.exe -X POST -F "file=@photo.jpg" http://localhost:8000/api/restore --output restored.jpg
```

### Pipeline IA (3 modes auto-detectes)

- **LITE** (Pillow only, ~10MB) : compatible Vercel serverless
  - Auto-contrast + median denoise + UnsharpMask + boost saturation
- **BASIC** (+ OpenCV) : runnable immediatement en local
  - Denoise (Non-Local Means)
  - CLAHE (contraste local adaptatif)
  - Detection visages (Haar) + sharpening + bilateral filter cible
  - Upscale Lanczos x1.5/x2
  - Unsharp mask + boost saturation
  - Temps : ~500ms par image

- **ADVANCED** (optionnel - effet wow maximal) : CodeFormer + Real-ESRGAN
  - Voir `backend/README.md` section "ADVANCED" pour activer.
  - Necessite GPU recommande, modeles ~500 Mo a telecharger.

---

## 2. Demarrer l'app Flutter

Prerequis : **Flutter 3.19+**, Android Studio, JDK 17.

**Premiere installation** - generer les dossiers natifs (android/, ios/, etc.) :

```powershell
cd mobile
flutter create --project-name souvenir_ai --org com.souvenirai --platforms=android,ios .
git checkout HEAD -- android/app/src/main/AndroidManifest.xml
git checkout HEAD -- android/app/src/main/res/xml/network_security_config.xml
flutter pub get
```

> Le code source (`lib/`, `pubspec.yaml`, `assets/`) est preserve.
> Apres `flutter create`, copier le `AndroidManifest.xml` fourni par-dessus celui genere :
> `mobile/android/app/src/main/AndroidManifest.xml` (deja present dans le repo).
> Et conserver `mobile/android/app/src/main/res/xml/network_security_config.xml`.

Ensuite, lancer :

```powershell
flutter run
```

### Configuration de l'URL backend

Par defaut : `http://10.0.2.2:8000` (loopback emulateur Android vers PC hote).

Pour appareil physique sur le meme Wi-Fi :
```powershell
flutter run --dart-define=API_BASE_URL=http://192.168.1.42:8000
```

Pour pointer sur Vercel + Supabase (production) :
```powershell
flutter run `
  --dart-define=API_BASE_URL=https://your-app.vercel.app `
  --dart-define=SUPABASE_URL=https://xxxxx.supabase.co `
  --dart-define=SUPABASE_ANON_KEY=eyJ...
```

### Construire l'APK de test

```powershell
flutter build apk --release
# APK genere dans build/app/outputs/flutter-apk/app-release.apk
```

---

## 3. Parcours utilisateur (MVP)

```
Accueil
  -> [Galerie] ou [Camera]
  -> Previsualisation
  -> [Restaurer la photo]   (POST /restore)
  -> Ecran resultat
       -> Slider AVANT/APRES interactif
       -> [Telecharger] (galerie Android)
       -> [Partager] (share_plus)
```

## 4. Fonctionnalites livrees

- [x] **Splash screen** + routing intelligent (onboarding/home)
- [x] **Onboarding 3 slides** emotionnels (premiere ouverture)
- [x] Ecran d'accueil avec logo, CTA Galerie/Camera, previsualisation
- [x] **Indicateur de connexion backend** en temps reel
- [x] Upload photo (JPG/JPEG/PNG, max 10 MB)
- [x] Endpoint `POST /restore` (binaire) et `POST /restore-json` (URL)
- [x] Pipeline IA BASIC : denoise + correction flou + restauration visages + upscale HD + contraste
- [x] **Pipeline IA ADVANCED** : Real-ESRGAN + CodeFormer/GFPGAN (auto-detection)
- [x] Slider avant/apres interactif (drag + tap)
- [x] Telechargement vers galerie + partage natif
- [x] Historique local (5 dernieres restaurations) avec **ecran dedie + thumbnails** + ouverture comparaison
- [x] **Tests backend** (pytest, 13 cas couverts)
- [x] **Quota anonyme** : 3 restaurations / 24h via X-Device-Id (Supabase ou memoire)
- [x] **Watermark** automatique sur version gratuite (Pillow)
- [x] **Ecran Premium upsell** (mensuel + annuel) avec hook IAP a brancher
- [x] **Endpoint `/api/quota`** + headers X-Quota-* + 429 si depasse
- [x] UI minimaliste, palette blanc/bleu doux/rouge accent

## 5. Stack

| Couche | Technologies |
|--------|-------------|
| Frontend | Flutter 3.19, Material 3, google_fonts (Inter), image_picker, share_plus, image_gallery_saver_plus, http |
| Backend | FastAPI, Uvicorn, OpenCV, Pillow, NumPy |
| IA (basic) | HaarCascade + CLAHE + Lanczos + Unsharp |
| IA (advanced) | CodeFormer + Real-ESRGAN (hooks prets) |

## 6. Tester le backend

```powershell
cd backend
.\venv\Scripts\activate
pytest -q
```

Tests inclus : routes `/`, `/health`, `/restore` (binaire + JSON), gestion d'erreurs (formats invalides, fichier vide).

## 7. Roadmap post-MVP

- Integration CodeFormer + Real-ESRGAN (voir `docs/INTEGRATION_AI.md`)
- Authentification + comptes utilisateurs
- Stripe / Google Play Billing pour Premium
- Watermark version gratuite
- Mode offline (modele light embarque via TFLite)
- Publication Play Store beta

---

## Licence

MVP proprietaire - usage interne.
