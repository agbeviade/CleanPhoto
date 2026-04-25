import 'package:flutter/material.dart';
import '../theme.dart';
import '../services/settings_service.dart';
import '../services/premium_service.dart';
import 'premium_screen.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  RestoreSettings _settings = const RestoreSettings();
  bool _isPremium = false;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final s = await SettingsService.load();
    final p = await PremiumService.isPremium();
    if (!mounted) return;
    setState(() {
      _settings = s;
      _isPremium = p;
      _loading = false;
    });
  }

  Future<void> _save() async {
    await SettingsService.save(_settings);
  }

  Future<void> _openPremium() async {
    final activated = await Navigator.push<bool>(
      context,
      MaterialPageRoute(builder: (_) => const PremiumScreen()),
    );
    if (activated == true && mounted) {
      setState(() => _isPremium = true);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Reglages IA',
            style: TextStyle(fontWeight: FontWeight.w700)),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(20),
              children: [
                _section(
                  icon: Icons.tune,
                  title: 'Fidelite',
                  subtitle:
                      'Equilibre entre amelioration creative et respect de la photo originale.',
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text(
                            _settings.fidelityLabel,
                            style: const TextStyle(
                              fontWeight: FontWeight.w700,
                              color: AppColors.primaryBlue,
                            ),
                          ),
                          Text(
                            '${(_settings.fidelity * 100).toInt()}%',
                            style: const TextStyle(
                              fontWeight: FontWeight.w700,
                              color: AppColors.textMuted,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Slider(
                        value: _settings.fidelity,
                        min: 0.2,
                        max: 1.0,
                        divisions: 16,
                        activeColor: AppColors.primaryBlue,
                        label: '${(_settings.fidelity * 100).toInt()}%',
                        onChanged: (v) =>
                            setState(() => _settings = _settings.copyWith(fidelity: v)),
                        onChangeEnd: (_) => _save(),
                      ),
                      const Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text('Plus retouche',
                              style: TextStyle(
                                  fontSize: 11, color: AppColors.textMuted)),
                          Text('Plus fidele',
                              style: TextStyle(
                                  fontSize: 11, color: AppColors.textMuted)),
                        ],
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 16),
                _section(
                  icon: Icons.zoom_in,
                  title: 'Resolution de sortie',
                  subtitle:
                      '4x necessite Premium et augmente legerement le temps de traitement.',
                  child: Column(
                    children: [
                      _upscaleOption(1, 'Original', 'Pas d\'agrandissement'),
                      _upscaleOption(2, '2x', 'Recommande pour anciennes photos'),
                      _upscaleOption(4, '4x', 'Maximum (Premium)', premium: true),
                    ],
                  ),
                ),
                const SizedBox(height: 24),
                Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: AppColors.softBlue.withOpacity(0.4),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: const Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Icon(Icons.lightbulb_outline,
                          color: AppColors.primaryBlue, size: 20),
                      SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          'Astuce : pour des portraits anciens tres abimes, baisse la fidelite (~40%) pour laisser l\'IA reconstruire les visages.',
                          style: TextStyle(
                              fontSize: 12,
                              color: AppColors.textDark,
                              height: 1.4),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
    );
  }

  Widget _section({
    required IconData icon,
    required String title,
    required String subtitle,
    required Widget child,
  }) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.lightGrey),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 36,
                height: 36,
                decoration: BoxDecoration(
                  color: AppColors.softBlue.withOpacity(0.5),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Icon(icon, color: AppColors.primaryBlue, size: 20),
              ),
              const SizedBox(width: 12),
              Text(title,
                  style: const TextStyle(
                      fontSize: 16, fontWeight: FontWeight.w700)),
            ],
          ),
          const SizedBox(height: 8),
          Text(subtitle,
              style:
                  const TextStyle(fontSize: 12, color: AppColors.textMuted, height: 1.4)),
          const SizedBox(height: 16),
          child,
        ],
      ),
    );
  }

  Widget _upscaleOption(int value, String label, String description,
      {bool premium = false}) {
    final selected = _settings.upscale == value;
    final disabled = premium && !_isPremium;
    return InkWell(
      onTap: disabled
          ? _openPremium
          : () {
              setState(() => _settings = _settings.copyWith(upscale: value));
              _save();
            },
      borderRadius: BorderRadius.circular(10),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
        margin: const EdgeInsets.only(bottom: 6),
        decoration: BoxDecoration(
          color: selected ? AppColors.softBlue.withOpacity(0.5) : Colors.transparent,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(
            color: selected ? AppColors.primaryBlue : AppColors.lightGrey,
            width: selected ? 1.5 : 1,
          ),
        ),
        child: Row(
          children: [
            Icon(
              selected ? Icons.radio_button_checked : Icons.radio_button_unchecked,
              color: selected ? AppColors.primaryBlue : AppColors.textMuted,
              size: 20,
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text(label,
                          style: const TextStyle(
                              fontWeight: FontWeight.w700, fontSize: 14)),
                      if (premium) ...[
                        const SizedBox(width: 8),
                        Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 6, vertical: 2),
                          decoration: BoxDecoration(
                            color: AppColors.accentRed,
                            borderRadius: BorderRadius.circular(4),
                          ),
                          child: const Text('Premium',
                              style: TextStyle(
                                  color: Colors.white,
                                  fontSize: 9,
                                  fontWeight: FontWeight.w700)),
                        ),
                      ],
                    ],
                  ),
                  Text(description,
                      style: const TextStyle(
                          fontSize: 11, color: AppColors.textMuted)),
                ],
              ),
            ),
            if (disabled)
              const Icon(Icons.lock_outline,
                  color: AppColors.textMuted, size: 16),
          ],
        ),
      ),
    );
  }
}
