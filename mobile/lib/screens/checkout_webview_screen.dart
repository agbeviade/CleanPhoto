import 'package:flutter/material.dart';
import 'package:flutter_inappwebview/flutter_inappwebview.dart';

import '../theme.dart';

/// Resultat retourne par CheckoutWebViewScreen.pop().
enum CheckoutResult {
  /// Le user a complete le paiement (URL success interceptee).
  success,

  /// Le user a annule / paiement echoue (URL error interceptee).
  error,

  /// Le user a ferme la WebView avant la fin (peut quand meme avoir paye).
  closed,
}

/// Page de checkout integree (WebView) pour GeniusPay.
///
/// L'utilisateur ne quitte JAMAIS l'app. Quand GeniusPay redirige vers
/// [successUrlPattern] ou [errorUrlPattern], on ferme automatiquement
/// la WebView et on retourne le resultat.
///
/// Utilisation :
/// ```dart
/// final result = await Navigator.push<CheckoutResult>(
///   context,
///   MaterialPageRoute(builder: (_) => CheckoutWebViewScreen(
///     checkoutUrl: init.checkoutUrl,
///     successUrlPattern: '/payment/return/success',
///     errorUrlPattern: '/payment/return/error',
///     reference: init.reference,
///   )),
/// );
/// ```
class CheckoutWebViewScreen extends StatefulWidget {
  final String checkoutUrl;
  final String successUrlPattern;
  final String errorUrlPattern;
  final String reference;

  const CheckoutWebViewScreen({
    super.key,
    required this.checkoutUrl,
    required this.successUrlPattern,
    required this.errorUrlPattern,
    required this.reference,
  });

  @override
  State<CheckoutWebViewScreen> createState() => _CheckoutWebViewScreenState();
}

class _CheckoutWebViewScreenState extends State<CheckoutWebViewScreen> {
  InAppWebViewController? _controller;
  double _progress = 0.0;
  bool _resolved = false;

  /// Intercepte les URLs charges par la WebView.
  /// Si l'URL contient le success/error pattern, on ferme et on retourne.
  NavigationActionPolicy _onNavigation(String url) {
    if (_resolved) return NavigationActionPolicy.CANCEL;
    if (url.contains(widget.successUrlPattern)) {
      _resolved = true;
      Navigator.of(context).pop(CheckoutResult.success);
      return NavigationActionPolicy.CANCEL;
    }
    if (url.contains(widget.errorUrlPattern)) {
      _resolved = true;
      Navigator.of(context).pop(CheckoutResult.error);
      return NavigationActionPolicy.CANCEL;
    }
    return NavigationActionPolicy.ALLOW;
  }

  Future<bool> _confirmExit() async {
    if (_resolved) return true;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Quitter le paiement ?'),
        content: const Text(
          'Si vous quittez, le paiement ne sera pas finalise. '
          'Si vous avez deja paye, votre pack sera active automatiquement '
          'dans quelques secondes.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Continuer le paiement'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: TextButton.styleFrom(foregroundColor: AppColors.accentRed),
            child: const Text('Quitter'),
          ),
        ],
      ),
    );
    return ok ?? false;
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, result) async {
        if (didPop) return;
        final shouldExit = await _confirmExit();
        if (shouldExit && mounted) {
          Navigator.of(context).pop(CheckoutResult.closed);
        }
      },
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Paiement securise',
              style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
          leading: IconButton(
            icon: const Icon(Icons.close),
            onPressed: () async {
              final shouldExit = await _confirmExit();
              if (shouldExit && mounted) {
                Navigator.of(context).pop(CheckoutResult.closed);
              }
            },
          ),
          bottom: PreferredSize(
            preferredSize: const Size.fromHeight(2),
            child: _progress < 1.0
                ? LinearProgressIndicator(
                    value: _progress,
                    minHeight: 2,
                    backgroundColor: Colors.transparent,
                    valueColor: const AlwaysStoppedAnimation<Color>(
                        AppColors.primaryBlue),
                  )
                : const SizedBox(height: 2),
          ),
        ),
        body: SafeArea(
          child: InAppWebView(
            initialUrlRequest: URLRequest(url: WebUri(widget.checkoutUrl)),
            initialSettings: InAppWebViewSettings(
              javaScriptEnabled: true,
              useShouldOverrideUrlLoading: true,
              mediaPlaybackRequiresUserGesture: false,
              transparentBackground: true,
              // Permet aux deeplinks Wave/OM/MTN de s'ouvrir si besoin
              useOnLoadResource: false,
            ),
            onWebViewCreated: (c) => _controller = c,
            shouldOverrideUrlLoading: (controller, action) async {
              final url = action.request.url?.toString() ?? '';
              return _onNavigation(url);
            },
            onLoadStart: (controller, url) {
              if (url != null) _onNavigation(url.toString());
            },
            onProgressChanged: (controller, p) {
              if (mounted) setState(() => _progress = p / 100);
            },
            onReceivedError: (controller, request, error) {
              // Erreur reseau : on n'arrete pas le flow, l'user peut retry
              debugPrint('[Checkout] error: ${error.description}');
            },
          ),
        ),
      ),
    );
  }
}
