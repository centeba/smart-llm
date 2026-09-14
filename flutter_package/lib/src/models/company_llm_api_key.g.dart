// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'company_llm_api_key.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$CompanyLLMApiKeyPublicImpl _$$CompanyLLMApiKeyPublicImplFromJson(
        Map<String, dynamic> json) =>
    _$CompanyLLMApiKeyPublicImpl(
      id: json['id'] as String,
      companyId: json['company_id'] as String,
      provider: json['provider'] as String,
      isActive: json['is_active'] as bool? ?? true,
      createdAt: json['created_at'] == null
          ? null
          : DateTime.parse(json['created_at'] as String),
    );

Map<String, dynamic> _$$CompanyLLMApiKeyPublicImplToJson(
        _$CompanyLLMApiKeyPublicImpl instance) =>
    <String, dynamic>{
      'id': instance.id,
      'company_id': instance.companyId,
      'provider': instance.provider,
      'is_active': instance.isActive,
      'created_at': instance.createdAt?.toIso8601String(),
    };

_$CompanyLLMApiKeysPublicImpl _$$CompanyLLMApiKeysPublicImplFromJson(
        Map<String, dynamic> json) =>
    _$CompanyLLMApiKeysPublicImpl(
      data: (json['data'] as List<dynamic>)
          .map(
              (e) => CompanyLLMApiKeyPublic.fromJson(e as Map<String, dynamic>))
          .toList(),
      count: (json['count'] as num).toInt(),
    );

Map<String, dynamic> _$$CompanyLLMApiKeysPublicImplToJson(
        _$CompanyLLMApiKeysPublicImpl instance) =>
    <String, dynamic>{
      'data': instance.data,
      'count': instance.count,
    };

_$CompanyLLMApiKeyCreateImpl _$$CompanyLLMApiKeyCreateImplFromJson(
        Map<String, dynamic> json) =>
    _$CompanyLLMApiKeyCreateImpl(
      provider: json['provider'] as String,
      apiKey: json['api_key'] as String,
    );

Map<String, dynamic> _$$CompanyLLMApiKeyCreateImplToJson(
        _$CompanyLLMApiKeyCreateImpl instance) =>
    <String, dynamic>{
      'provider': instance.provider,
      'api_key': instance.apiKey,
    };
