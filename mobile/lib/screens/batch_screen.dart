import 'dart:io';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:image_gallery_saver_plus/image_gallery_saver_plus.dart';

import '../theme.dart';
import '../services/api_service.dart';
import '../services/history_service.dart';

/// Statut d'une photo dans le batch.
enum _BatchStatus { pending, processing, done, error }

class _BatchItem {
  final File source;
  _BatchStatus status = _BatchStatus.pending;
  Uint8List? restored;
  String? error;
  int processingMs = 0;
  _BatchItem(this.source);
}

/// Ecran de traitement batch (premium uniquement).
/// Restaure plusieurs photos en serie et permet de tout sauvegarder.
class BatchScreen extends StatefulWidget {
  final List<File> sources;

  const BatchScreen({super.key, required this.sources});

  @override
  State<BatchScreen> createState() => _BatchScreenState();
}

class _BatchScreenState extends State<BatchScreen> {
  late final List<_BatchItem> _items;
  bool _running = false;
  bool _cancelled = false;
  bool _savingAll = false;

  int get _doneCount =>
      _items.where((i) => i.status == _BatchStatus.done).length;
  int get _errorCount =>
      _items.where((i) => i.status == _BatchStatus.error).length;

  @override
  void initState() {
    super.initState();
    _items = widget.sources.map((f) => _BatchItem(f)).toList();
    WidgetsBinding.instance.addPostFrameCallback((_) => _runBatch());
  }

  Future<void> _runBatch() async {
    if (_running) return;
    setState(() => _running = true);
    for (final item in _items) {
      if (_cancelled) break;
      if (item.status == _BatchStatus.done) continue;
      setState(() => item.status = _BatchStatus.processing);
      try {
        final result = await ApiService.restorePhoto(item.source);
        item.restored = Uint8List.fromList(result.bytes);
        item.processingMs = result.processingMs;
        item.status = _BatchStatus.done;
        // Best-effort: enregistrer dans l'historique local
        try {
          await HistoryService.save(item.source, item.restored!);
        } catch (_) {}
      } catch (e) {
        item.error = e.toString();
        item.status = _BatchStatus.error;
      }
      if (mounted) setState(() {});
    }
    if (mounted) setState(() => _running = false);
  }

  Future<void> _saveAll() async {
    setState(() => _savingAll = true);
    int saved = 0;
    for (final item in _items) {
      if (item.status != _BatchStatus.done || item.restored == null) continue;
      try {
        final r = await ImageGallerySaverPlus.saveImage(
          item.restored!,
          quality: 95,
          name: 'souvenir_batch_${DateTime.now().millisecondsSinceEpoch}_$saved',
        );
        if (r is Map && r['isSuccess'] == true) saved++;
      } catch (_) {}
    }
    if (mounted) {
      setState(() => _savingAll = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('$saved photo(s) enregistree(s) dans la galerie'),
          behavior: SnackBarBehavior.floating,
        ),
      );
    }
  }

  Future<bool> _confirmExit() async {
    if (!_running) return true;
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Quitter le traitement ?'),
        content: const Text(
            'Le traitement en cours sera interrompu. Les photos deja restaurees seront conservees dans l\'historique.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Continuer'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Quitter'),
          ),
        ],
      ),
    );
    if (ok == true) _cancelled = true;
    return ok ?? false;
  }

  @override
  Widget build(BuildContext context) {
    final total = _items.length;
    final progress = total == 0 ? 0.0 : _doneCount / total;
    final allDone = !_running && _doneCount + _errorCount == total;

    return PopScope(
      canPop: !_running,
      onPopInvoked: (didPop) async {
        if (didPop) return;
        if (await _confirmExit()) {
          if (mounted) Navigator.pop(context);
        }
      },
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Traitement par lot',
              style: TextStyle(fontWeight: FontWeight.w700)),
          actions: [
            Padding(
              padding: const EdgeInsets.only(right: 12),
              child: Center(
                child: Container(
                  padding: const EdgeInsets.symmetric(
                      horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    color: AppColors.accentRed.withOpacity(0.1),
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: const Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.workspace_premium,
                          size: 14, color: AppColors.accentRed),
                      SizedBox(width: 4),
                      Text('PREMIUM',
                          style: TextStyle(
                              fontSize: 11,
                              fontWeight: FontWeight.w700,
                              color: AppColors.accentRed)),
                    ],
                  ),
                ),
              ),
            ),
          ],
        ),
        body: SafeArea(
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 12, 20, 8),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text(
                          '$_doneCount / $total restauree(s)',
                          style: const TextStyle(
                              fontWeight: FontWeight.w700, fontSize: 15),
                        ),
                        if (_errorCount > 0)
                          Text('$_errorCount erreur(s)',
                              style: const TextStyle(
                                  color: Colors.redAccent,
                                  fontSize: 13,
                                  fontWeight: FontWeight.w600)),
                      ],
                    ),
                    const SizedBox(height: 8),
                    ClipRRect(
                      borderRadius: BorderRadius.circular(8),
                      child: LinearProgressIndicator(
                        value: progress,
                        minHeight: 6,
                        backgroundColor: AppColors.softBlue,
                        valueColor: const AlwaysStoppedAnimation(
                            AppColors.primaryBlue),
                      ),
                    ),
                  ],
                ),
              ),
              Expanded(
                child: ListView.separated(
                  padding: const EdgeInsets.fromLTRB(20, 8, 20, 20),
                  itemCount: _items.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 10),
                  itemBuilder: (_, i) => _itemCard(_items[i], i),
                ),
              ),
              if (allDone)
                Padding(
                  padding: const EdgeInsets.fromLTRB(20, 8, 20, 20),
                  child: ElevatedButton.icon(
                    onPressed: _savingAll || _doneCount == 0 ? null : _saveAll,
                    icon: _savingAll
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(
                                strokeWidth: 2, color: Colors.white))
                        : const Icon(Icons.download_rounded),
                    label: Text(_savingAll
                        ? 'Enregistrement...'
                        : 'Enregistrer les $_doneCount photo(s)'),
                    style: ElevatedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 16),
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _itemCard(_BatchItem item, int index) {
    Widget statusIcon;
    Color borderColor = AppColors.softBlue;
    switch (item.status) {
      case _BatchStatus.pending:
        statusIcon = const Icon(Icons.schedule,
            color: AppColors.textMuted, size: 20);
        break;
      case _BatchStatus.processing:
        statusIcon = const SizedBox(
          width: 18,
          height: 18,
          child: CircularProgressIndicator(
              strokeWidth: 2, color: AppColors.primaryBlue),
        );
        borderColor = AppColors.primaryBlue;
        break;
      case _BatchStatus.done:
        statusIcon = const Icon(Icons.check_circle,
            color: Colors.green, size: 22);
        break;
      case _BatchStatus.error:
        statusIcon = const Icon(Icons.error_outline,
            color: Colors.redAccent, size: 22);
        borderColor = Colors.redAccent;
        break;
    }

    return Container(
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: borderColor.withOpacity(0.5), width: 1.2),
      ),
      padding: const EdgeInsets.all(10),
      child: Row(
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(8),
            child: SizedBox(
              width: 56,
              height: 56,
              child: item.restored != null
                  ? Image.memory(item.restored!, fit: BoxFit.cover)
                  : Image.file(item.source, fit: BoxFit.cover),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Photo ${index + 1}',
                  style: const TextStyle(
                      fontWeight: FontWeight.w600, fontSize: 14),
                ),
                const SizedBox(height: 2),
                Text(
                  _statusLabel(item),
                  style: TextStyle(
                      fontSize: 12,
                      color: item.status == _BatchStatus.error
                          ? Colors.redAccent
                          : AppColors.textMuted),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
          statusIcon,
        ],
      ),
    );
  }

  String _statusLabel(_BatchItem item) {
    switch (item.status) {
      case _BatchStatus.pending:
        return 'En attente...';
      case _BatchStatus.processing:
        return 'Restauration en cours...';
      case _BatchStatus.done:
        return 'Restauree en ${(item.processingMs / 1000).toStringAsFixed(1)} s';
      case _BatchStatus.error:
        final e = item.error ?? 'Erreur inconnue';
        return e.length > 80 ? '${e.substring(0, 80)}...' : e;
    }
  }
}
