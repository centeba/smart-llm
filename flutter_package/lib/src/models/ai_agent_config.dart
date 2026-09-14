// freezed puts @JsonSerializable on the factory constructor; the generator reads
// it there, but the analyzer only allows it on classes.
// ignore_for_file: invalid_annotation_target

import 'package:freezed_annotation/freezed_annotation.dart';
import 'ai_skill.dart';

part 'ai_agent_config.freezed.dart';
part 'ai_agent_config.g.dart';

@freezed
class AIAgentConfigPublic with _$AIAgentConfigPublic {
  @JsonSerializable(fieldRename: FieldRename.snake)
  const factory AIAgentConfigPublic({
    required String id,
    required String companyId,
    required String name,
    String? label,
    String? description,
    String? icon,
    String? systemPrompt,
    @Default('openai') String providerType,
    String? modelName,
    String? modelConfiguration,
    @Default('text') String responseFormat,
    String? roleId,
    @Default(true) bool isActive,
    @Default(true) bool isCustom,
    String? createdBy,
    DateTime? createdAt,
    DateTime? updatedAt,
    @Default([]) List<AISkillPublic> skills,
  }) = _AIAgentConfigPublic;

  factory AIAgentConfigPublic.fromJson(Map<String, dynamic> json) =>
      _$AIAgentConfigPublicFromJson(json);
}

@freezed
class AIAgentConfigsPublic with _$AIAgentConfigsPublic {
  @JsonSerializable(fieldRename: FieldRename.snake)
  const factory AIAgentConfigsPublic({
    required List<AIAgentConfigPublic> data,
    required int count,
  }) = _AIAgentConfigsPublic;

  factory AIAgentConfigsPublic.fromJson(Map<String, dynamic> json) =>
      _$AIAgentConfigsPublicFromJson(json);
}

@freezed
class AIAgentConfigCreate with _$AIAgentConfigCreate {
  @JsonSerializable(fieldRename: FieldRename.snake)
  const factory AIAgentConfigCreate({
    required String name,
    String? label,
    String? description,
    String? icon,
    String? systemPrompt,
    @Default('openai') String providerType,
    String? modelName,
    String? modelConfiguration,
    @Default('text') String responseFormat,
    String? roleId,
    @Default(true) bool isActive,
    @Default([]) List<String> skillIds,
  }) = _AIAgentConfigCreate;

  factory AIAgentConfigCreate.fromJson(Map<String, dynamic> json) =>
      _$AIAgentConfigCreateFromJson(json);
}

@freezed
class AIAgentConfigUpdate with _$AIAgentConfigUpdate {
  @JsonSerializable(fieldRename: FieldRename.snake)
  const factory AIAgentConfigUpdate({
    String? name,
    String? label,
    String? description,
    String? icon,
    String? systemPrompt,
    String? providerType,
    String? modelName,
    String? modelConfiguration,
    String? responseFormat,
    String? roleId,
    bool? isActive,
    List<String>? skillIds,
  }) = _AIAgentConfigUpdate;

  factory AIAgentConfigUpdate.fromJson(Map<String, dynamic> json) =>
      _$AIAgentConfigUpdateFromJson(json);
}
