# 🛒 Setup In-App Purchase (StoreKit) iOS — Souvenir AI

Ce guide explique comment configurer **App Store Connect** pour vendre les
3 packs de photos sur iOS, et comment tester en sandbox avant publication.

---

## 📋 Pré-requis

- ✅ Compte **Apple Developer Program** actif (99 USD/an)
- ✅ App créée dans App Store Connect avec Bundle ID `ci.cleanphoto.souvenirai`
- ✅ Backend déployé sur Vercel avec endpoint `/api/payments/apple/verify`
- ✅ Variable d'env `APPLE_BUNDLE_ID=ci.cleanphoto.souvenirai` côté backend

---

## 🎯 Étape 1 — Créer les 3 In-App Purchases

### A. Aller dans App Store Connect

1. https://appstoreconnect.apple.com → ton app → **Features** → **In-App Purchases**
2. Click **+** → choisis **Consumable** (chaque pack se consomme à l'achat)

### B. Créer les 3 produits

| Reference Name | Product ID | Type | Price Tier | Prix |
|---|---|---|---|---|
| Pack 10 photos | `pack_10_ios` | Consumable | **Tier 3** | $2.99 |
| Pack 50 photos | `pack_50_ios` | Consumable | **Tier 5** | $4.99 |
| Pack 100 photos | `pack_100_ios` | Consumable | **Tier 9** | $8.99 |

⚠️ Les **Product IDs doivent matcher EXACTEMENT** ceux du code (constante
`IapService.productIds` dans `mobile/lib/services/iap_service.dart` et
`PRODUCT_TO_PACK` dans `api/_services/apple_iap.py`).

### C. Localisations obligatoires

Pour chaque produit, ajoute au moins l'**anglais** :

**`pack_10_ios`** :
- Display Name : `10 photos`
- Description : `10 photo restorations valid for 7 days`

**`pack_50_ios`** :
- Display Name : `50 photos`
- Description : `50 photo restorations valid for 7 days`

**`pack_100_ios`** :
- Display Name : `100 photos`
- Description : `100 photo restorations valid for 7 days`

### D. Review Information

Pour chaque produit :
- Screenshot : capture du `PremiumScreen` montrant le pack
- Notes : "Premium pack of N photo restorations, valid 7 days"

### E. Soumettre

Click **Submit for Review** sur chaque produit. Apple les valide en même
temps que la première soumission de l'app (après ton premier build via
TestFlight).

---

## 🧪 Étape 2 — Tester en Sandbox (avant publication)

### A. Créer un compte Sandbox Tester

1. App Store Connect → **Users and Access** → **Sandbox Testers**
2. Click **+** → crée un compte avec une **email jetable** (PAS ton vrai
   Apple ID, car le compte sandbox est lié à cette email pour la vie)
3. Note le mot de passe

### B. Configurer iOS pour utiliser ce compte

**iOS 16+** :
1. **Settings** → **App Store** → tout en bas → **Sandbox Account**
2. **Sign in** avec le compte sandbox

**iOS 15-** :
1. **Settings** → **App Store** → sign out de ton vrai Apple ID
2. À la première tentative d'achat dans l'app, iOS demandera un Apple ID :
   utilise le sandbox

### C. Forcer le backend en mode sandbox (DEV uniquement)

Sur Vercel staging (ou local) :
```
APPLE_USE_SANDBOX=1
```

**⚠️ NE PAS METTRE EN PROD** : avec cette variable, les vrais receipts seront
rejetés. Le backend sait fallback automatiquement si Apple renvoie status
21007 (receipt sandbox sur prod), donc tu peux laisser cette variable à 0
en prod et l'app marchera quand même en sandbox testing.

### D. Tester un achat

1. Lance l'app sur un iPhone réel (sandbox **ne marche PAS sur le simulator**)
2. Va dans **Profil → Devenir Premium**
3. Tap sur un pack → bouton "Payer $2.99" → dialog Apple → "Buy"
4. Confirme avec Face ID / mot de passe sandbox
5. Tu dois voir **"Pack activé !"** + retour Premium activé

Vérifie côté backend (logs Vercel) :
```
INFO Apple verify: pack_10_week active pour device=...
INFO Nouveau paiement Apple (sandbox)
```

---

## 🔐 Étape 3 — Variables d'environnement Vercel

Ajoute dans **Vercel Project Settings → Environment Variables** :

| Var | Valeur | Quand |
|---|---|---|
| `APPLE_BUNDLE_ID` | `ci.cleanphoto.souvenirai` | Toujours |
| `APPLE_IAP_ENABLED` | `1` | Toujours (par défaut) |
| `APPLE_USE_SANDBOX` | `1` | UNIQUEMENT staging/dev |
| `APPLE_SHARED_SECRET` | (laisser vide) | Optionnel — pas besoin pour consumables |

> 💡 `APPLE_SHARED_SECRET` n'est nécessaire que pour les **subscriptions
> auto-renouvelables**. Pour des Consumables, Apple n'en a pas besoin.

---

## 🚦 Étape 4 — Premier build TestFlight

1. Bump la version dans `mobile/pubspec.yaml` (ex: `1.1.0+2`)
2. Lance le workflow Codemagic **`ios-release-appstore`** (après avoir
   décommenté les sections signing — voir `IOS_BUILD.md`)
3. L'IPA est upload automatiquement sur TestFlight
4. Active les testeurs internes dans App Store Connect
5. Reçois un mail TestFlight → installe l'app via l'app **TestFlight** d'Apple
6. Teste l'achat avec ton compte sandbox

---

## ⚠️ Erreurs courantes et solutions

### "Cannot connect to iTunes Store"
- Vérifie que les Product IDs matchent exactement
- Le produit doit être au statut **"Ready to Submit"** (pas "Missing Metadata")
- Wait ~2h après création — le système Apple cache les produits

### "This In-App Purchase has already been bought"
- Normal en sandbox : les Consumables sont consommables côté backend mais
  pas en sandbox de la même manière qu'en prod
- Solution : utilise un nouveau compte sandbox pour re-tester

### "Receipt invalide (Apple status=21002)"
- Le receipt envoyé est mal formé / corrompu
- Vérifie côté Flutter que tu envoies bien `verificationData.serverVerificationData`
  (et pas `localVerificationData` qui est local-only)

### Backend renvoie 503 "Apple IAP désactivé"
- Vérifie `APPLE_IAP_ENABLED=1` sur Vercel

### Le bouton affiche `...` au lieu d'un prix
- Les produits ne sont pas (encore) chargés depuis App Store Connect
- Causes possibles : Product IDs mal écrits, app pas encore en TestFlight,
  pays du compte sandbox ne supporte pas le produit

---

## 📊 Économie : Combien Apple prend-il ?

| Scenario | Pourcentage Apple |
|---|---|
| Année 1 d'un compte App Store | 30% |
| Année 1 si tu rejoins **Small Business Program** (CA < $1M) | **15%** |
| Renouvellement abonnement après 1 an | 15% (même hors Small Biz) |

➡️ **Inscris-toi au Small Business Program** dès l'ouverture de ton compte
Apple Developer : économie immédiate de 50% des frais.
https://developer.apple.com/app-store/small-business-program/

### Calcul net pour un pack 10 photos à $2.99

| | Standard 30% | Small Business 15% |
|---|---|---|
| Prix client | $2.99 | $2.99 |
| Apple prend | $0.90 | $0.45 |
| Tu reçois | **$2.09** | **$2.54** |

À comparer aux **1499 F CFA ≈ $2.45** sur Android via GeniusPay (frais
~3-5%, donc tu reçois ~$2.33 net). **iOS Small Business est légèrement
plus rentable que GeniusPay.**

---

## 🎓 Aller plus loin

- [Doc Apple verifyReceipt](https://developer.apple.com/documentation/appstorereceipts/verifyreceipt)
- [in_app_purchase Flutter](https://pub.dev/packages/in_app_purchase)
- [App Store Review Guidelines (3.1.1 IAP)](https://developer.apple.com/app-store/review/guidelines/#in-app-purchase)
- [Codemagic iOS code signing](https://docs.codemagic.io/yaml-code-signing/signing-ios/)
