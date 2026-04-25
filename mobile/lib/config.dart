/// Configuration globale.
///
/// En production: Vercel URL via --dart-define=API_BASE_URL=https://xxx.vercel.app
/// En dev local emulateur Android: 10.0.2.2:8000
class AppConfig {
  static const String apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://10.0.2.2:8000',
  );

  /// Cle anon Supabase (PUBLIQUE, OK cote client).
  /// Permet la lecture du storage public et l'auth utilisateur.
  static const String supabaseUrl = String.fromEnvironment(
    'SUPABASE_URL',
    defaultValue: '',
  );
  static const String supabaseAnonKey = String.fromEnvironment(
    'SUPABASE_ANON_KEY',
    defaultValue: '',
  );

  static const int maxImageSizeMB = 10;
  static const int dailyFreeLimit = 3; // base monetisation future

  static bool get hasSupabase => supabaseUrl.isNotEmpty && supabaseAnonKey.isNotEmpty;
}
