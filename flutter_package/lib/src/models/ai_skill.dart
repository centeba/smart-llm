import 'package:freezed_annotation/freezed_annotation.dart';

part 'ai_skill.freezed.dart';
part 'ai_skill.g.dart';

@freezed
class AISkillPublic with _$AISkillPublic {
  @JsonSerializable(fieldRename: FieldRename.snake)
  const factory AISkillPublic({
    required String id,
    required String companyId,
    required String name,
    String? label,
    String? description,
    String? icon,
    String? content,
    @Default(true) bool isActive,
    String? createdBy,
    DateTime? createdAt,
    DateTime? updatedAt,
  }) = _AISkillPublic;

  factory AISkillPublic.fromJson(Map<String, dynamic> json) =>
      _$AISkillPublicFromJson(json);
}

@freezed
class AISkillsPublic with _$AISkillsPublic {
  @JsonSerializable(fieldRename: FieldRename.snake)
  const factory AISkillsPublic({
    required List<AISkillPublic> data,
    required int count,
  }) = _AISkillsPublic;

  factory AISkillsPublic.fromJson(Map<String, dynamic> json) =>
      _$AISkillsPublicFromJson(json);
}

@freezed
class AISkillCreate with _$AISkillCreate {
  @JsonSerializable(fieldRename: FieldRename.snake)
  const factory AISkillCreate({
    required String name,
    String? label,
    String? description,
    String? icon,
    String? content,
    @Default(true) bool isActive,
  }) = _AISkillCreate;

  factory AISkillCreate.fromJson(Map<String, dynamic> json) =>
      _$AISkillCreateFromJson(json);
}

@freezed
class AISkillUpdate with _$AISkillUpdate {
  @JsonSerializable(fieldRename: FieldRename.snake)
  const factory AISkillUpdate({
    String? name,
    String? label,
    String? description,
    String? icon,
    String? content,
    bool? isActive,
  }) = _AISkillUpdate;

  factory AISkillUpdate.fromJson(Map<String, dynamic> json) =>
      _$AISkillUpdateFromJson(json);
}
