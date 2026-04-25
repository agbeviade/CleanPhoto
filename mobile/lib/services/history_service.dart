import 'dart:io';
import 'dart:typed_data';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

class HistoryEntry {
  final String beforePath;
  final String afterPath;
  final DateTime createdAt;
  HistoryEntry({required this.beforePath, required this.afterPath, required this.createdAt});

  String encode() => '$beforePath|$afterPath|${createdAt.millisecondsSinceEpoch}';
  static HistoryEntry? decode(String raw) {
    final parts = raw.split('|');
    if (parts.length != 3) return null;
    return HistoryEntry(
      beforePath: parts[0],
      afterPath: parts[1],
      createdAt: DateTime.fromMillisecondsSinceEpoch(int.parse(parts[2])),
    );
  }
}

class HistoryService {
  static const _key = 'history_v1';
  static const int maxEntries = 5;

  static Future<Directory> _historyDir() async {
    final base = await getApplicationDocumentsDirectory();
    final dir = Directory(p.join(base.path, 'history'));
    if (!dir.existsSync()) dir.createSync(recursive: true);
    return dir;
  }

  static Future<HistoryEntry> save(File before, Uint8List afterBytes) async {
    final dir = await _historyDir();
    final ts = DateTime.now().millisecondsSinceEpoch;
    final beforeDst = File(p.join(dir.path, 'before_$ts${p.extension(before.path)}'));
    final afterDst = File(p.join(dir.path, 'after_$ts.jpg'));
    await before.copy(beforeDst.path);
    await afterDst.writeAsBytes(afterBytes);

    final entry = HistoryEntry(
      beforePath: beforeDst.path,
      afterPath: afterDst.path,
      createdAt: DateTime.now(),
    );

    final prefs = await SharedPreferences.getInstance();
    final list = prefs.getStringList(_key) ?? [];
    list.insert(0, entry.encode());
    if (list.length > maxEntries) {
      // remove old files
      for (final old in list.sublist(maxEntries)) {
        final oldEntry = HistoryEntry.decode(old);
        if (oldEntry != null) {
          final f1 = File(oldEntry.beforePath);
          final f2 = File(oldEntry.afterPath);
          if (f1.existsSync()) f1.deleteSync();
          if (f2.existsSync()) f2.deleteSync();
        }
      }
      list.removeRange(maxEntries, list.length);
    }
    await prefs.setStringList(_key, list);
    return entry;
  }

  static Future<List<HistoryEntry>> all() async {
    final prefs = await SharedPreferences.getInstance();
    final list = prefs.getStringList(_key) ?? [];
    return list.map(HistoryEntry.decode).whereType<HistoryEntry>().toList();
  }

  static Future<void> clear() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_key);
    final dir = await _historyDir();
    if (dir.existsSync()) dir.deleteSync(recursive: true);
  }
}
