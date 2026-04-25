import 'dart:io';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:image_gallery_saver_plus/image_gallery_saver_plus.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';
import 'package:path/path.dart' as p;

import '../theme.dart';
import '../widgets/before_after_slider.dart';

class ResultScreen extends StatefulWidget {
  final File beforeFile;
  final List<int> afterBytes;
  final int processingMs;

  const ResultScreen({
    super.key,
    required this.beforeFile,
    required this.afterBytes,
    required this.processingMs,
  });

  @override
  State<ResultScreen> createState() => _ResultScreenState();
}

class _ResultScreenState extends State<ResultScreen> {
  bool _saving = false;

  Uint8List get _afterUint8 => Uint8List.fromList(widget.afterBytes);

  Future<void> _download() async {
    setState(() => _saving = true);
    try {
      final result = await ImageGallerySaverPlus.saveImage(
        _afterUint8,
        quality: 95,
        name: 'souvenir_${DateTime.now().millisecondsSinceEpoch}',
      );
      final ok = (result is Map && result['isSuccess'] == true);
      _snack(ok ? 'Photo enregistree dans la galerie' : 'Echec enregistrement');
    } catch (e) {
      _snack('Erreur : $e');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _share() async {
    try {
      final tmp = await getTemporaryDirectory();
      final path = p.join(tmp.path,
          'souvenir_share_${DateTime.now().millisecondsSinceEpoch}.jpg');
      final f = File(path);
      await f.writeAsBytes(_afterUint8);
      // CTA viral : texte + lien app pour generer du bouche-a-oreille
      const link = 'https://clean-photo.vercel.app';
      const message =
          "J'ai restaure cette vieille photo en quelques secondes avec Souvenir AI ! "
          'Essaie gratuitement : $link';
      await Share.shareXFiles(
        [XFile(path)],
        text: message,
        subject: 'Photo restauree avec Souvenir AI',
      );
    } catch (e) {
      _snack('Erreur partage : $e');
    }
  }

  void _snack(String m) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(m), behavior: SnackBarBehavior.floating),
    );
  }

  @override
  Widget build(BuildContext context) {
    final beforeBytes = widget.beforeFile.readAsBytesSync();
    return Scaffold(
      appBar: AppBar(
        title: const Text('Resultat',
            style: TextStyle(fontWeight: FontWeight.w700)),
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                decoration: BoxDecoration(
                  color: AppColors.softBlue.withOpacity(0.5),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.auto_awesome,
                        color: AppColors.primaryBlue, size: 16),
                    const SizedBox(width: 6),
                    Text(
                      'Restauration en ${(widget.processingMs / 1000).toStringAsFixed(1)} s',
                      style: const TextStyle(
                          color: AppColors.primaryBlue,
                          fontWeight: FontWeight.w600,
                          fontSize: 12),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 14),
              const Text(
                'Glissez le curseur pour comparer',
                style: TextStyle(
                    fontSize: 13,
                    color: AppColors.textMuted,
                    fontWeight: FontWeight.w500),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 12),
              BeforeAfterSlider.fromBytes(
                beforeBytes: beforeBytes,
                afterBytes: _afterUint8,
              ),
              const SizedBox(height: 24),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: _share,
                      icon: const Icon(Icons.share_outlined),
                      label: const Text('Partager'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: ElevatedButton.icon(
                      onPressed: _saving ? null : _download,
                      icon: _saving
                          ? const SizedBox(
                              width: 16,
                              height: 16,
                              child: CircularProgressIndicator(
                                  strokeWidth: 2, color: Colors.white))
                          : const Icon(Icons.download_rounded),
                      label: Text(_saving ? 'Enregistrement...' : 'Telecharger'),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              TextButton.icon(
                onPressed: () => Navigator.pop(context),
                icon: const Icon(Icons.refresh),
                label: const Text('Restaurer une autre photo'),
                style: TextButton.styleFrom(foregroundColor: AppColors.primaryBlue),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
