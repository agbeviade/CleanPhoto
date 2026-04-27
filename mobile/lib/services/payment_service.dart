import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:url_launcher/url_launcher.dart';

import '../config.dart';
import 'auth_service.dart';
import 'device_service.dart';
import 'premium_service.dart';

/// Description d'un pack hebdomadaire (catalogue dynamique).
class PackPlan {
  final String id; // ex: "pack_10_week"
  final int images;
  final int price;
  final int days;
  final String label;

  const PackPlan({
    required this.id,
    required this.images,
    required this.price,
    required this.days,
    required this.label,
  });

  factory PackPlan.fromJson(String id, Map<String, dynamic> j) => PackPlan(
        id: id,
        images: (j['images'] as num).toInt(),
        price: (j['price'] as num).toInt(),
        days: (j['days'] as num).toInt(),
        label: (j['label'] as String?) ?? id,
      );
}

/// Resultat d'une initiation de paiement.
class PaymentInitResult {
  final String reference;
  final String checkoutUrl;
  final int amount;
  final String currency;
  final String plan;
  final int? packSize;
  final int? expiresInDays;

  const PaymentInitResult({
    required this.reference,
    required this.checkoutUrl,
    required this.amount,
    required this.currency,
    required this.plan,
    this.packSize,
    this.expiresInDays,
  });

  factory PaymentInitResult.fromJson(Map<String, dynamic> j) =>
      PaymentInitResult(
        reference: j['reference'] as String,
        checkoutUrl: j['checkout_url'] as String,
        amount: (j['amount'] as num).toInt(),
        currency: (j['currency'] as String?) ?? 'XOF',
        plan: (j['plan'] as String?) ?? 'pack_10_week',
        packSize: (j['pack_size'] as num?)?.toInt(),
        expiresInDays: (j['expires_in_days'] as num?)?.toInt(),
      );
}

/// Service paiement Premium via GeniusPay (Mobile Money / Cartes).
///
/// Flow:
///   1. startPremiumPurchase() -> POST /api/payments/create
///   2. ouvre checkout_url dans le navigateur (Wave/Orange/MTN/carte)
///   3. apres paiement, le webhook backend active premium
///   4. l'app peut poll pollStatus(reference) pour confirmer
class PaymentService {
  static Uri _u(String path) {
    final base = AppConfig.apiBaseUrl.endsWith('/')
        ? AppConfig.apiBaseUrl.substring(0, AppConfig.apiBaseUrl.length - 1)
        : AppConfig.apiBaseUrl;
    return Uri.parse('$base$path');
  }

  static Future<Map<String, String>> _headers() async {
    final id = await DeviceService.getId();
    final token = AuthService.accessToken;
    return {
      'X-Device-Id': id,
      'Content-Type': 'application/json',
      if (token != null && token.isNotEmpty) 'Authorization': 'Bearer $token',
    };
  }

  /// Catalogue par defaut, affiche INSTANTANEMENT pendant que /api/plans
  /// charge en arriere-plan (cold-start Vercel ~3-5s).
  /// Doit rester synchronise avec backend/_services/payments.py DEFAULT_PACKS.
  static const List<PackPlan> defaultPlans = [
    PackPlan(
        id: 'pack_10_week',
        images: 10,
        price: 1499,
        days: 7,
        label: '10 photos / semaine'),
    PackPlan(
        id: 'pack_50_week',
        images: 50,
        price: 2999,
        days: 7,
        label: '50 photos / semaine'),
    PackPlan(
        id: 'pack_100_week',
        images: 100,
        price: 4999,
        days: 7,
        label: '100 photos / semaine'),
  ];

  /// Recupere le catalogue de packs disponibles a l'achat.
  /// Retourne null si erreur reseau.
  static Future<List<PackPlan>?> fetchPlans() async {
    try {
      final r = await http
          .get(_u('/api/plans'))
          .timeout(const Duration(seconds: 8));
      if (r.statusCode != 200) return null;
      final body = jsonDecode(r.body) as Map<String, dynamic>;
      final raw = (body['plans'] as Map<String, dynamic>?) ?? const {};
      final plans = <PackPlan>[];
      raw.forEach((k, v) {
        if (v is Map<String, dynamic>) plans.add(PackPlan.fromJson(k, v));
      });
      // Tri par nombre d'images croissant
      plans.sort((a, b) => a.images.compareTo(b.images));
      return plans;
    } catch (_) {
      return null;
    }
  }

  /// URLs de callback que GeniusPay appellera apres le paiement.
  /// La WebView in-app les intercepte AVANT chargement et ferme l'ecran.
  /// On utilise des URLs basees sur apiBaseUrl (donc HTTPS valide) pour
  /// que GeniusPay les accepte ; le backend n'a pas besoin d'exposer ces
  /// endpoints (404 = OK, on intercepte avant).
  static const String successUrlPattern = '/payment-return/success';
  static const String errorUrlPattern = '/payment-return/error';

  static String get _callbackBase {
    final base = AppConfig.apiBaseUrl.endsWith('/')
        ? AppConfig.apiBaseUrl.substring(0, AppConfig.apiBaseUrl.length - 1)
        : AppConfig.apiBaseUrl;
    return '$base/payment-return';
  }

  /// Initie un paiement Premium.
  ///
  /// [plan] : id du pack (ex: 'pack_10_week', 'pack_50_week', 'pack_100_week').
  /// [useInAppCallback] : si true (defaut), utilise les URLs de callback
  /// interceptees par CheckoutWebViewScreen. Sinon, GeniusPay garde ses URLs
  /// par defaut.
  static Future<PaymentInitResult> createPayment({
    String plan = 'pack_10_week',
    bool useInAppCallback = true,
  }) async {
    final body = <String, dynamic>{'plan': plan};
    if (useInAppCallback) {
      body['success_url'] = '$_callbackBase/success';
      body['error_url'] = '$_callbackBase/error';
    }
    final r = await http
        .post(
          _u('/api/payments/create'),
          headers: await _headers(),
          body: jsonEncode(body),
        )
        .timeout(const Duration(seconds: 15));
    if (r.statusCode != 200) {
      throw Exception(_extractError(r));
    }
    final json = jsonDecode(r.body) as Map<String, dynamic>;
    return PaymentInitResult.fromJson(json);
  }

  /// Ouvre la page de checkout GeniusPay (navigateur externe).
  ///
  /// Retourne true si l'app a pu lancer l'URL.
  /// Strategie de fallback :
  ///   1. externalApplication (navigateur systeme)
  ///   2. platformDefault (custom tabs / WebView interne)
  ///   3. inAppWebView (dernier recours)
  /// On ne fait PAS canLaunchUrl prealable car il peut renvoyer false a tort
  /// sur Android 11+ si les <queries> sont manquantes (false negative).
  static Future<bool> openCheckout(String checkoutUrl) async {
    final Uri uri;
    try {
      uri = Uri.parse(checkoutUrl);
    } catch (_) {
      return false;
    }
    for (final mode in const [
      LaunchMode.externalApplication,
      LaunchMode.platformDefault,
      LaunchMode.inAppWebView,
    ]) {
      try {
        final ok = await launchUrl(uri, mode: mode);
        if (ok) return true;
      } catch (_) {
        // tente le mode suivant
      }
    }
    return false;
  }

  /// Verifie le status d'un paiement (polling apres retour de la page de paiement).
  ///
  /// Retourne 'pending' | 'completed' | 'failed' | 'expired' | null si introuvable.
  static Future<String?> getStatus(String reference) async {
    try {
      final r = await http
          .get(
            _u('/api/payments/status?reference=$reference'),
            headers: await _headers(),
          )
          .timeout(const Duration(seconds: 8));
      if (r.statusCode != 200) return null;
      final body = jsonDecode(r.body) as Map<String, dynamic>;
      return body['status'] as String?;
    } catch (_) {
      return null;
    }
  }

  /// Polling avec timeout (utile si l'app revient au foreground apres paiement).
  /// Met a jour PremiumService localement quand status=completed.
  static Future<bool> waitForCompletion(
    String reference, {
    Duration timeout = const Duration(minutes: 5),
    Duration interval = const Duration(seconds: 4),
  }) async {
    final deadline = DateTime.now().add(timeout);
    while (DateTime.now().isBefore(deadline)) {
      final status = await getStatus(reference);
      if (status == 'completed') {
        await PremiumService.setPremium(true);
        return true;
      }
      if (status == 'failed' || status == 'expired') {
        return false;
      }
      await Future.delayed(interval);
    }
    return false;
  }

  static String _extractError(http.Response r) {
    try {
      final body = jsonDecode(r.body) as Map<String, dynamic>;
      final detail = body['detail'];
      if (detail is String) return 'HTTP ${r.statusCode}: $detail';
      if (detail is Map) return 'HTTP ${r.statusCode}: ${detail['message'] ?? detail}';
      return 'HTTP ${r.statusCode}: ${r.body}';
    } catch (_) {
      return 'HTTP ${r.statusCode}';
    }
  }
}
