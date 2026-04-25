# Souvenir AI - Backend

API FastAPI de restauration de photos anciennes.

## Installation

```powershell
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

API disponible sur http://localhost:8000

## Endpoints

- `GET /health` -> etat + pipeline actif
- `POST /restore` (multipart `file`) -> binaire image restauree
- `POST /restore-json` -> JSON `{status, restored_image_url, ...}`
- `GET /outputs/<filename>` -> images restaurees servies en static

## Test rapide

```powershell
curl.exe -X POST -F "file=@photo.jpg" http://localhost:8000/restore-json
```

## Modes du pipeline

### BASIC (par defaut, runnable immediatement)
- `cv2.fastNlMeansDenoisingColored` -> debruitage
- CLAHE (LAB) -> contraste local adaptatif
- HaarCascade face detection -> sharpening + bilateral filter sur visages
- Lanczos upscale x1.5/x2 si image < 1500px
- Unsharp mask global
- Boost saturation + warmth

Resultat: 300-800ms par image, effet visible.

### ADVANCED (optionnel - effet wow)
1. Decommenter `torch`, `basicsr`, `realesrgan`, `gfpgan` dans `requirements.txt`
2. `pip install -r requirements.txt`
3. Telecharger les poids dans `models/` :
   - https://github.com/sczhou/CodeFormer/releases -> `codeformer.pth`
   - https://github.com/xinntao/Real-ESRGAN/releases -> `RealESRGAN_x4plus.pth`
4. Implementer `_restore_advanced()` dans `services/restore_service.py`

Le service bascule automatiquement vers ADVANCED si les poids sont presents.

## Structure

```
backend/
  main.py                    # FastAPI app + routes
  services/
    restore_service.py       # Pipeline IA (basic + advanced hook)
  models/                    # Poids modeles (a telecharger)
  uploads/                   # Photos sources (auto-cree)
  outputs/                   # Photos restaurees (auto-cree, servies en static)
```
