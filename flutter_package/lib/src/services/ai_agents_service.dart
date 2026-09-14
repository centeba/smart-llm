import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/ai_agent_config.dart';
import '../models/ai_skill.dart';
import '../models/company_llm_api_key.dart';
import '../models/cost_dashboard.dart';

/// The Dio instance used by smart_llm_ui to talk to the backend.
///
/// In a standalone environment this defaults to a plain [Dio].  The host app
/// (e.g. user-master) **must** override this via a ProviderScope so that auth
/// headers, base-url, and error interceptors are wired in:
///
/// ```dart
/// ProviderScope(
///   overrides: [
///     smartLlmDioProvider.overrideWith((ref) => ref.watch(dioProvider)),
///   ],
///   child: const App(),
/// )
/// ```
final smartLlmDioProvider = Provider<Dio>((ref) => Dio());

final aiAgentsServiceProvider = Provider<AIAgentsService>((ref) {
  return AIAgentsService(ref.watch(smartLlmDioProvider));
});

/// Client for the smart-llm backend router (agents, skills, LLM keys).
///
/// Chat / thread endpoints intentionally live in the host application because
/// they carry per-app context (threads, evaluations, etc.).
class AIAgentsService {
  final Dio _dio;
  final String _base = '/api/v1';

  AIAgentsService(this._dio);

  // --- Agent Configs ---

  Future<AIAgentConfigsPublic> listConfigs({
    int skip = 0,
    int limit = 100,
    String? search,
  }) async {
    final response = await _dio.get(
      '$_base/ai-agents/',
      queryParameters: {
        'skip': skip,
        'limit': limit,
        if (search != null) 'search': search,
      },
    );
    return AIAgentConfigsPublic.fromJson(response.data as Map<String, dynamic>);
  }

  Future<AIAgentConfigPublic> getConfig(String id) async {
    final response = await _dio.get('$_base/ai-agents/$id');
    return AIAgentConfigPublic.fromJson(response.data as Map<String, dynamic>);
  }

  Future<AIAgentConfigPublic> createConfig(AIAgentConfigCreate data) async {
    final json = data.toJson()..removeWhere((_, v) => v == null);
    final response = await _dio.post('$_base/ai-agents/', data: json);
    return AIAgentConfigPublic.fromJson(response.data as Map<String, dynamic>);
  }

  Future<AIAgentConfigPublic> updateConfig(
      String id, AIAgentConfigUpdate data) async {
    final json = data.toJson()..removeWhere((_, v) => v == null);
    final response = await _dio.patch('$_base/ai-agents/$id', data: json);
    return AIAgentConfigPublic.fromJson(response.data as Map<String, dynamic>);
  }

  Future<void> deleteConfig(String id) async {
    await _dio.delete('$_base/ai-agents/$id');
  }

  // --- Skills ---

  Future<AISkillsPublic> listSkills({
    int skip = 0,
    int limit = 100,
    String? search,
  }) async {
    final response = await _dio.get(
      '$_base/ai-skills/',
      queryParameters: {
        'skip': skip,
        'limit': limit,
        if (search != null) 'search': search,
      },
    );
    return AISkillsPublic.fromJson(response.data as Map<String, dynamic>);
  }

  Future<AISkillPublic> getSkill(String id) async {
    final response = await _dio.get('$_base/ai-skills/$id');
    return AISkillPublic.fromJson(response.data as Map<String, dynamic>);
  }

  Future<AISkillPublic> createSkill(AISkillCreate data) async {
    final json = data.toJson()..removeWhere((_, v) => v == null);
    final response = await _dio.post('$_base/ai-skills/', data: json);
    return AISkillPublic.fromJson(response.data as Map<String, dynamic>);
  }

  Future<AISkillPublic> updateSkill(String id, AISkillUpdate data) async {
    final json = data.toJson()..removeWhere((_, v) => v == null);
    final response = await _dio.patch('$_base/ai-skills/$id', data: json);
    return AISkillPublic.fromJson(response.data as Map<String, dynamic>);
  }

  Future<void> deleteSkill(String id) async {
    await _dio.delete('$_base/ai-skills/$id');
  }

  // --- LLM Keys ---

  Future<CompanyLLMApiKeysPublic> listLLMKeys() async {
    final response = await _dio.get('$_base/ai-agents/llm-keys/');
    return CompanyLLMApiKeysPublic.fromJson(
        response.data as Map<String, dynamic>);
  }

  Future<CompanyLLMApiKeyPublic> createLLMKey(
      CompanyLLMApiKeyCreate data) async {
    final response = await _dio.post(
      '$_base/ai-agents/llm-keys/',
      data: data.toJson(),
    );
    return CompanyLLMApiKeyPublic.fromJson(
        response.data as Map<String, dynamic>);
  }

  Future<void> deleteLLMKey(String id) async {
    await _dio.delete('$_base/ai-agents/llm-keys/$id');
  }

  // --- Usage / cost ---

  Future<CostDashboard> getCostDashboard() async {
    final response = await _dio.get('$_base/ai-usage/cost-dashboard');
    return CostDashboard.fromJson(response.data as Map<String, dynamic>);
  }
}
