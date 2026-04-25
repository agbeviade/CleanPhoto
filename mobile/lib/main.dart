import 'package:flutter/material.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'config.dart';
import 'theme.dart';
import 'screens/splash_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await initializeDateFormatting('fr_FR', null);
  if (AppConfig.hasSupabase) {
    try {
      await Supabase.initialize(
        url: AppConfig.supabaseUrl,
        anonKey: AppConfig.supabaseAnonKey,
        debug: false,
      );
    } catch (e) {
      debugPrint('Supabase init failed: $e');
    }
  }
  runApp(const SouvenirApp());
}

class SouvenirApp extends StatelessWidget {
  const SouvenirApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Souvenir AI',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(),
      home: const SplashScreen(),
    );
  }
}
