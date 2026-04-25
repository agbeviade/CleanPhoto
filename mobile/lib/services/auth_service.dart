import 'package:supabase_flutter/supabase_flutter.dart';
import '../config.dart';

/// Wrapper auth Supabase. Si Supabase n'est pas configure (URL/key vides),
/// l'auth est en mode "no-op" et l'app fonctionne en mode anonyme.
class AuthService {
  static bool get isConfigured => AppConfig.hasSupabase;

  static SupabaseClient? get _client =>
      isConfigured ? Supabase.instance.client : null;

  static User? get currentUser => _client?.auth.currentUser;
  static Session? get currentSession => _client?.auth.currentSession;
  static String? get accessToken => currentSession?.accessToken;
  static bool get isLoggedIn => currentUser != null;

  static Stream<AuthState>? get onAuthChange => _client?.auth.onAuthStateChange;

  static Future<AuthResponse> signUp(String email, String password) async {
    if (!isConfigured) throw Exception('Auth non configuree');
    return _client!.auth.signUp(email: email, password: password);
  }

  static Future<AuthResponse> signIn(String email, String password) async {
    if (!isConfigured) throw Exception('Auth non configuree');
    return _client!.auth.signInWithPassword(email: email, password: password);
  }

  static Future<void> signOut() async {
    if (!isConfigured) return;
    await _client!.auth.signOut();
  }

  static Future<void> resetPassword(String email) async {
    if (!isConfigured) throw Exception('Auth non configuree');
    await _client!.auth.resetPasswordForEmail(email);
  }
}
