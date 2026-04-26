import 'package:flutter/material.dart';
import '../theme.dart';
import '../services/payment_service.dart';
import '../services/premium_service.dart';

class PremiumScreen extends StatefulWidget {
  const PremiumScreen({super.key});

  @override
  State<PremiumScreen> createState() => _PremiumScreenState();
}

class _PremiumScreenState extends State<PremiumScreen> {
  bool _processing = false;
  bool _loadingPlans = true;
  List<PackPlan> _plans = [];
  String? _selectedPlanId;
  String? _loadError;

  static const _features = [
    ('Sans filigrane sur vos photos', Icons.water_drop_outlined),
    ('Qualite premium maximale', Icons.high_quality),
    ('Traitement par lot (jusqu\'a 10 photos)', Icons.burst_mode_outlined),
    ('Traitement prioritaire', Icons.flash_on),
    ('Support dedie', Icons.support_agent),
  ];

  @override
  void initState() {
    super.initState();
    _loadPlans();
  }

  Future<void> _loadPlans() async {
    setState(() {
      _loadingPlans = true;
      _loadError = null;
    });
    final list = await PaymentService.fetchPlans();
    if (!mounted) return;
    if (list == null || list.isEmpty) {
      setState(() {
        _loadingPlans = false;
        _loadError = 'Impossible de charger les forfaits. Verifiez votre connexion.';
      });
      return;
    }
    setState(() {
      _plans = list;
      // Plan recommande par defaut : 50 photos (rapport qualite-prix)
      final defaultPick = list.firstWhere(
        (p) => p.id == 'pack_50_week',
        orElse: () => list.first,
      );
      _selectedPlanId = defaultPick.id;
      _loadingPlans = false;
    });
  }

  PackPlan? get _selectedPlan {
    if (_selectedPlanId == null) return null;
    return _plans.firstWhere(
      (p) => p.id == _selectedPlanId,
      orElse: () => _plans.first,
    );
  }

  String _formatPrice(int xof) {
    // Formate "2999" -> "2 999 F CFA"
    final s = xof.toString();
    final buf = StringBuffer();
    for (int i = 0; i < s.length; i++) {
      if (i > 0 && (s.length - i) % 3 == 0) buf.write(' ');
      buf.write(s[i]);
    }
    return '${buf.toString()} F CFA';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Choisissez votre pack',
            style: TextStyle(fontWeight: FontWeight.w700)),
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Container(
                padding: const EdgeInsets.all(24),
                decoration: BoxDecoration(
                  gradient: const LinearGradient(
                    colors: [AppColors.primaryBlue, AppColors.accentRed],
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                  ),
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(Icons.workspace_premium,
                        color: Colors.white, size: 36),
                    const SizedBox(height: 12),
                    const Text(
                      'Restaurez tous vos\nprecieux souvenirs',
                      style: TextStyle(
                        color: Colors.white,
                        fontSize: 22,
                        fontWeight: FontWeight.w800,
                        height: 1.2,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      'Choisissez le pack qui vous convient. Paiement unique, valable 7 jours.',
                      style: TextStyle(
                        color: Colors.white.withOpacity(0.9),
                        fontSize: 14,
                        height: 1.4,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 20),
              ..._features.map((f) => Padding(
                    padding: const EdgeInsets.symmetric(vertical: 6),
                    child: Row(
                      children: [
                        Container(
                          width: 32,
                          height: 32,
                          decoration: BoxDecoration(
                            color: AppColors.softBlue.withOpacity(0.5),
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Icon(f.$2,
                              color: AppColors.primaryBlue, size: 18),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Text(f.$1,
                              style: const TextStyle(
                                  fontSize: 14,
                                  fontWeight: FontWeight.w600,
                                  color: AppColors.textDark)),
                        ),
                        const Icon(Icons.check_circle,
                            color: Color(0xFF2E7D32), size: 18),
                      ],
                    ),
                  )),
              const SizedBox(height: 20),
              if (_loadingPlans)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 40),
                  child: Center(child: CircularProgressIndicator()),
                )
              else if (_loadError != null)
                Column(
                  children: [
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      child: Text(_loadError!,
                          style: const TextStyle(color: AppColors.accentRed),
                          textAlign: TextAlign.center),
                    ),
                    OutlinedButton.icon(
                      onPressed: _loadPlans,
                      icon: const Icon(Icons.refresh),
                      label: const Text('Reessayer'),
                    ),
                  ],
                )
              else
                ..._plans.asMap().entries.map((e) {
                  final idx = e.key;
                  final p = e.value;
                  final isMid = _plans.length >= 3 && idx == 1;
                  return Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: GestureDetector(
                      onTap: _processing
                          ? null
                          : () => setState(() => _selectedPlanId = p.id),
                      child: _planCard(
                        plan: p,
                        highlighted: _selectedPlanId == p.id,
                        badge: isMid ? 'Recommande' : null,
                      ),
                    ),
                  );
                }),
              if (!_loadingPlans && _loadError == null && _selectedPlan != null) ...[
                const SizedBox(height: 12),
                ElevatedButton(
                  onPressed: _processing ? null : () => _startPayment(context),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.accentRed,
                    padding: const EdgeInsets.symmetric(vertical: 18),
                  ),
                  child: _processing
                      ? const SizedBox(
                          height: 20,
                          width: 20,
                          child: CircularProgressIndicator(
                            strokeWidth: 2.5,
                            color: Colors.white,
                          ),
                        )
                      : Text(
                          'Payer ${_formatPrice(_selectedPlan!.price)}',
                          style: const TextStyle(
                              fontSize: 16, fontWeight: FontWeight.w700),
                        ),
                ),
              ],
              const SizedBox(height: 8),
              Center(
                child: Text(
                  'Paiement securise via GeniusPay\nWave - Orange Money - MTN - Cartes bancaires',
                  style: TextStyle(
                      color: AppColors.textMuted.withOpacity(0.8),
                      fontSize: 11,
                      height: 1.5),
                  textAlign: TextAlign.center,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _planCard({
    required PackPlan plan,
    bool highlighted = false,
    String? badge,
  }) {
    final pricePerImage = plan.price / plan.images;
    final pricePerImageStr = pricePerImage.toStringAsFixed(0);
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: highlighted ? AppColors.softBlue.withOpacity(0.4) : Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: highlighted ? AppColors.primaryBlue : AppColors.lightGrey,
          width: highlighted ? 2 : 1,
        ),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text('${plan.images} photos',
                        style: const TextStyle(
                            fontSize: 16, fontWeight: FontWeight.w700)),
                    if (badge != null) ...[
                      const SizedBox(width: 8),
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          color: AppColors.accentRed,
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text(badge,
                            style: const TextStyle(
                                color: Colors.white,
                                fontSize: 10,
                                fontWeight: FontWeight.w700)),
                      ),
                    ],
                  ],
                ),
                const SizedBox(height: 4),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(_formatPrice(plan.price),
                        style: const TextStyle(
                            fontSize: 22,
                            fontWeight: FontWeight.w800,
                            color: AppColors.textDark)),
                    Text('  / ${plan.days}j',
                        style: const TextStyle(
                            fontSize: 13, color: AppColors.textMuted)),
                  ],
                ),
                const SizedBox(height: 2),
                Text('Soit ~ $pricePerImageStr F CFA / photo',
                    style: const TextStyle(
                        fontSize: 11, color: AppColors.textMuted)),
              ],
            ),
          ),
          if (highlighted)
            const Icon(Icons.radio_button_checked,
                color: AppColors.primaryBlue, size: 24)
          else
            const Icon(Icons.radio_button_unchecked,
                color: AppColors.textMuted, size: 24),
        ],
      ),
    );
  }

  Future<void> _startPayment(BuildContext context) async {
    final selected = _selectedPlan;
    if (selected == null) return;
    setState(() => _processing = true);
    try {
      final init = await PaymentService.createPayment(plan: selected.id);
      final ok = await PaymentService.openCheckout(init.checkoutUrl);
      if (!ok) {
        throw Exception('Impossible d\'ouvrir la page de paiement');
      }
      if (!context.mounted) return;

      // Affiche un dialog en attendant la confirmation webhook
      _showWaitingDialog(context, init.reference);

      // Polling backend pour confirmer le paiement
      final completed = await PaymentService.waitForCompletion(init.reference);

      if (!context.mounted) return;
      Navigator.of(context, rootNavigator: true).pop(); // ferme dialog

      if (completed) {
        await PremiumService.setPremium(true);
        if (!context.mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Premium active ! Merci pour votre soutien.'),
            backgroundColor: Color(0xFF2E7D32),
            behavior: SnackBarBehavior.floating,
          ),
        );
        Navigator.pop(context, true);
      } else {
        if (!context.mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
                'Paiement non confirme. Si vous avez paye, le statut sera mis a jour automatiquement.'),
            behavior: SnackBarBehavior.floating,
          ),
        );
      }
    } catch (e) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Erreur paiement: $e'),
          backgroundColor: AppColors.accentRed,
          behavior: SnackBarBehavior.floating,
        ),
      );
    } finally {
      if (mounted) setState(() => _processing = false);
    }
  }

  void _showWaitingDialog(BuildContext context, String reference) {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (_) => AlertDialog(
        title: const Text('En attente du paiement'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const CircularProgressIndicator(),
            const SizedBox(height: 16),
            const Text(
              'Finalisez le paiement dans la fenetre du navigateur. '
              'Cette page se mettra a jour automatiquement.',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 13),
            ),
            const SizedBox(height: 8),
            Text('Ref: $reference',
                style: const TextStyle(
                    fontSize: 11,
                    color: AppColors.textMuted,
                    fontFamily: 'monospace')),
          ],
        ),
      ),
    );
  }
}
