import 'dart:async';
import 'dart:convert';
import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:in_app_purchase/in_app_purchase.dart';

import '../config.dart';
import 'auth_service.dart';
import 'device_service.dart';

/// Wrapper autour de `in_app_purchase` pour Apple StoreKit (iOS).
///
/// Flux :
///   1. `init()` au demarrage : ecoute le stream des achats en cours/restaures
///   2. `fetchProducts()` : recupere les 3 packs depuis App Store Connect
///   3. `buy(productId)` : declenche le dialog Apple
///   4. Stream callback `_onPurchaseUpdated` : envoie le receipt au backend
///   5. Backend valide via Apple verifyReceipt et active le pack
///
/// Cote Android : a configurer separement (Google Play Billing) - non couvert ici.
class IapService {
  IapService._();
  static final IapService instance = IapService._();

  /// IDs des produits dans App Store Connect (a creer en face dans
  /// la console Apple, en mode "Consumable").
  static const Set<String> productIds = {
    'pack_10_ios',
    'pack_50_ios',
    'pack_100_ios',
  };

  final InAppPurchase _iap = InAppPurchase.instance;
  StreamSubscription<List<PurchaseDetails>>? _sub;
  bool _initialized = false;

  /// Map productId -> ProductDetails (rempli apres fetchProducts).
  Map<String, ProductDetails> _products = {};

  /// Resultats async des achats : productId -> Completer<bool>
  /// (true = activated, false = failed/canceled).
  final Map<String, Completer<IapResult>> _pendingPurchases = {};

  /// Indique si la plateforme supporte les IAP (iOS uniquement pour l'instant).
  bool get isSupported => !kIsWeb && Platform.isIOS;

  Map<String, ProductDetails> get products => _products;

  /// Initialise le listener StoreKit. A appeler une fois au demarrage.
  Future<void> init() async {
    if (_initialized || !isSupported) return;
    _initialized = true;

    final available = await _iap.isAvailable();
    if (!available) {
      debugPrint('[IAP] StoreKit non disponible');
      return;
    }

    _sub = _iap.purchaseStream.listen(
      _onPurchaseUpdated,
      onError: (Object err) {
        debugPrint('[IAP] purchaseStream error: $err');
      },
    );
  }

  void dispose() {
    _sub?.cancel();
    _sub = null;
    _initialized = false;
  }

  /// Recupere les produits depuis App Store Connect.
  /// Retourne la map productId -> ProductDetails (vide si echec).
  Future<Map<String, ProductDetails>> fetchProducts() async {
    if (!isSupported) return {};
    if (!_initialized) await init();

    final response = await _iap.queryProductDetails(productIds);
    if (response.error != null) {
      debugPrint('[IAP] queryProductDetails error: ${response.error}');
    }
    if (response.notFoundIDs.isNotEmpty) {
      debugPrint('[IAP] productIds introuvables: ${response.notFoundIDs}');
    }
    _products = {
      for (final p in response.productDetails) p.id: p,
    };
    return _products;
  }

  /// Lance l'achat d'un produit. Resout quand l'achat est valide
  /// cote backend (ou rejete par l'utilisateur).
  ///
  /// Throws [IapException] si la plateforme ne supporte pas IAP.
  Future<IapResult> buy(String productId) async {
    if (!isSupported) {
      throw IapException('IAP non supporte sur cette plateforme');
    }
    final product = _products[productId];
    if (product == null) {
      // Tente un re-fetch au cas ou l'init n'a pas eu lieu
      await fetchProducts();
      final retry = _products[productId];
      if (retry == null) {
        throw IapException('Produit $productId introuvable dans App Store');
      }
    }
    final details = _products[productId]!;

    // Si un completer existe deja pour ce produit, on l'annule
    _pendingPurchases[productId]?.completeError(
      IapException('Nouvel achat lance, ancien annule'),
    );

    final completer = Completer<IapResult>();
    _pendingPurchases[productId] = completer;

    final param = PurchaseParam(productDetails: details);
    final ok = await _iap.buyConsumable(
      purchaseParam: param,
      autoConsume: true,
    );
    if (!ok) {
      _pendingPurchases.remove(productId);
      completer.complete(IapResult.failed('buyConsumable refuse par StoreKit'));
    }
    return completer.future;
  }

  /// Restaure les achats existants (obligatoire pour validation Apple).
  Future<void> restorePurchases() async {
    if (!isSupported) return;
    await _iap.restorePurchases();
  }

  /// Stream callback : envoie le receipt au backend pour validation.
  Future<void> _onPurchaseUpdated(List<PurchaseDetails> purchases) async {
    for (final p in purchases) {
      switch (p.status) {
        case PurchaseStatus.pending:
          // En cours -> on attend le prochain event
          break;

        case PurchaseStatus.error:
          debugPrint('[IAP] error productId=${p.productID} '
              'msg=${p.error?.message}');
          _resolvePending(
            p.productID,
            IapResult.failed(p.error?.message ?? 'Erreur achat'),
          );
          if (p.pendingCompletePurchase) {
            await _iap.completePurchase(p);
          }
          break;

        case PurchaseStatus.canceled:
          _resolvePending(p.productID, IapResult.canceled());
          if (p.pendingCompletePurchase) {
            await _iap.completePurchase(p);
          }
          break;

        case PurchaseStatus.purchased:
        case PurchaseStatus.restored:
          // Validation cote backend OBLIGATOIRE
          final receipt = p.verificationData.serverVerificationData;
          final activated = await _verifyOnBackend(
            receiptData: receipt,
            productId: p.productID,
          );
          _resolvePending(
            p.productID,
            activated.success
                ? IapResult.success(productId: p.productID,
                                     plan: activated.plan)
                : IapResult.failed(activated.errorMessage
                    ?? 'Validation backend echouee'),
          );
          // Marque la transaction comme terminee cote StoreKit
          if (p.pendingCompletePurchase) {
            await _iap.completePurchase(p);
          }
          break;
      }
    }
  }

  void _resolvePending(String productId, IapResult result) {
    final c = _pendingPurchases.remove(productId);
    if (c != null && !c.isCompleted) {
      c.complete(result);
    }
  }

  /// POST le receipt sur /api/payments/apple/verify et retourne le resultat.
  Future<_BackendVerifyResult> _verifyOnBackend({
    required String receiptData,
    required String productId,
  }) async {
    try {
      final base = AppConfig.apiBaseUrl.endsWith('/')
          ? AppConfig.apiBaseUrl
              .substring(0, AppConfig.apiBaseUrl.length - 1)
          : AppConfig.apiBaseUrl;
      final uri = Uri.parse('$base/api/payments/apple/verify');

      final deviceId = await DeviceService.getId();
      final token = AuthService.accessToken;

      final headers = <String, String>{
        'Content-Type': 'application/json',
        'X-Device-Id': deviceId,
        if (token != null && token.isNotEmpty) 'Authorization': 'Bearer $token',
      };

      final body = jsonEncode({
        'receipt_data': receiptData,
        'product_id': productId,
      });

      final resp = await http
          .post(uri, headers: headers, body: body)
          .timeout(const Duration(seconds: 15));

      if (resp.statusCode != 200) {
        debugPrint('[IAP] backend verify HTTP ${resp.statusCode}: ${resp.body}');
        try {
          final j = jsonDecode(resp.body) as Map<String, dynamic>;
          return _BackendVerifyResult.fail(
            j['detail']?.toString() ?? 'HTTP ${resp.statusCode}',
          );
        } catch (_) {
          return _BackendVerifyResult.fail('HTTP ${resp.statusCode}');
        }
      }

      final j = jsonDecode(resp.body) as Map<String, dynamic>;
      final activated = j['premium_activated'] == true ||
          j['status'] == 'already_processed';
      return _BackendVerifyResult(
        success: activated,
        plan: j['plan']?.toString(),
      );
    } catch (e) {
      debugPrint('[IAP] backend verify exception: $e');
      return _BackendVerifyResult.fail(e.toString());
    }
  }
}

/// Resultat d'un achat IAP retourne au caller (UI).
class IapResult {
  final IapResultStatus status;
  final String? productId;
  final String? plan;
  final String? errorMessage;

  const IapResult._({
    required this.status,
    this.productId,
    this.plan,
    this.errorMessage,
  });

  factory IapResult.success({required String productId, String? plan}) =>
      IapResult._(
        status: IapResultStatus.success,
        productId: productId,
        plan: plan,
      );

  factory IapResult.canceled() =>
      const IapResult._(status: IapResultStatus.canceled);

  factory IapResult.failed(String message) => IapResult._(
        status: IapResultStatus.failed,
        errorMessage: message,
      );

  bool get isSuccess => status == IapResultStatus.success;
  bool get isCanceled => status == IapResultStatus.canceled;
  bool get isFailed => status == IapResultStatus.failed;
}

enum IapResultStatus { success, canceled, failed }

class IapException implements Exception {
  final String message;
  IapException(this.message);
  @override
  String toString() => 'IapException: $message';
}

class _BackendVerifyResult {
  final bool success;
  final String? plan;
  final String? errorMessage;

  const _BackendVerifyResult({
    required this.success,
    this.plan,
    this.errorMessage,
  });

  factory _BackendVerifyResult.fail(String msg) =>
      _BackendVerifyResult(success: false, errorMessage: msg);
}
