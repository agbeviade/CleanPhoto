# Deploiement Souvenir AI - GitHub + Vercel + Supabase

Guide complet de mise en production.

## Architecture cloud

```
┌──────────────────┐     git push     ┌──────────────────┐
│  Developer       │ ───────────────▶ │  GitHub          │
│  (local)         │                  │  - source        │
└──────────────────┘                  │  - Actions CI    │
                                      └────────┬─────────┘
                                               │ webhook
                                  ┌────────────┴────────────┐
                                  ▼                          ▼
                       ┌──────────────────┐      ┌───────────────────┐
                       │  Vercel          │      │  Artifacts        │
                       │  /api/*  FastAPI │      │  (APK Flutter)    │
                       │  Pipeline LITE   │      └───────────────────┘
                       └────────┬─────────┘
                                │ Service key
                                ▼
                       ┌──────────────────┐
                       │  Supabase        │
                       │  - Storage       │ (uploads/, outputs/)
                       │  - Postgres      │ (table restorations)
                       │  - Auth          │ (premium futur)
                       └──────────────────┘
                                ▲
                                │ Anon key
                       ┌────────┴─────────┐
                       │  App Flutter     │
                       │  (Android/iOS)   │
                       └──────────────────┘
```

---

## Etape 1 : GitHub

```powershell
cd d:\NewImage
git init
git add .
git commit -m "Initial commit: Souvenir AI MVP"
git branch -M main
git remote add origin https://github.com/<user>/souvenir-ai.git
git push -u origin main
```

GitHub Actions s'execute automatiquement :
- `backend-tests.yml` → pytest LITE mode
- `flutter-build.yml` → APK release telechargeable depuis l'onglet Actions

---

## Etape 2 : Supabase

1. Creer un projet sur [supabase.com](https://supabase.com)
2. **SQL Editor** → coller `supabase/schema.sql` → Run
3. **Storage** → Create bucket `souvenir` (public)
4. **Storage > Policies** sur `souvenir` :
   ```sql
   CREATE POLICY "Public read" ON storage.objects
     FOR SELECT TO anon
     USING (bucket_id = 'souvenir');

   CREATE POLICY "Service write" ON storage.objects
     FOR ALL TO service_role
     USING (bucket_id = 'souvenir')
     WITH CHECK (bucket_id = 'souvenir');
   ```
5. Recuperer dans **Settings > API** :
   - `Project URL`
   - `service_role` (secret)
   - `anon public` (pour l'app Flutter)

---

## Etape 3 : Vercel

1. Aller sur [vercel.com/new](https://vercel.com/new) → importer le repo GitHub
2. **Framework Preset**: Other (Vercel detectera `vercel.json`)
3. **Environment Variables** (Settings > Environment Variables) :

   | Name | Value |
   |------|-------|
   | `REPLICATE_API_TOKEN` | `r8_xxx` (https://replicate.com/account/api-tokens) |
   | `SUPABASE_URL` | `https://xxxxx.supabase.co` |
   | `SUPABASE_SERVICE_KEY` | `eyJ...` (service_role) |
   | `SUPABASE_BUCKET` | `souvenir` |
   | `PIPELINE_MODE` | `replicate` |
   | `MAX_UPLOAD_MB` | `10` |
   | `CORS_ORIGINS` | `*` |
   | `REPLICATE_FIDELITY` | `0.7` (0=plus cree, 1=plus fidele) |
   | `REPLICATE_UPSCALE` | `2` |
   | `DAILY_FREE_LIMIT` | `3` (restaurations gratuites par jour) |

4. **Deploy**

URL finale : `https://<projet>.vercel.app`

Test :
```powershell
curl.exe https://<projet>.vercel.app/api/health
```

Reponse attendue :
```json
{"status":"healthy","pipeline":{"mode":"lite",...},"supabase":true}
```

---

## Etape 4 : App Flutter

```powershell
cd mobile
flutter create --project-name souvenir_ai --org com.souvenirai --platforms=android,ios .
# Restaurer le AndroidManifest et network_security_config personnalises:
git checkout HEAD -- android/app/src/main/AndroidManifest.xml
git checkout HEAD -- android/app/src/main/res/xml/network_security_config.xml

flutter pub get

flutter build apk --release `
  --dart-define=API_BASE_URL=https://<projet>.vercel.app `
  --dart-define=SUPABASE_URL=https://xxxxx.supabase.co `
  --dart-define=SUPABASE_ANON_KEY=eyJ...
```

APK genere : `mobile/build/app/outputs/flutter-apk/app-release.apk`

---

## Pipeline Replicate (recommande - effet wow + serverless)

**Replicate** execute le modele `sczhou/codeformer` sur GPU T4 :
- ~5-10s par image
- ~$0.005-$0.01 par image (pay-per-use, pas de cout idle)
- Combine restauration visages CodeFormer + upscale Real-ESRGAN
- Aucune infrastructure a gerer

### Setup

1. Creer un compte sur [replicate.com](https://replicate.com)
2. Settings > API tokens > Create token
3. Ajouter `REPLICATE_API_TOKEN` dans Vercel env vars
4. Set `PIPELINE_MODE=replicate`

Le service detecte automatiquement le token et bascule en mode replicate. En cas
d'erreur (quota, panne), fallback automatique vers BASIC ou LITE.

### Reglage qualite

- `REPLICATE_FIDELITY=0.7` : equilibre (recommande)
- `REPLICATE_FIDELITY=0.5` : plus de restauration creative (visages tres degrades)
- `REPLICATE_FIDELITY=0.9` : plus fidele a l'original (degats faibles)

## Limitations Vercel selon le mode

| Mode | Vercel Hobby | Vercel Pro | Cout |
|------|:---:|:---:|:---:|
| LITE (Pillow) | ✅ <3s | ✅ | $0 |
| BASIC (cv2) | ⚠️ taille limite | ✅ | $0 |
| **REPLICATE** | ⚠️ timeout 10s tight | ✅ 60s OK | ~$0.01/img |
| ADVANCED (torch local) | ❌ | ❌ | -- |

> Pour Hobby + Replicate : la prediction prend ~5-8s donc tient generalement dans la
> limite 10s, mais activer Pro est plus sur (`maxDuration: 60`).

---

## Verification finale

```powershell
# 1. Health
curl.exe https://<projet>.vercel.app/api/health

# 2. Restauration test
curl.exe -X POST -F "file=@photo.jpg" https://<projet>.vercel.app/api/restore

# 3. Verifier Supabase Storage > Browser souvenir/outputs/

# 4. Verifier Postgres
#    Supabase Studio > Table editor > restorations
```
