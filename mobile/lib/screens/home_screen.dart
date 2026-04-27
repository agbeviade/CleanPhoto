import 'dart:io';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter_spinkit/flutter_spinkit.dart';
import 'package:image_picker/image_picker.dart';
import 'package:path/path.dart' as p;

import '../theme.dart';
import '../config.dart';
import '../services/api_service.dart';
import '../services/history_service.dart';
import '../services/premium_service.dart';
import '../services/auth_service.dart';
import 'result_screen.dart';
import 'history_screen.dart';
import 'premium_screen.dart';
import 'batch_screen.dart';
import 'settings_screen.dart';
import 'auth_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _picker = ImagePicker();
  File? _selectedImage;
  bool _processing = false;
  bool? _backendOnline;
  QuotaInfo? _quota;
  bool _isPremium = false;

  @override
  void initState() {
    super.initState();
    _checkBackend();
    _refreshQuota();
  }

  Future<void> _checkBackend() async {
    final ok = await ApiService.ping();
    if (mounted) setState(() => _backendOnline = ok);
  }

  Future<void> _refreshQuota() async {
    final premium = await PremiumService.isPremium();
    final quota = await ApiService.fetchQuota();
    if (mounted) {
      setState(() {
        _isPremium = premium;
        _quota = quota;
      });
    }
  }

  Future<void> _openPremium() async {
    final activated = await Navigator.push<bool>(
      context,
      MaterialPageRoute(builder: (_) => const PremiumScreen()),
    );
    if (activated == true) {
      _refreshQuota();
    }
  }

  Future<void> _pick(ImageSource source) async {
    try {
      final XFile? picked = await _picker.pickImage(
        source: source,
        maxWidth: 4000,
        imageQuality: 95,
      );
      if (picked == null) return;

      final ext = p.extension(picked.path).toLowerCase();
      if (!['.jpg', '.jpeg', '.png'].contains(ext)) {
        _snack('Format non supporte. Utilisez JPG ou PNG.');
        return;
      }
      final size = await File(picked.path).length();
      if (size > AppConfig.maxImageSizeMB * 1024 * 1024) {
        _snack('Image trop lourde (>${AppConfig.maxImageSizeMB} MB)');
        return;
      }
      setState(() => _selectedImage = File(picked.path));
    } catch (e) {
      _snack('Erreur : $e');
    }
  }

  Future<void> _pickBatch() async {
    if (!_isPremium) {
      // Gate premium : montre l'ecran d'achat
      _showBatchPremiumGate();
      return;
    }
    try {
      final List<XFile> picked = await _picker.pickMultiImage(
        maxWidth: 4000,
        imageQuality: 95,
      );
      if (picked.isEmpty) return;
      // Limite de securite cote client (anti-abus)
      const maxBatch = 10;
      final files = picked.take(maxBatch).toList();
      // Filtre les formats valides
      final valid = <File>[];
      for (final x in files) {
        final ext = p.extension(x.path).toLowerCase();
        if (!['.jpg', '.jpeg', '.png'].contains(ext)) continue;
        final size = await File(x.path).length();
        if (size > AppConfig.maxImageSizeMB * 1024 * 1024) continue;
        valid.add(File(x.path));
      }
      if (valid.isEmpty) {
        _snack('Aucune photo valide selectionnee (JPG/PNG, < ${AppConfig.maxImageSizeMB} MB)');
        return;
      }
      if (picked.length > maxBatch) {
        _snack('Limite a $maxBatch photos par lot. Les premieres sont traitees.');
      }
      if (!mounted) return;
      await Navigator.push(
        context,
        MaterialPageRoute(builder: (_) => BatchScreen(sources: valid)),
      );
      _refreshQuota();
    } catch (e) {
      _snack('Erreur selection : $e');
    }
  }

  void _showBatchPremiumGate() {
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        title: Row(
          children: const [
            Icon(Icons.workspace_premium, color: AppColors.accentRed),
            SizedBox(width: 8),
            Text('Fonction Premium'),
          ],
        ),
        content: const Text(
          'Le traitement par lot vous permet de restaurer jusqu\'a 10 photos d\'un coup. '
          'Reserve aux membres Premium.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Plus tard'),
          ),
          ElevatedButton(
            onPressed: () {
              Navigator.pop(context);
              _openPremium();
            },
            style: ElevatedButton.styleFrom(
                backgroundColor: AppColors.accentRed),
            child: const Text('Devenir Premium'),
          ),
        ],
      ),
    );
  }

  Future<void> _restore() async {
    if (_selectedImage == null) return;
    setState(() => _processing = true);
    try {
      final result = await ApiService.restorePhoto(_selectedImage!);
      // Save to history (best-effort)
      try {
        await HistoryService.save(_selectedImage!, Uint8List.fromList(result.bytes));
      } catch (_) {}

      if (!mounted) return;
      Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => ResultScreen(
            beforeFile: _selectedImage!,
            afterBytes: result.bytes,
            processingMs: result.processingMs,
            detectedCategory: result.detectedCategory,
            detectedLabel: result.detectedLabel,
          ),
        ),
      );
    } on QuotaExceededException catch (e) {
      if (mounted) _showQuotaDialog(e.info);
    } catch (e) {
      _snack('Echec restauration : $e');
    } finally {
      if (mounted) {
        setState(() => _processing = false);
        _refreshQuota();
      }
    }
  }

  void _showAccountSheet() {
    final user = AuthService.currentUser;
    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) => Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Icon(Icons.account_circle,
                size: 56, color: AppColors.primaryBlue),
            const SizedBox(height: 8),
            Text(
              user?.email ?? 'Compte connecte',
              textAlign: TextAlign.center,
              style: const TextStyle(
                  fontSize: 16, fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 4),
            const Text(
              'Tes restaurations sont synchronisees dans le cloud.',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 12, color: AppColors.textMuted),
            ),
            const SizedBox(height: 20),
            OutlinedButton.icon(
              onPressed: () async {
                Navigator.pop(ctx);
                await AuthService.signOut();
                if (mounted) setState(() {});
              },
              icon: const Icon(Icons.logout, size: 18),
              label: const Text('Se deconnecter'),
              style: OutlinedButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 14)),
            ),
          ],
        ),
      ),
    );
  }

  void _showQuotaDialog(QuotaInfo? info) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        title: Row(
          children: const [
            Icon(Icons.workspace_premium, color: AppColors.accentRed),
            SizedBox(width: 8),
            Text('Limite atteinte'),
          ],
        ),
        content: Text(
          info != null
              ? 'Vous avez utilise vos ${info.limit} restaurations gratuites du jour.\n\nPassez Premium pour des restaurations illimitees, sans filigrane.'
              : 'Limite quotidienne atteinte. Passez Premium pour continuer.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Plus tard'),
          ),
          ElevatedButton(
            onPressed: () {
              Navigator.pop(ctx);
              _openPremium();
            },
            style: ElevatedButton.styleFrom(backgroundColor: AppColors.accentRed),
            child: const Text('Decouvrir Premium'),
          ),
        ],
      ),
    );
  }

  void _snack(String msg) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(msg), behavior: SnackBarBehavior.floating),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 32,
              height: 32,
              decoration: BoxDecoration(
                gradient: const LinearGradient(
                  colors: [AppColors.primaryBlue, AppColors.accentRed],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                ),
                borderRadius: BorderRadius.circular(10),
              ),
              child: const Icon(Icons.auto_awesome, color: Colors.white, size: 18),
            ),
            const SizedBox(width: 10),
            const Text('Souvenir AI',
                style: TextStyle(fontWeight: FontWeight.w700, fontSize: 18)),
          ],
        ),
        actions: [
          if (!_isPremium)
            IconButton(
              tooltip: 'Premium',
              icon: const Icon(Icons.workspace_premium,
                  color: AppColors.accentRed),
              onPressed: _openPremium,
            ),
          IconButton(
            tooltip: AuthService.isLoggedIn ? 'Mon compte' : 'Connexion',
            icon: Icon(AuthService.isLoggedIn
                ? Icons.account_circle
                : Icons.account_circle_outlined),
            onPressed: () async {
              if (AuthService.isLoggedIn) {
                _showAccountSheet();
              } else {
                await Navigator.push(
                  context,
                  MaterialPageRoute(builder: (_) => const AuthScreen()),
                );
                if (mounted) setState(() {});
              }
            },
          ),
          IconButton(
            tooltip: 'Reglages IA',
            icon: const Icon(Icons.tune),
            onPressed: () {
              Navigator.push(
                context,
                MaterialPageRoute(builder: (_) => const SettingsScreen()),
              );
            },
          ),
          IconButton(
            tooltip: 'Historique',
            icon: const Icon(Icons.history),
            onPressed: () {
              Navigator.push(
                context,
                MaterialPageRoute(builder: (_) => const HistoryScreen()),
              );
            },
          ),
        ],
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const SizedBox(height: 4),
              const Text(
                'Redonnez vie a vos souvenirs',
                style: TextStyle(
                  fontSize: 26,
                  fontWeight: FontWeight.w800,
                  height: 1.15,
                  color: AppColors.textDark,
                ),
              ),
              const SizedBox(height: 8),
              const Text(
                'Restaurez vos photos anciennes en quelques secondes grace a l\'IA.',
                style: TextStyle(fontSize: 15, color: AppColors.textMuted, height: 1.4),
              ),
              const SizedBox(height: 24),
              _previewCard(),
              const SizedBox(height: 20),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: _processing ? null : () => _pick(ImageSource.gallery),
                      icon: const Icon(Icons.photo_library_outlined),
                      label: const Text('Galerie'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: _processing ? null : () => _pick(ImageSource.camera),
                      icon: const Icon(Icons.camera_alt_outlined),
                      label: const Text('Camera'),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              // Bouton batch (premium) : restaure plusieurs photos d'un coup
              OutlinedButton.icon(
                onPressed: _processing ? null : _pickBatch,
                icon: Stack(
                  clipBehavior: Clip.none,
                  children: [
                    const Icon(Icons.burst_mode_outlined),
                    if (!_isPremium)
                      Positioned(
                        right: -6,
                        top: -6,
                        child: Container(
                          padding: const EdgeInsets.all(2),
                          decoration: const BoxDecoration(
                            color: AppColors.accentRed,
                            shape: BoxShape.circle,
                          ),
                          child: const Icon(Icons.lock,
                              size: 8, color: Colors.white),
                        ),
                      ),
                  ],
                ),
                label: Text(_isPremium
                    ? 'Restaurer plusieurs photos'
                    : 'Plusieurs photos (Premium)'),
                style: OutlinedButton.styleFrom(
                  side: BorderSide(
                      color: _isPremium
                          ? AppColors.primaryBlue
                          : AppColors.accentRed.withOpacity(0.6)),
                  foregroundColor: _isPremium
                      ? AppColors.primaryBlue
                      : AppColors.accentRed,
                ),
              ),
              const SizedBox(height: 14),
              ElevatedButton.icon(
                onPressed: (_selectedImage != null && !_processing) ? _restore : null,
                icon: _processing
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: SpinKitFadingCircle(color: Colors.white, size: 18),
                      )
                    : const Icon(Icons.auto_fix_high),
                label: Text(_processing ? 'Restauration en cours...' : 'Restaurer la photo'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.accentRed,
                  padding: const EdgeInsets.symmetric(vertical: 18),
                ),
              ),
              const SizedBox(height: 16),
              _quotaBadge(),
              _connectivityBanner(),
              const SizedBox(height: 16),
              _featuresGrid(),
            ],
          ),
        ),
      ),
    );
  }

  Widget _previewCard() {
    return AspectRatio(
      aspectRatio: 4 / 5,
      child: Container(
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: AppColors.softBlue, width: 1.5),
          boxShadow: [
            BoxShadow(
              color: AppColors.primaryBlue.withOpacity(0.06),
              blurRadius: 24,
              offset: const Offset(0, 8),
            ),
          ],
        ),
        clipBehavior: Clip.antiAlias,
        child: _selectedImage == null
            ? Center(
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Container(
                      width: 72,
                      height: 72,
                      decoration: const BoxDecoration(
                        color: AppColors.lightGrey,
                        shape: BoxShape.circle,
                      ),
                      child: const Icon(Icons.image_outlined,
                          size: 36, color: AppColors.primaryBlue),
                    ),
                    const SizedBox(height: 16),
                    const Text(
                      'Selectionnez une photo a restaurer',
                      style: TextStyle(color: AppColors.textMuted, fontSize: 14),
                    ),
                  ],
                ),
              )
            : Image.file(_selectedImage!, fit: BoxFit.cover),
      ),
    );
  }

  Widget _quotaBadge() {
    if (_isPremium) {
      return Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(
            gradient: const LinearGradient(
              colors: [AppColors.primaryBlue, AppColors.accentRed],
            ),
            borderRadius: BorderRadius.circular(12),
          ),
          child: Row(
            children: const [
              Icon(Icons.workspace_premium, color: Colors.white, size: 18),
              SizedBox(width: 8),
              Text('Premium - Restaurations illimitees',
                  style: TextStyle(
                      color: Colors.white,
                      fontSize: 13,
                      fontWeight: FontWeight.w700)),
            ],
          ),
        ),
      );
    }
    if (_quota == null) return const SizedBox.shrink();
    final q = _quota!;
    final critical = q.remaining <= 1;
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: GestureDetector(
        onTap: _openPremium,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(
            color: critical
                ? const Color(0xFFFFF3E0)
                : AppColors.softBlue.withOpacity(0.5),
            borderRadius: BorderRadius.circular(12),
          ),
          child: Row(
            children: [
              Icon(
                critical ? Icons.timer_outlined : Icons.bolt,
                size: 18,
                color: critical ? const Color(0xFFE65100) : AppColors.primaryBlue,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  '${q.remaining} / ${q.limit} restauration${q.limit > 1 ? "s" : ""} gratuite${q.limit > 1 ? "s" : ""} restantes aujourd\'hui',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: critical
                        ? const Color(0xFFE65100)
                        : AppColors.primaryBlue,
                  ),
                ),
              ),
              Text(
                'Premium',
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  color: AppColors.accentRed,
                ),
              ),
              const Icon(Icons.chevron_right, size: 16, color: AppColors.accentRed),
            ],
          ),
        ),
      ),
    );
  }

  Widget _connectivityBanner() {
    if (_backendOnline == null) return const SizedBox.shrink();
    final online = _backendOnline == true;
    return GestureDetector(
      onTap: _checkBackend,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        decoration: BoxDecoration(
          color: online
              ? const Color(0xFFE8F5E9)
              : const Color(0xFFFFEBEE),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Row(
          children: [
            Icon(
              online ? Icons.cloud_done_outlined : Icons.cloud_off_outlined,
              size: 18,
              color: online ? const Color(0xFF2E7D32) : AppColors.accentRed,
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                online
                    ? 'Serveur IA connecte'
                    : 'Serveur IA injoignable - verifiez l\'URL (${AppConfig.apiBaseUrl})',
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: online ? const Color(0xFF2E7D32) : AppColors.accentRed,
                ),
              ),
            ),
            if (!online)
              const Icon(Icons.refresh, size: 16, color: AppColors.accentRed),
          ],
        ),
      ),
    );
  }

  Widget _featuresGrid() {
    final items = [
      ('Visages', Icons.face_retouching_natural, 'Restauration realiste'),
      ('Nettete', Icons.tune, 'Correction du flou'),
      ('HD', Icons.high_quality, 'Upscale haute def.'),
      ('Couleurs', Icons.palette_outlined, 'Contraste & nuances'),
    ];
    return Wrap(
      spacing: 10,
      runSpacing: 10,
      children: items.map((it) {
        return Container(
          width: (MediaQuery.of(context).size.width - 50) / 2,
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: AppColors.surface,
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: AppColors.lightGrey),
          ),
          child: Row(
            children: [
              Icon(it.$2, color: AppColors.primaryBlue, size: 22),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(it.$1,
                        style: const TextStyle(
                            fontWeight: FontWeight.w700, fontSize: 13)),
                    Text(it.$3,
                        style: const TextStyle(
                            color: AppColors.textMuted, fontSize: 11)),
                  ],
                ),
              ),
            ],
          ),
        );
      }).toList(),
    );
  }
}
