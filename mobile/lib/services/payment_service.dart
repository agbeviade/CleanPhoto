import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:url_launcher/url_launcher.dart';

import '../config.dart';
import 'auth_service.dart';
import 'device_service.dart';
import 'premium_service.dart';

/// Resultat d'une initiation de paiement.
class PaymentInitResult {
  final String reference;
  final String checkoutUrl;
  final int amount;
  final String currency;
  final String plan;

  const PaymentInitResult({
    required this.reference,
    required this.checkoutUrl,
    required this.amount,
    required this.currency,
    required this.plan,
  });

  factory PaymentInitResult.fromJson(Map<String, dynamic> j) =>
      PaymentInitResult(
        reference: j['reference'] as String,
        checkoutUrl: j['checkout_url'] as String,
        amount: (j['amount'] as num).toInt(),
        currency: (j['currency'] as String?) ?? 'XOF',
        plan: (j['plan'] as String?) ?? 'monthly',
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

  /// Initie un paiement Premium.
  ///
  /// [plan] : 'monthly' (default, 30 jours) ou 'lifetime' (a vie).
  static Future<PaymentInitResult> createPayment({
    String plan = 'monthly',
  }) async {
    final r = await http
        .post(
          _u('/api/payments/create'),
          headers: await _headers(),
          body: jsonEncode({'plan': plan}),
        )
        .timeout(const Duration(seconds: 15));
    if (r.statusCode != 200) {
      throw Exception(_extractError(r));
    }
    final body = jsonDecode(r.body) as Map<String, dynamic>;
    return PaymentInitResult.fromJson(body);
  }

  /// Ouvre la page de checkout GeniusPay (navigateur externe).
  ///
  /// Retourne true si l'app a pu lancer l'URL.
  static Future<bool> openCheckout(String checkoutUrl) async {
    final uri = Uri.parse(checkoutUrl);
    if (!await canLaunchUrl(uri)) return false;
    return launchUrl(uri, mode: LaunchMode.externalApplication);
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
