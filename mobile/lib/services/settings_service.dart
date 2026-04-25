import 'package:shared_preferences/shared_preferences.dart';

/// Reglages de restauration IA persistes localement.
/// fidelity: 0.0 (plus creatif, lisse) -> 1.0 (plus fidele a l'original)
/// upscale: 1, 2, 4 (premium pour 4x)
class RestoreSettings {
  final double fidelity;
  final int upscale;

  const RestoreSettings({
    this.fidelity = 0.7,
    this.upscale = 2,
  });

  RestoreSettings copyWith({double? fidelity, int? upscale}) =>
      RestoreSettings(
        fidelity: fidelity ?? this.fidelity,
        upscale: upscale ?? this.upscale,
      );

  String get fidelityLabel {
    if (fidelity <= 0.4) return 'Maximum (visages restaures)';
    if (fidelity <= 0.65) return 'Equilibre';
    if (fidelity <= 0.85) return 'Naturel (recommande)';
    return 'Tres fidele (peu de retouche)';
  }
}

class SettingsService {
  static const _kFidelity = 'restore_fidelity_v1';
  static const _kUpscale = 'restore_upscale_v1';

  static Future<RestoreSettings> load() async {
    final p = await SharedPreferences.getInstance();
    return RestoreSettings(
      fidelity: p.getDouble(_kFidelity) ?? 0.7,
      upscale: p.getInt(_kUpscale) ?? 2,
    );
  }

  static Future<void> save(RestoreSettings s) async {
    final p = await SharedPreferences.getInstance();
    await p.setDouble(_kFidelity, s.fidelity);
    await p.setInt(_kUpscale, s.upscale);
  }
}
