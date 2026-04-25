import 'package:flutter/material.dart';
import '../theme.dart';
import '../services/premium_service.dart';

class PremiumScreen extends StatelessWidget {
  const PremiumScreen({super.key});

  static const _features = [
    ('Restaurations illimitees', Icons.all_inclusive),
    ('Sans filigrane', Icons.water_drop_outlined),
    ('Qualite maximale', Icons.high_quality),
    ('Traitement prioritaire', Icons.flash_on),
    ('Support dedie', Icons.support_agent),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Souvenir AI Premium',
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
                      'Liberez tout le potentiel\nde Souvenir AI',
                      style: TextStyle(
                        color: Colors.white,
                        fontSize: 22,
                        fontWeight: FontWeight.w800,
                        height: 1.2,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      'Restaurez tous les souvenirs precieux de votre famille, sans limite.',
                      style: TextStyle(
                        color: Colors.white.withOpacity(0.9),
                        fontSize: 14,
                        height: 1.4,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 24),
              ..._features.map((f) => Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: Row(
                      children: [
                        Container(
                          width: 36,
                          height: 36,
                          decoration: BoxDecoration(
                            color: AppColors.softBlue.withOpacity(0.5),
                            borderRadius: BorderRadius.circular(10),
                          ),
                          child: Icon(f.$2,
                              color: AppColors.primaryBlue, size: 20),
                        ),
                        const SizedBox(width: 14),
                        Expanded(
                          child: Text(f.$1,
                              style: const TextStyle(
                                  fontSize: 15,
                                  fontWeight: FontWeight.w600,
                                  color: AppColors.textDark)),
                        ),
                        const Icon(Icons.check_circle,
                            color: Color(0xFF2E7D32), size: 20),
                      ],
                    ),
                  )),
              const SizedBox(height: 24),
              _planCard(
                title: 'Mensuel',
                price: '4,99 €',
                period: '/ mois',
                highlighted: false,
              ),
              const SizedBox(height: 12),
              _planCard(
                title: 'Annuel',
                price: '39,99 €',
                period: '/ an',
                highlighted: true,
                badge: 'Economisez 33%',
              ),
              const SizedBox(height: 24),
              ElevatedButton(
                onPressed: () => _activate(context),
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.accentRed,
                  padding: const EdgeInsets.symmetric(vertical: 18),
                ),
                child: const Text('Souscrire',
                    style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
              ),
              const SizedBox(height: 8),
              Center(
                child: Text(
                  'Facturation Google Play / App Store - resiliable a tout moment',
                  style: TextStyle(
                      color: AppColors.textMuted.withOpacity(0.8), fontSize: 11),
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
    required String title,
    required String price,
    required String period,
    bool highlighted = false,
    String? badge,
  }) {
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
                    Text(title,
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
                    Text(price,
                        style: const TextStyle(
                            fontSize: 22,
                            fontWeight: FontWeight.w800,
                            color: AppColors.textDark)),
                    Text(period,
                        style: const TextStyle(
                            fontSize: 13, color: AppColors.textMuted)),
                  ],
                ),
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

  Future<void> _activate(BuildContext context) async {
    // Hook IAP : a remplacer par RevenueCat / Google Play Billing.
    // Pour MVP, on simule l'activation locale.
    await PremiumService.setPremium(true);
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('Premium active (simulation)'),
        behavior: SnackBarBehavior.floating,
      ),
    );
    Navigator.pop(context, true);
  }
}
