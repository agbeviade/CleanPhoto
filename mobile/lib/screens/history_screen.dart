import 'dart:io';
import 'package:flutter/material.dart';
import 'package:cached_network_image/cached_network_image.dart';
import 'package:http/http.dart' as http;
import 'package:intl/intl.dart' as intl;
import 'package:image_gallery_saver_plus/image_gallery_saver_plus.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

import '../theme.dart';
import '../services/history_service.dart';
import '../services/api_service.dart';
import '../services/auth_service.dart';
import 'auth_screen.dart';
import 'result_screen.dart';

class HistoryScreen extends StatefulWidget {
  const HistoryScreen({super.key});

  @override
  State<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends State<HistoryScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tab;
  late Future<List<HistoryEntry>> _localFuture;
  late Future<List<CloudHistoryItem>?> _cloudFuture;

  @override
  void initState() {
    super.initState();
    _tab = TabController(length: 2, vsync: this, initialIndex: AuthService.isLoggedIn ? 1 : 0);
    _localFuture = HistoryService.all();
    _cloudFuture = ApiService.fetchCloudHistory();
  }

  @override
  void dispose() {
    _tab.dispose();
    super.dispose();
  }

  Future<void> _refresh() async {
    setState(() {
      _localFuture = HistoryService.all();
      _cloudFuture = ApiService.fetchCloudHistory();
    });
  }

  Future<void> _confirmClear() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Effacer l\'historique ?'),
        content: const Text('Cette action est irreversible.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Annuler')),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: TextButton.styleFrom(foregroundColor: AppColors.accentRed),
            child: const Text('Effacer'),
          ),
        ],
      ),
    );
    if (ok == true) {
      await HistoryService.clear();
      _refresh();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Historique',
            style: TextStyle(fontWeight: FontWeight.w700)),
        actions: [
          IconButton(
            icon: const Icon(Icons.delete_outline),
            onPressed: _confirmClear,
            tooltip: 'Effacer (local)',
          ),
        ],
        bottom: TabBar(
          controller: _tab,
          labelColor: AppColors.primaryBlue,
          unselectedLabelColor: AppColors.textMuted,
          indicatorColor: AppColors.primaryBlue,
          tabs: const [
            Tab(text: 'Sur ce telephone', icon: Icon(Icons.phone_android, size: 18)),
            Tab(text: 'Cloud', icon: Icon(Icons.cloud_outlined, size: 18)),
          ],
        ),
      ),
      body: TabBarView(
        controller: _tab,
        children: [
          _localTab(),
          _cloudTab(),
        ],
      ),
    );
  }

  Widget _localTab() {
    return FutureBuilder<List<HistoryEntry>>(
      future: _localFuture,
      builder: (ctx, snap) {
        if (!snap.hasData) {
          return const Center(child: CircularProgressIndicator());
        }
        final list = snap.data!;
        if (list.isEmpty) return _empty('Aucune restauration locale.');
        return RefreshIndicator(
          onRefresh: _refresh,
          child: ListView.separated(
            padding: const EdgeInsets.all(16),
            itemCount: list.length,
            separatorBuilder: (_, __) => const SizedBox(height: 12),
            itemBuilder: (_, i) => _localTile(list[i]),
          ),
        );
      },
    );
  }

  Widget _cloudTab() {
    if (!AuthService.isLoggedIn) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.cloud_off,
                  size: 56, color: AppColors.textMuted),
              const SizedBox(height: 16),
              const Text('Connecte-toi pour synchroniser',
                  style: TextStyle(
                      fontSize: 16, fontWeight: FontWeight.w600)),
              const SizedBox(height: 8),
              const Text(
                'Tes restaurations seront accessibles sur tous tes appareils.',
                textAlign: TextAlign.center,
                style: TextStyle(color: AppColors.textMuted),
              ),
              const SizedBox(height: 20),
              ElevatedButton.icon(
                onPressed: () async {
                  await Navigator.push(
                    context,
                    MaterialPageRoute(builder: (_) => const AuthScreen()),
                  );
                  if (mounted) _refresh();
                },
                icon: const Icon(Icons.login, size: 18),
                label: const Text('Se connecter'),
              ),
            ],
          ),
        ),
      );
    }
    return FutureBuilder<List<CloudHistoryItem>?>(
      future: _cloudFuture,
      builder: (ctx, snap) {
        if (!snap.hasData && snap.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        final list = snap.data;
        if (list == null) {
          return _empty('Impossible de charger l\'historique cloud.');
        }
        if (list.isEmpty) return _empty('Aucune restauration cloud.');
        return RefreshIndicator(
          onRefresh: _refresh,
          child: ListView.separated(
            padding: const EdgeInsets.all(16),
            itemCount: list.length,
            separatorBuilder: (_, __) => const SizedBox(height: 12),
            itemBuilder: (_, i) => _cloudTile(list[i]),
          ),
        );
      },
    );
  }

  Widget _empty(String message) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              width: 80,
              height: 80,
              decoration: const BoxDecoration(
                color: AppColors.lightGrey,
                shape: BoxShape.circle,
              ),
              child: const Icon(Icons.history,
                  size: 40, color: AppColors.primaryBlue),
            ),
            const SizedBox(height: 16),
            Text(message,
                textAlign: TextAlign.center,
                style: const TextStyle(
                    fontSize: 14, color: AppColors.textMuted)),
          ],
        ),
      ),
    );
  }

  Widget _cloudTile(CloudHistoryItem e) {
    final df = intl.DateFormat('dd MMM yyyy - HH:mm', 'fr_FR');
    return InkWell(
      onTap: () => _openCloudDetail(e),
      borderRadius: BorderRadius.circular(16),
      child: Container(
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: AppColors.lightGrey),
        ),
        child: Row(
          children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(10),
              child: e.afterUrl != null
                  ? CachedNetworkImage(
                      imageUrl: e.afterUrl!,
                      width: 80,
                      height: 80,
                      fit: BoxFit.cover,
                      placeholder: (_, __) => const SizedBox(
                          width: 80,
                          height: 80,
                          child: Center(
                              child: SizedBox(
                                  width: 16,
                                  height: 16,
                                  child: CircularProgressIndicator(strokeWidth: 2)))),
                      errorWidget: (_, __, ___) => Container(
                        width: 80,
                        height: 80,
                        color: AppColors.lightGrey,
                        child: const Icon(Icons.broken_image_outlined,
                            color: AppColors.textMuted),
                      ),
                    )
                  : Container(
                      width: 80,
                      height: 80,
                      color: AppColors.lightGrey,
                    ),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                      e.createdAt != null
                          ? df.format(e.createdAt!.toLocal())
                          : 'Date inconnue',
                      style: const TextStyle(fontWeight: FontWeight.w600)),
                  const SizedBox(height: 4),
                  Text(
                    e.pipeline != null
                        ? 'Mode: ${e.pipeline} - ${e.processingMs ?? 0} ms'
                        : 'Touchez pour comparer / partager',
                    style: const TextStyle(
                        color: AppColors.textMuted, fontSize: 12),
                  ),
                ],
              ),
            ),
            if (e.afterUrl != null)
              IconButton(
                tooltip: 'Re-telecharger',
                icon: const Icon(Icons.download_rounded,
                    color: AppColors.primaryBlue),
                onPressed: () => _quickDownloadUrl(e.afterUrl!),
              ),
            const Icon(Icons.cloud_done, color: AppColors.primaryBlue, size: 20),
          ],
        ),
      ),
    );
  }

  Future<void> _quickDownloadUrl(String url) async {
    _snack('Telechargement en cours...');
    try {
      final resp = await http.get(Uri.parse(url))
          .timeout(const Duration(seconds: 30));
      if (resp.statusCode != 200) {
        _snack('Echec telechargement (HTTP ${resp.statusCode})');
        return;
      }
      final result = await ImageGallerySaverPlus.saveImage(
        resp.bodyBytes,
        quality: 95,
        name: 'souvenir_${DateTime.now().millisecondsSinceEpoch}',
      );
      final ok = (result is Map && result['isSuccess'] == true);
      _snack(ok ? 'Photo enregistree dans la galerie' : 'Echec enregistrement');
    } catch (e) {
      _snack('Erreur : $e');
    }
  }

  Future<void> _quickDownloadFile(String path) async {
    try {
      final bytes = await File(path).readAsBytes();
      final result = await ImageGallerySaverPlus.saveImage(
        bytes,
        quality: 95,
        name: 'souvenir_${DateTime.now().millisecondsSinceEpoch}',
      );
      final ok = (result is Map && result['isSuccess'] == true);
      _snack(ok ? 'Photo enregistree dans la galerie' : 'Echec enregistrement');
    } catch (e) {
      _snack('Erreur : $e');
    }
  }

  void _snack(String m) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(m), behavior: SnackBarBehavior.floating),
    );
  }

  Future<void> _openCloudDetail(CloudHistoryItem e) async {
    if (e.beforeUrl == null || e.afterUrl == null) {
      _snack('Images indisponibles');
      return;
    }
    // Affiche un loader pendant le download
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (_) => const Center(child: CircularProgressIndicator()),
    );
    try {
      final tmp = await getTemporaryDirectory();
      final ts = DateTime.now().millisecondsSinceEpoch;
      final beforeResp = await http.get(Uri.parse(e.beforeUrl!))
          .timeout(const Duration(seconds: 30));
      final afterResp = await http.get(Uri.parse(e.afterUrl!))
          .timeout(const Duration(seconds: 30));
      if (beforeResp.statusCode != 200 || afterResp.statusCode != 200) {
        if (mounted) Navigator.pop(context);
        _snack('Echec telechargement images');
        return;
      }
      final beforeFile = File(p.join(tmp.path, 'cloud_before_$ts.jpg'));
      await beforeFile.writeAsBytes(beforeResp.bodyBytes);
      if (!mounted) return;
      Navigator.pop(context); // close loader
      Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => ResultScreen(
            beforeFile: beforeFile,
            afterBytes: afterResp.bodyBytes,
            processingMs: e.processingMs ?? 0,
          ),
        ),
      );
    } catch (err) {
      if (mounted) Navigator.pop(context);
      _snack('Erreur : $err');
    }
  }

  Widget _localTile(HistoryEntry e) {
    final beforeFile = File(e.beforePath);
    final afterFile = File(e.afterPath);
    final exists = beforeFile.existsSync() && afterFile.existsSync();
    if (!exists) return const SizedBox.shrink();

    final df = intl.DateFormat('dd MMM yyyy - HH:mm', 'fr_FR');
    return InkWell(
      onTap: () => _openDetail(e),
      borderRadius: BorderRadius.circular(16),
      child: Container(
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: AppColors.lightGrey),
        ),
        child: Row(
          children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(10),
              child: Stack(
                children: [
                  Image.file(afterFile, width: 80, height: 80, fit: BoxFit.cover),
                  Positioned(
                    left: 0,
                    top: 0,
                    bottom: 0,
                    child: ClipRect(
                      clipper: _HalfClipper(),
                      child: Image.file(beforeFile, width: 80, height: 80, fit: BoxFit.cover),
                    ),
                  ),
                  Container(
                    width: 80,
                    height: 80,
                    alignment: Alignment.center,
                    child: Container(
                      width: 1.5,
                      color: Colors.white.withOpacity(0.9),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(df.format(e.createdAt),
                      style: const TextStyle(fontWeight: FontWeight.w600)),
                  const SizedBox(height: 4),
                  const Text('Touchez pour comparer / partager',
                      style: TextStyle(color: AppColors.textMuted, fontSize: 12)),
                ],
              ),
            ),
            IconButton(
              tooltip: 'Re-telecharger',
              icon: const Icon(Icons.download_rounded,
                  color: AppColors.primaryBlue),
              onPressed: () => _quickDownloadFile(e.afterPath),
            ),
            const Icon(Icons.chevron_right, color: AppColors.textMuted),
          ],
        ),
      ),
    );
  }

  Future<void> _openDetail(HistoryEntry e) async {
    try {
      final afterBytes = await File(e.afterPath).readAsBytes();
      if (!mounted) return;
      Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => ResultScreen(
            beforeFile: File(e.beforePath),
            afterBytes: afterBytes,
            processingMs: 0, // historique : pas de timing
          ),
        ),
      );
    } catch (err) {
      _snack('Impossible d\'ouvrir : $err');
    }
  }
}

class _HalfClipper extends CustomClipper<Rect> {
  @override
  Rect getClip(Size size) => Rect.fromLTWH(0, 0, size.width / 2, size.height);
  @override
  bool shouldReclip(_) => false;
}
