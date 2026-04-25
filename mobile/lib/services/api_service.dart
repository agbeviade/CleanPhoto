import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import 'package:path/path.dart' as p;
import '../config.dart';
import 'device_service.dart';
import 'premium_service.dart';
import 'settings_service.dart';
import 'auth_service.dart';

class RestoreResult {
  final List<int> bytes;
  final String? remoteUrl;
  final String? beforeUrl;
  final int processingMs;
  final String? jobId;
  final String? pipelineMode;
  final QuotaInfo? quota;
  final bool isPremium;

  RestoreResult({
    required this.bytes,
    this.remoteUrl,
    this.beforeUrl,
    required this.processingMs,
    this.jobId,
    this.pipelineMode,
    this.quota,
    this.isPremium = false,
  });
}

class QuotaInfo {
  final int used;
  final int limit;
  final int remaining;
  final bool premium;
  QuotaInfo({
    required this.used,
    required this.limit,
    required this.remaining,
    required this.premium,
  });
  factory QuotaInfo.fromJson(Map<String, dynamic> j) => QuotaInfo(
        used: (j['used'] as num?)?.toInt() ?? 0,
        limit: (j['limit'] as num?)?.toInt() ?? 3,
        remaining: (j['remaining'] as num?)?.toInt() ?? 0,
        premium: j['premium'] as bool? ?? false,
      );
}

class QuotaExceededException implements Exception {
  final QuotaInfo? info;
  QuotaExceededException(this.info);
  @override
  String toString() => 'Limite quotidienne atteinte';
}

class CloudHistoryItem {
  final String jobId;
  final String? beforeUrl;
  final String? afterUrl;
  final int? processingMs;
  final DateTime? createdAt;
  final String? pipeline;

  CloudHistoryItem({
    required this.jobId,
    this.beforeUrl,
    this.afterUrl,
    this.processingMs,
    this.createdAt,
    this.pipeline,
  });

  factory CloudHistoryItem.fromJson(Map<String, dynamic> j) => CloudHistoryItem(
        jobId: j['job_id'] as String? ?? '',
        beforeUrl: j['before_url'] as String?,
        afterUrl: j['after_url'] as String?,
        processingMs: (j['processing_ms'] as num?)?.toInt(),
        createdAt: j['created_at'] != null
            ? DateTime.tryParse(j['created_at'] as String)
            : null,
        pipeline: j['pipeline'] as String?,
      );
}

class ApiService {
  static Uri _u(String path) {
    final base = AppConfig.apiBaseUrl.endsWith('/')
        ? AppConfig.apiBaseUrl.substring(0, AppConfig.apiBaseUrl.length - 1)
        : AppConfig.apiBaseUrl;
    return Uri.parse('$base$path');
  }

  static Future<Map<String, String>> _authHeaders() async {
    final id = await DeviceService.getId();
    final premium = await PremiumService.isPremium();
    final token = AuthService.accessToken;
    return {
      'X-Device-Id': id,
      if (premium) 'X-Premium': '1',
      if (token != null && token.isNotEmpty) 'Authorization': 'Bearer $token',
    };
  }

  /// Recupere l'historique cloud de l'utilisateur connecte.
  /// Retourne null si non authentifie ou erreur.
  static Future<List<CloudHistoryItem>?> fetchCloudHistory({int limit = 20}) async {
    if (!AuthService.isLoggedIn) return null;
    try {
      final r = await http
          .get(_u('/api/history?limit=$limit'), headers: await _authHeaders())
          .timeout(const Duration(seconds: 8));
      if (r.statusCode != 200) return null;
      final body = jsonDecode(r.body) as Map<String, dynamic>;
      final items = (body['items'] as List?) ?? [];
      return items
          .map((e) => CloudHistoryItem.fromJson(Map<String, dynamic>.from(e)))
          .toList();
    } catch (_) {
      return null;
    }
  }

  /// Endpoint principal: tente d'abord /api/restore (Vercel),
  /// retombe sur /restore-binary pour recuperer toujours des bytes.
  static Future<RestoreResult> restorePhoto(File image,
      {RestoreSettings? settings}) async {
    final request = http.MultipartRequest('POST', _u('/api/restore'));
    request.headers.addAll(await _authHeaders());
    request.files.add(await http.MultipartFile.fromPath(
      'file',
      image.path,
      filename: p.basename(image.path),
    ));
    final s = settings ?? await SettingsService.load();
    request.fields['fidelity'] = s.fidelity.toStringAsFixed(2);
    request.fields['upscale'] = s.upscale.toString();

    final streamed = await request.send().timeout(const Duration(seconds: 90));
    final response = await http.Response.fromStream(streamed);

    if (response.statusCode == 429) {
      QuotaInfo? info;
      try {
        final body = jsonDecode(response.body);
        final detail = body['detail'];
        if (detail is Map && detail['quota'] is Map) {
          info = QuotaInfo.fromJson(Map<String, dynamic>.from(detail['quota']));
        }
      } catch (_) {}
      throw QuotaExceededException(info);
    }
    if (response.statusCode != 200) {
      throw Exception('Erreur backend (${response.statusCode}) : ${response.body}');
    }

    final ct = (response.headers['content-type'] ?? '').toLowerCase();
    final processingMs =
        int.tryParse(response.headers['x-processing-ms'] ?? '0') ?? 0;
    final jobId = response.headers['x-job-id'];
    final pipelineMode = response.headers['x-pipeline-mode'];

    if (ct.startsWith('application/json')) {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      final restoredUrl = body['restored_image_url'] as String?;
      final beforeUrl = body['before_image_url'] as String?;
      if (restoredUrl == null) {
        throw Exception('Reponse invalide: restored_image_url manquant');
      }
      final imgResp = await http.get(Uri.parse(restoredUrl)).timeout(
            const Duration(seconds: 30),
          );
      if (imgResp.statusCode != 200) {
        throw Exception('Impossible de telecharger l\'image restauree');
      }
      return RestoreResult(
        bytes: imgResp.bodyBytes,
        remoteUrl: restoredUrl,
        beforeUrl: beforeUrl,
        processingMs: body['processing_ms'] as int? ?? processingMs,
        jobId: body['job_id'] as String? ?? jobId,
        pipelineMode: body['pipeline'] as String? ?? pipelineMode,
        quota: body['quota'] is Map
            ? QuotaInfo.fromJson(Map<String, dynamic>.from(body['quota']))
            : null,
        isPremium: body['is_premium'] as bool? ?? false,
      );
    }

    // Mode binaire (fallback / pas de Supabase)
    final remaining = int.tryParse(response.headers['x-quota-remaining'] ?? '');
    final used = int.tryParse(response.headers['x-quota-used'] ?? '');
    return RestoreResult(
      bytes: response.bodyBytes,
      processingMs: processingMs,
      jobId: jobId,
      pipelineMode: pipelineMode,
      quota: (remaining != null)
          ? QuotaInfo(
              used: used ?? 0,
              limit: 3,
              remaining: remaining,
              premium: response.headers['x-premium'] == '1',
            )
          : null,
      isPremium: response.headers['x-premium'] == '1',
    );
  }

  /// Recupere le quota courant (sans declencher de restauration).
  static Future<QuotaInfo?> fetchQuota() async {
    try {
      final r = await http
          .get(_u('/api/quota'), headers: await _authHeaders())
          .timeout(const Duration(seconds: 5));
      if (r.statusCode != 200) return null;
      return QuotaInfo.fromJson(jsonDecode(r.body) as Map<String, dynamic>);
    } catch (_) {
      return null;
    }
  }

  static Future<bool> ping() async {
    try {
      final r = await http
          .get(_u('/api/health'))
          .timeout(const Duration(seconds: 4));
      return r.statusCode == 200;
    } catch (_) {
      // Fallback sur /health (mode local)
      try {
        final r = await http.get(_u('/health')).timeout(const Duration(seconds: 4));
        return r.statusCode == 200;
      } catch (_) {
        return false;
      }
    }
  }
}
