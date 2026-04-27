import 'dart:io' show Platform;
import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:timezone/data/latest_all.dart' as tz_data;
import 'package:timezone/timezone.dart' as tz;

/// Service de notifications LOCALES (pas FCM/push remote).
///
/// Fonctionnalites :
///   - Notif immediate quand quota=0 (free) ou pack epuise (premium)
///   - Notif schedulee 24h avant expiration d'un pack
///   - Notif de reengagement apres 7 jours d'inactivite
///   - Toggle global ON/OFF persiste en SharedPreferences
///
/// Toutes les operations sont no-op silencieuses si :
///   - L'utilisateur a desactive les notifs dans Settings
///   - L'OS a refuse les permissions
///   - On est sur web (kIsWeb)
class NotificationService {
  NotificationService._();
  static final NotificationService instance = NotificationService._();

  static const String _prefsEnabledKey = 'notif_enabled_v1';
  static const String _channelId = 'souvenir_main';
  static const String _channelName = 'Souvenir AI';
  static const String _channelDesc =
      'Rappels de quota, expirations de packs et reengagement';

  // IDs reserves pour les differents types de notifs.
  // Permet d'annuler / replacer une notif specifique sans toucher aux autres.
  static const int idQuotaLow = 1001;
  static const int idPackExpiring = 1002;
  static const int idReengagement = 1003;

  final FlutterLocalNotificationsPlugin _plugin =
      FlutterLocalNotificationsPlugin();
  bool _initialized = false;

  /// Indique si la plateforme supporte les notifications locales.
  bool get _isSupported => !kIsWeb && (Platform.isAndroid || Platform.isIOS);

  /// Lit la preference utilisateur (toggle Settings).
  static Future<bool> isEnabled() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool(_prefsEnabledKey) ?? true; // ON par defaut
  }

  /// Met a jour la preference. Si OFF, annule toutes les notifs en attente.
  Future<void> setEnabled(bool enabled) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_prefsEnabledKey, enabled);
    if (!enabled) {
      await cancelAll();
    }
  }

  /// Initialise le plugin + timezone. A appeler une fois au demarrage.
  Future<void> init() async {
    if (_initialized || !_isSupported) return;
    _initialized = true;

    // Timezone DB (necessaire pour zonedSchedule)
    tz_data.initializeTimeZones();
    try {
      // Detection naive : on prend le local time, sinon UTC
      tz.setLocalLocation(tz.getLocation(tz.local.name));
    } catch (_) {
      tz.setLocalLocation(tz.UTC);
    }

    const androidInit =
        AndroidInitializationSettings('@mipmap/ic_launcher');
    const iosInit = DarwinInitializationSettings(
      requestAlertPermission: false,
      requestBadgePermission: false,
      requestSoundPermission: false,
    );
    const initSettings =
        InitializationSettings(android: androidInit, iOS: iosInit);

    await _plugin.initialize(initSettings);

    // Cree le channel Android (no-op sur iOS)
    if (Platform.isAndroid) {
      const channel = AndroidNotificationChannel(
        _channelId,
        _channelName,
        description: _channelDesc,
        importance: Importance.high,
      );
      await _plugin
          .resolvePlatformSpecificImplementation<
              AndroidFlutterLocalNotificationsPlugin>()
          ?.createNotificationChannel(channel);
    }
  }

  /// Demande les permissions a l'utilisateur (Android 13+ et iOS).
  /// Retourne true si accordees.
  Future<bool> requestPermissions() async {
    if (!_isSupported) return false;
    if (!_initialized) await init();

    if (Platform.isAndroid) {
      final granted = await _plugin
          .resolvePlatformSpecificImplementation<
              AndroidFlutterLocalNotificationsPlugin>()
          ?.requestNotificationsPermission();
      return granted ?? false;
    }
    if (Platform.isIOS) {
      final granted = await _plugin
          .resolvePlatformSpecificImplementation<
              IOSFlutterLocalNotificationsPlugin>()
          ?.requestPermissions(alert: true, badge: true, sound: true);
      return granted ?? false;
    }
    return false;
  }

  // ---------------------------------------------------------------------
  // Notifications IMMEDIATES (envoi tout de suite)
  // ---------------------------------------------------------------------

  /// Quota epuise (free user a 0 photos restantes apres restoration).
  Future<void> showQuotaExhausted({required bool isPremium}) async {
    if (!await _shouldNotify()) return;
    final title = isPremium ? 'Pack epuise' : 'Quota gratuit atteint';
    final body = isPremium
        ? 'Votre pack est epuise. Achetez un nouveau pack pour continuer.'
        : 'Vous avez utilise vos 3 photos gratuites. Revenez demain ou passez Premium.';
    await _show(idQuotaLow, title, body);
  }

  /// Pack bas (1 ou 2 photos restantes) - plus subtil.
  Future<void> showPackLow(int remaining) async {
    if (!await _shouldNotify()) return;
    if (remaining <= 0 || remaining > 2) return;
    await _show(
      idQuotaLow,
      'Plus que $remaining photo${remaining > 1 ? "s" : ""} dans votre pack',
      'Utilisez vos dernieres photos avant expiration ou achetez un nouveau pack.',
    );
  }

  /// Pour bouton "Tester les notifications" dans Settings.
  Future<void> showTest() async {
    if (!await _shouldNotify()) return;
    await _show(
      9999,
      'Test Souvenir AI',
      'Les notifications fonctionnent ! Vous recevrez des rappels utiles.',
    );
  }

  // ---------------------------------------------------------------------
  // Notifications SCHEDULEES (declenchent plus tard)
  // ---------------------------------------------------------------------

  /// Schedule un rappel 24h avant expiration d'un pack.
  /// Si une autre notif "expire" est deja schedulee, elle est remplacee.
  Future<void> schedulePackExpiringReminder({
    required DateTime expiresAt,
    required int packSize,
  }) async {
    if (!await _shouldNotify()) return;
    final reminderAt = expiresAt.subtract(const Duration(hours: 24));
    // Si la date est deja passee, on n'envoie rien
    if (reminderAt.isBefore(DateTime.now().add(const Duration(minutes: 5)))) {
      return;
    }
    await _zonedSchedule(
      idPackExpiring,
      'Votre pack expire demain',
      'Utilisez vos photos restantes avant expiration de votre pack de $packSize photos.',
      tz.TZDateTime.from(reminderAt, tz.local),
    );
  }

  /// Schedule un rappel de reengagement dans 7 jours.
  /// Annule + remplace celle existante (= reset le compteur d'inactivite).
  Future<void> scheduleReengagement({Duration delay = const Duration(days: 7)}) async {
    if (!await _shouldNotify()) return;
    final at = DateTime.now().add(delay);
    await _zonedSchedule(
      idReengagement,
      'Une photo qui vous tient a coeur ?',
      'Restaurez une vieille photo en quelques secondes avec Souvenir AI.',
      tz.TZDateTime.from(at, tz.local),
    );
  }

  // ---------------------------------------------------------------------
  // Cancel helpers
  // ---------------------------------------------------------------------

  Future<void> cancelPackExpiring() => _plugin.cancel(idPackExpiring);
  Future<void> cancelReengagement() => _plugin.cancel(idReengagement);
  Future<void> cancelAll() => _plugin.cancelAll();

  // ---------------------------------------------------------------------
  // Internals
  // ---------------------------------------------------------------------

  /// Verifie : (1) plateforme supportee, (2) init OK, (3) toggle ON.
  Future<bool> _shouldNotify() async {
    if (!_isSupported) return false;
    if (!_initialized) await init();
    return await isEnabled();
  }

  NotificationDetails _details() {
    const android = AndroidNotificationDetails(
      _channelId,
      _channelName,
      channelDescription: _channelDesc,
      importance: Importance.high,
      priority: Priority.high,
      icon: '@mipmap/ic_launcher',
    );
    const ios = DarwinNotificationDetails(
      presentAlert: true,
      presentBadge: true,
      presentSound: true,
    );
    return const NotificationDetails(android: android, iOS: ios);
  }

  Future<void> _show(int id, String title, String body) async {
    try {
      await _plugin.show(id, title, body, _details());
    } catch (e) {
      debugPrint('[Notif] show failed: $e');
    }
  }

  Future<void> _zonedSchedule(
    int id,
    String title,
    String body,
    tz.TZDateTime when,
  ) async {
    try {
      await _plugin.zonedSchedule(
        id,
        title,
        body,
        when,
        _details(),
        androidScheduleMode: AndroidScheduleMode.inexactAllowWhileIdle,
        uiLocalNotificationDateInterpretation:
            UILocalNotificationDateInterpretation.absoluteTime,
      );
    } catch (e) {
      debugPrint('[Notif] zonedSchedule failed: $e');
    }
  }
}
