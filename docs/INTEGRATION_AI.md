# Integration du pipeline IA avance (CodeFormer + Real-ESRGAN)

Ce guide explique comment activer le mode **ADVANCED** du backend pour atteindre l'effet "wow"
sur la restauration de visages et l'upscale HD.

## 1. Dependances

Decommenter dans `backend/requirements.txt` :

```
torch==2.2.2
torchvision==0.17.2
basicsr==1.4.2
facexlib==0.3.0
gfpgan==1.3.8
realesrgan==0.3.0
```

Puis :
```powershell
pip install -r requirements.txt
```

> Sur Windows, installer torch GPU si CUDA disponible :
> `pip install torch==2.2.2+cu121 --index-url https://download.pytorch.org/whl/cu121`

## 2. Telechargement des poids modeles

Placer dans `backend/models/` :

| Fichier | Source |
|---------|--------|
| `codeformer.pth` | https://github.com/sczhou/CodeFormer/releases |
| `RealESRGAN_x4plus.pth` | https://github.com/xinntao/Real-ESRGAN/releases |

## 3. Implementer `_restore_advanced`

Ouvrir `backend/services/restore_service.py` et remplacer le corps de `_restore_advanced` par :

```python
def _restore_advanced(self, src_path: str, dst_path: str) -> str:
    import torch
    import cv2
    from basicsr.archs.rrdbnet_arch import RRDBNet
    from realesrgan import RealESRGANer
    from gfpgan import GFPGANer  # CodeFormer-like API

    device = "cuda" if torch.cuda.is_available() else "cpu"

    # Real-ESRGAN
    model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23,
                    num_grow_ch=32, scale=4)
    upsampler = RealESRGANer(
        scale=4,
        model_path=str(REALESRGAN_PATH),
        model=model,
        tile=400, tile_pad=10, pre_pad=0, half=(device == "cuda"),
    )

    # Face restorer (CodeFormer-style)
    face_restorer = GFPGANer(
        model_path=str(CODEFORMER_PATH),
        upscale=2,
        arch="clean",
        channel_multiplier=2,
        bg_upsampler=upsampler,
    )

    img = cv2.imread(src_path, cv2.IMREAD_COLOR)
    _, _, restored = face_restorer.enhance(
        img, has_aligned=False, only_center_face=False, paste_back=True, weight=0.7,
    )
    cv2.imwrite(dst_path, restored, [cv2.IMWRITE_JPEG_QUALITY, 95])
    return dst_path
```

## 4. Verification

```powershell
curl.exe http://localhost:8000/health
```

Reponse attendue :
```json
{"status":"healthy","pipeline":{"mode":"advanced","codeformer":true,"realesrgan":true}}
```

## 5. Notes de performance

| Mode | CPU | GPU |
|------|-----|-----|
| BASIC | 300-800ms | 200-500ms |
| ADVANCED | 8-30s | 1-4s |

Pour rester dans la cible 5-10s en production sans GPU, deployer derriere une queue
(Celery / RQ) ou un worker GPU dedie.
