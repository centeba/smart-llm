// freezed puts @JsonSerializable on the factory constructor; the generator reads
// it there, but the analyzer only allows it on classes.
// ignore_for_file: invalid_annotation_target

import 'package:freezed_annotation/freezed_annotation.dart';

part 'company_llm_api_key.freezed.dart';
part 'company_llm_api_key.g.dart';

@freezed
class CompanyLLMApiKeyPublic with _$CompanyLLMApiKeyPublic {
  @JsonSerializable(fieldRename: FieldRename.snake)
  const factory CompanyLLMApiKeyPublic({
    required String id,
    required String companyId,
    required String provider,
    @Default(true) bool isActive,
    DateTime? createdAt,
  }) = _CompanyLLMApiKeyPublic;

  factory CompanyLLMApiKeyPublic.fromJson(Map<String, dynamic> json) =>
      _$CompanyLLMApiKeyPublicFromJson(json);
}

@freezed
class CompanyLLMApiKeysPublic with _$CompanyLLMApiKeysPublic {
  @JsonSerializable(fieldRename: FieldRename.snake)
  const factory CompanyLLMApiKeysPublic({
    required List<CompanyLLMApiKeyPublic> data,
    required int count,
  }) = _CompanyLLMApiKeysPublic;

  factory CompanyLLMApiKeysPublic.fromJson(Map<String, dynamic> json) =>
      _$CompanyLLMApiKeysPublicFromJson(json);
}

@freezed
class CompanyLLMApiKeyCreate with _$CompanyLLMApiKeyCreate {
  @JsonSerializable(fieldRename: FieldRename.snake)
  const factory CompanyLLMApiKeyCreate({
    required String provider,
    required String apiKey,
  }) = _CompanyLLMApiKeyCreate;

  factory CompanyLLMApiKeyCreate.fromJson(Map<String, dynamic> json) =>
      _$CompanyLLMApiKeyCreateFromJson(json);
}
