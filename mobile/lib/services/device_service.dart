import 'dart:convert';
import 'dart:io' show Platform;
import 'package:crypto/crypto.dart';
import 'package:device_info_plus/device_info_plus.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Genere et persiste un identifiant anonyme du device.
///
/// Strategie de persistance (du plus persistant au moins persistant) :
///   1. **Keychain iOS / Keystore Android** (flutter_secure_storage)
///      - iOS : SURVIT aux desinstallations (Keychain)
///      - Android : ne survit pas (Keystore lie a l'app), mais chiffre
///   2. **SharedPreferences** (compatibilite avec utilisateurs existants)
///   3. **Hardware ID** (ANDROID_ID / identifierForVendor)
///      - Android : ANDROID_ID survit aux desinstallations (reset au factory reset)
///      - iOS : IDFV survit tant qu'une autre app du meme vendor reste installee
///   4. **UUID v4** (dernier recours)
///
/// L'ID est ecrit dans TOUS les emplacements pour maximiser la persistance.
class DeviceService {
  static const _keyV2 = 'device_id_v2';
  static const _keyV1 = 'device_id_v1'; // ancien stockage (migration)
  static const _hashSalt = 'souvenir-ai-2026';

  static String? _cached;

  // iOS : accessible apres premier deverrouillage, persiste sans backup iCloud
  static const _secureStorage = FlutterSecureStorage(
    iOptions: IOSOptions(
      accessibility: KeychainAccessibility.first_unlock,
      synchronizable: false,
    ),
    aOptions: AndroidOptions(
      encryptedSharedPreferences: true,
    ),
  );

  /// Retourne l'identifiant device (cache memoire apres 1er appel).
  static Future<String> getId() async {
    if (_cached != null) return _cached!;

    // 1. Tenter le secure storage (Keychain iOS qui survit aux uninstalls)
    String? id = await _readSecure();

    // 2. Fallback : SharedPreferences (utilisateurs existants v1/v2)
    final prefs = await SharedPreferences.getInstance();
    if (id == null || id.isEmpty) {
      id = prefs.getString(_keyV2) ?? prefs.getString(_keyV1);
    }

    // 3. Fallback : derive depuis hardware ID (survit aux uninstalls Android)
    if (id == null || id.isEmpty) {
      id = await _deriveFromHardware();
    }

    // 4. Dernier recours : UUID v4 random
    id = (id != null && id.isNotEmpty) ? id : _generateUuid();

    // Persiste dans TOUS les emplacements (best-effort)
    await _writeSecure(id);
    await prefs.setString(_keyV2, id);

    _cached = id;
    return id;
  }

  // ---------------- Helpers ----------------

  static Future<String?> _readSecure() async {
    try {
      return await _secureStorage.read(key: _keyV2);
    } catch (_) {
      return null; // sur certains emulateurs/devices secure storage peut fail
    }
  }

  static Future<void> _writeSecure(String id) async {
    try {
      await _secureStorage.write(key: _keyV2, value: id);
    } catch (_) {
      // ignore - on a toujours SharedPreferences
    }
  }

  /// Derive un ID stable depuis un identifiant hardware.
  /// Hashe avec un salt pour ne JAMAIS exposer l'ID hardware brut.
  static Future<String?> _deriveFromHardware() async {
    try {
      final info = DeviceInfoPlugin();
      String? raw;
      if (Platform.isAndroid) {
        final a = await info.androidInfo;
        raw = a.id; // SSAID / ANDROID_ID, survit aux uninstalls
      } else if (Platform.isIOS) {
        final i = await info.iosInfo;
        raw = i.identifierForVendor; // survit si autre app du vendor presente
      }
      if (raw == null || raw.isEmpty) return null;
      // SHA-256 + salt -> 32 bytes hex, formate en UUID-like
      final digest = sha256.convert(utf8.encode('$raw$_hashSalt')).toString();
      // Format UUID v4-like (sans etre vraiment v4, juste un format reconnu)
      return '${digest.substring(0, 8)}-${digest.substring(8, 12)}-'
          '4${digest.substring(13, 16)}-'
          'a${digest.substring(17, 20)}-${digest.substring(20, 32)}';
    } catch (_) {
      return null;
    }
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
