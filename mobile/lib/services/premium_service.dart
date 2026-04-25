import 'package:shared_preferences/shared_preferences.dart';

/// Etat premium local. Hook pour brancher RevenueCat / Stripe / IAP plus tard.
class PremiumService {
  static const _key = 'is_premium_v1';

  static Future<bool> isPremium() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool(_key) ?? false;
  }

  static Future<void> setPremium(bool value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_key, value);
  }
}
