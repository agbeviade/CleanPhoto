import 'package:shared_preferences/shared_preferences.dart';

/// Mode de colorisation pour photos N&B.
/// auto : detection automatique de la saturation (recommande)
/// on   : force la colorisation meme si l'image semble couleur
/// off  : jamais coloriser
enum ColorizeMode { auto, on, off }

extension ColorizeModeX on ColorizeMode {
  String get apiValue => switch (this) {
        ColorizeMode.auto => 'auto',
        ColorizeMode.on => 'on',
        ColorizeMode.off => 'off',
      };
  String get label => switch (this) {
        ColorizeMode.auto => 'Automatique',
        ColorizeMode.on => 'Toujours coloriser',
        ColorizeMode.off => 'Ne jamais coloriser',
      };
  String get description => switch (this) {
        ColorizeMode.auto =>
          'Detecte automatiquement les photos N&B / sepia',
        ColorizeMode.on =>
          'Applique la colorisation meme sur photos couleur (peut alterer les teintes)',
        ColorizeMode.off =>
          'Conserve les couleurs d\'origine sans intervention',
      };
}

/// Reglages de restauration IA persistes localement.
/// fidelity: 0.0 (plus creatif, lisse) -> 1.0 (plus fidele a l'original)
/// upscale: 1, 2, 4 (premium pour 4x)
/// colorize: ColorizeMode.auto par defaut
class RestoreSettings {
  final double fidelity;
  final int upscale;
  final ColorizeMode colorize;

  const RestoreSettings({
    this.fidelity = 0.7,
    this.upscale = 2,
    this.colorize = ColorizeMode.auto,
  });

  RestoreSettings copyWith({
    double? fidelity,
    int? upscale,
    ColorizeMode? colorize,
  }) =>
      RestoreSettings(
        fidelity: fidelity ?? this.fidelity,
        upscale: upscale ?? this.upscale,
        colorize: colorize ?? this.colorize,
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
  static const _kColorize = 'restore_colorize_v1';

  static Future<RestoreSettings> load() async {
    final p = await SharedPreferences.getInstance();
    final colorRaw = p.getString(_kColorize) ?? 'auto';
    return RestoreSettings(
      fidelity: p.getDouble(_kFidelity) ?? 0.7,
      upscale: p.getInt(_kUpscale) ?? 2,
      colorize: ColorizeMode.values.firstWhere(
        (m) => m.apiValue == colorRaw,
        orElse: () => ColorizeMode.auto,
      ),
    );
  }

  static Future<void> save(RestoreSettings s) async {
    final p = await SharedPreferences.getInstance();
    await p.setDouble(_kFidelity, s.fidelity);
    await p.setInt(_kUpscale, s.upscale);
    await p.setString(_kColorize, s.colorize.apiValue);
  }
}
