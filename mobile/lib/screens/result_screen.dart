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
  final String? detectedCategory;
  final String? detectedLabel;

  const ResultScreen({
    super.key,
    required this.beforeFile,
    required this.afterBytes,
    required this.processingMs,
    this.detectedCategory,
    this.detectedLabel,
  });

  @override
  State<ResultScreen> createState() => _ResultScreenState();
}

class _ResultScreenState extends State<ResultScreen> {
  bool _saving = false;
  bool _sharing = false;

  /// CACHE : on lit le fichier beforeFile UNE seule fois (initState)
  /// au lieu de readAsBytesSync() dans build() qui causait des flashs
  /// d'image a chaque setState (re-IO disque).
  late final Uint8List _beforeBytes;
  late final Uint8List _afterUint8;

  /// True quand une operation longue est en cours (download/share).
  /// Bloque les autres boutons + affiche l'overlay.
  bool get _busy => _saving || _sharing;

  @override
  void initState() {
    super.initState();
    _beforeBytes = widget.beforeFile.readAsBytesSync();
    _afterUint8 = Uint8List.fromList(widget.afterBytes);
  }

  Future<void> _download() async {
    if (_busy) return;
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
    if (_busy) return;
    setState(() => _sharing = true);
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
    } finally {
      if (mounted) setState(() => _sharing = false);
    }
  }

  /// Retourne un badge "Optimise pour : <label>" si le classifier a detecte
  /// quelque chose d'autre que 'unknown' ou 'user_override'.
  Widget? _categoryBadge() {
    final cat = widget.detectedCategory;
    final label = widget.detectedLabel;
    if (label == null || label.isEmpty) return null;
    if (cat == 'unknown' || cat == 'user_override') return null;

    // Icone par categorie
    IconData icon;
    switch (cat) {
      case 'face_portrait':
        icon = Icons.person_outline;
        break;
      case 'face_group':
        icon = Icons.groups_outlined;
        break;
      case 'landscape':
        icon = Icons.landscape_outlined;
        break;
      case 'document':
        icon = Icons.description_outlined;
        break;
      case 'object':
        icon = Icons.image_outlined;
        break;
      default:
        icon = Icons.auto_awesome_outlined;
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: const Color(0xFFEDE9FE), // mauve doux
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: const Color(0xFFA78BFA), width: 1),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, color: const Color(0xFF6D28D9), size: 16),
          const SizedBox(width: 6),
          Text(
            'Optimise pour : $label',
            style: const TextStyle(
                color: Color(0xFF6D28D9),
                fontWeight: FontWeight.w600,
                fontSize: 12),
          ),
        ],
      ),
    );
  }

  void _snack(String m) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(m), behavior: SnackBarBehavior.floating),
    );
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      // Bloque le back pendant download/share
      canPop: !_busy,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Resultat',
              style: TextStyle(fontWeight: FontWeight.w700)),
          leading: _busy ? const SizedBox.shrink() : null,
        ),
        body: Stack(
          children: [
            AbsorbPointer(
              absorbing: _busy,
              child: SafeArea(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
                  child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Wrap(
                spacing: 8,
                runSpacing: 8,
                alignment: WrapAlignment.center,
                children: [
                  if (widget.processingMs > 0)
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 12, vertical: 8),
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
                  if (_categoryBadge() != null) _categoryBadge()!,
                ],
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
                beforeBytes: _beforeBytes,
                afterBytes: _afterUint8,
              ),
              const SizedBox(height: 24),
              Row(
                children: [
                  Expanded(
                    // Bouton garde TOUJOURS le meme look : pas de spinner inline,
                    // l'overlay s'occupe de l'indicateur de chargement.
                    child: OutlinedButton.icon(
                      onPressed: _busy ? null : _share,
                      icon: const Icon(Icons.share_outlined),
                      label: const Text('Partager'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: ElevatedButton.icon(
                      onPressed: _busy ? null : _download,
                      style: ElevatedButton.styleFrom(
                        // Couleurs identiques en disabled : pas de flash visuel
                        disabledBackgroundColor: AppColors.primaryBlue,
                        disabledForegroundColor: Colors.white,
                      ),
                      icon: const Icon(Icons.download_rounded),
                      label: const Text('Telecharger'),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              TextButton.icon(
                onPressed: _busy ? null : () => Navigator.pop(context),
                icon: const Icon(Icons.refresh),
                label: const Text('Restaurer une autre photo'),
                style: TextButton.styleFrom(foregroundColor: AppColors.primaryBlue),
              ),
                    ],
                  ),
                ),
              ),
            ),
            // Overlay qui fige l'ecran pendant download/share
            if (_busy) const _ResultOverlay(),
          ],
        ),
      ),
    );
  }
}

/// Overlay semi-transparent qui bloque toute interaction et fige le ResultScreen
/// pendant un download ou un partage. Utilise const pour zero rebuild.
class _ResultOverlay extends StatelessWidget {
  const _ResultOverlay();

  @override
  Widget build(BuildContext context) {
    return const Positioned.fill(
      child: ColoredBox(
        color: Color(0x66000000),
        child: Center(
          child: Card(
            elevation: 8,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.all(Radius.circular(16)),
            ),
            child: Padding(
              padding: EdgeInsets.symmetric(horizontal: 28, vertical: 24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  SizedBox(
                    width: 36,
                    height: 36,
                    child: CircularProgressIndicator(strokeWidth: 3),
                  ),
                  SizedBox(height: 16),
                  Text(
                    'Patientez...',
                    style: TextStyle(
                        fontSize: 14, fontWeight: FontWeight.w600),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
