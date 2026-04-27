# 🍎 Build iOS Souvenir AI via Codemagic

Ce projet **n'a pas de dossier `ios/`** dans le repo. Le workflow Codemagic
le génère automatiquement à chaque build (idempotent), donc tu n'as **rien à
commit côté iOS** pour démarrer.

## 📋 Workflows disponibles dans `codemagic.yaml`

| Workflow | Apple Dev account ? | Sortie | Usage |
|---|---|---|---|
| `ios-debug-unsigned` | ❌ Non | `.app` non signé | Valider que ça compile |
| `ios-release-appstore` | ✅ Oui (99 USD/an) | `.ipa` signé + TestFlight | Distribution App Store |

---

## 🚀 Étape 1 : Premier build de validation (gratuit, sans compte Apple)

Ce workflow vérifie que le code Flutter compile bien sur iOS sans rien
casser. Aucun compte Apple Developer requis.

### A. Créer le compte Codemagic

1. Va sur https://codemagic.io et sign in avec **GitHub**
2. Autorise l'accès au repo `agbeviade/CleanPhoto`
3. Sélectionne le repo → "Set up build" → choisis **"YAML configuration"**
4. Codemagic détecte automatiquement `codemagic.yaml` à la racine

### B. Lancer le build manuellement

1. Dans Codemagic UI → Applications → CleanPhoto → **Start new build**
2. Branch : `main`
3. Workflow : **`Souvenir AI - iOS Debug (unsigned validation build)`**
4. Click **Start new build** → ~15 min

### C. Vérifier les logs

Si le build passe :
- ✅ `Runner.app` est dans les artifacts (téléchargeable)
- ⚠️ Mais tu **ne peux PAS l'installer sur un iPhone** (pas signé)
- 🎯 Objectif : confirmer que le code compile, repérer les erreurs Swift/Pod

Si le build échoue, les erreurs typiques :
- Plugin pas compatible iOS → vérifier la dernière version sur pub.dev
- Pod conflit → bumper `platform :ios, '14.0'` au lieu de 13.0
- Permission Info.plist manquante → ajouter au step `Patch Info.plist`

---

## 🍎 Étape 2 : Build signé pour App Store (99 USD/an)

### A. Pré-requis Apple

1. **Compte Apple Developer Program** : https://developer.apple.com/programs/ (99 USD/an)
2. **App Store Connect** : créer une nouvelle app
   - Bundle ID : `ci.cleanphoto.souvenirai` (ou ce que tu veux, doit être unique)
   - Nom : Souvenir AI
   - Plateforme : iOS
   - Note l'**Apple ID numérique** (ex: `6478123456`) → à mettre dans `APP_STORE_APPLE_ID`

### B. Créer une App Store Connect API Key

1. https://appstoreconnect.apple.com/access/integrations/api
2. **Generate API Key** :
   - Nom : "Codemagic Souvenir"
   - Access : **Admin**
3. Télécharge le fichier `.p8` (une seule fois !)
4. Note l' **Issuer ID**, **Key ID**, et garde le `.p8`

### C. Configurer Codemagic

1. Codemagic UI → Teams → **Integrations** → App Store Connect → **Add key**
   - Référence name : `SOUVENIR_APP_STORE_KEY`
   - Issuer ID : (de l'étape B.4)
   - Key ID : (de l'étape B.4)
   - Upload le `.p8`

2. Codemagic UI → ton app → **Code signing identities** → **iOS**
   - Click "Fetch from App Store Connect" → utilise la clé créée
   - Ça va générer automatiquement le profil de provisioning

### D. Activer le workflow signé

Dans `codemagic.yaml`, **décommenter** les sections marquées `# Decommenter quand...` :

```yaml
ios-release-appstore:
  # ...
  integrations:
    app_store_connect: SOUVENIR_APP_STORE_KEY    # decommenter
  environment:
    # ...
    ios_signing:                                  # decommenter
      distribution_type: app_store
      bundle_identifier: ci.cleanphoto.souvenirai
  # ...
  scripts:
    # ...
    - name: Set bundle id + version from CI       # decommenter
      # ...
    - name: Set up code signing                   # decommenter
      script: xcode-project use-profiles
    - name: Build IPA                             # decommenter
      # ...
  publishing:                                     # decommenter
    app_store_connect:
      auth: integration
      submit_to_testflight: true
```

Mettre à jour `APP_STORE_APPLE_ID` avec l'ID numérique réel.

Commit + push → Codemagic build → IPA → upload TestFlight automatique.

### E. Tester via TestFlight

1. App Store Connect → ton app → TestFlight
2. Ajoute des testeurs (ton email d'abord)
3. Reçois un mail TestFlight → installe sur iPhone via app TestFlight d'Apple
4. Si OK → **Submit for review** → Apple review (~24-48h) → Live App Store

---

## 💰 Coûts récapitulatifs

| Item | Coût |
|---|---|
| Compte Apple Developer | 99 USD/an |
| Codemagic (Free tier) | 500 min/mois gratuits, ensuite 0.038 USD/min Mac M2 |
| Build iOS moyen | ~15-20 min → ~25 builds gratuits/mois |
| **Total mensuel** : | **~8 USD/mois (99/12)** si quota Codemagic respecté |

---

## ⚠️ Limites identifiées avant publication App Store

### 🚫 Paiement externe (GeniusPay) → risque de rejet

Apple **interdit** la vente de contenu numérique via paiement tiers. L'écran
Premium actuel utilise GeniusPay et risque le rejet (guideline 3.1.1).

**Options** :
1. **Désactiver l'écran Premium sur iOS uniquement** (le détecter via
   `Theme.of(context).platform == TargetPlatform.iOS`) → app gratuite limitée
   à 3/jour. Soumission OK.
2. **Implémenter StoreKit / In-App Purchase** → Apple prend 30% (15% pour
   petits éditeurs). Réécrire `payment_service.dart` avec
   `in_app_purchase` package. ~3-5 jours dev.
3. **Argument "biens physiques"** : ne marche PAS pour un service digital.

### 🍎 Sign in with Apple obligatoire

Si tu actives Google Sign-In sur iOS, **Apple exige** Sign in with Apple en
parallèle (guideline 4.8). Ajouter le plugin `sign_in_with_apple` + capability.

### 📸 Permissions Info.plist

Déjà patchées par le workflow CI :
- `NSPhotoLibraryUsageDescription`
- `NSPhotoLibraryAddUsageDescription`
- `NSCameraUsageDescription`
- `LSApplicationQueriesSchemes` (https/http pour url_launcher)

---

## 🎯 Prochaine étape recommandée

1. ✅ Créer compte Codemagic + lancer **`ios-debug-unsigned`**
2. Si OK → décider : Apple Dev account + StoreKit OU iOS gratuit-only
3. Soumettre à TestFlight
4. Soumettre App Store Review
