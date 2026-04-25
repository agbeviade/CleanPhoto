import 'package:flutter/material.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'theme.dart';
import 'screens/splash_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await initializeDateFormatting('fr_FR', null);
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
