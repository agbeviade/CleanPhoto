import 'package:shared_preferences/shared_preferences.dart';

/// Genere et persiste un identifiant anonyme du device (UUID v4 simplifie).
/// Utilise pour le quota cote serveur sans necessiter d'authentification.
class DeviceService {
  static const _key = 'device_id_v1';
  static String? _cached;

  static Future<String> getId() async {
    if (_cached != null) return _cached!;
    final prefs = await SharedPreferences.getInstance();
    var id = prefs.getString(_key);
    if (id == null || id.isEmpty) {
      id = _generateUuid();
      await prefs.setString(_key, id);
    }
    _cached = id;
    return id;
  }

  static String _generateUuid() {
    // RFC 4122 v4 (random) sans dependance externe
    final now = DateTime.now().microsecondsSinceEpoch;
    final rng = (DateTime.now().millisecondsSinceEpoch * 9301 + 49297) % 233280;
    final hex =
        (now.toRadixString(16) + rng.toRadixString(16)).padRight(32, 'f').substring(0, 32);
    return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-4${hex.substring(13, 16)}-'
        'a${hex.substring(17, 20)}-${hex.substring(20, 32)}';
  }
}
