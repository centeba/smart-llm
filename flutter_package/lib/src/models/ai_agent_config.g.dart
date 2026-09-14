// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'ai_agent_config.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$AIAgentConfigPublicImpl _$$AIAgentConfigPublicImplFromJson(
        Map<String, dynamic> json) =>
    _$AIAgentConfigPublicImpl(
      id: json['id'] as String,
      companyId: json['company_id'] as String,
      name: json['name'] as String,
      label: json['label'] as String?,
      description: json['description'] as String?,
      icon: json['icon'] as String?,
      systemPrompt: json['system_prompt'] as String?,
      providerType: json['provider_type'] as String? ?? 'openai',
      modelName: json['model_name'] as String?,
      modelConfiguration: json['model_configuration'] as String?,
      responseFormat: json['response_format'] as String? ?? 'text',
      roleId: json['role_id'] as String?,
      isActive: json['is_active'] as bool? ?? true,
      isCustom: json['is_custom'] as bool? ?? true,
      createdBy: json['created_by'] as String?,
      createdAt: json['created_at'] == null
          ? null
          : DateTime.parse(json['created_at'] as String),
      updatedAt: json['updated_at'] == null
          ? null
          : DateTime.parse(json['updated_at'] as String),
      skills: (json['skills'] as List<dynamic>?)
              ?.map((e) => AISkillPublic.fromJson(e as Map<String, dynamic>))
              .toList() ??
          const [],
    );

Map<String, dynamic> _$$AIAgentConfigPublicImplToJson(
        _$AIAgentConfigPublicImpl instance) =>
    <String, dynamic>{
      'id': instance.id,
      'company_id': instance.companyId,
      'name': instance.name,
      'label': instance.label,
      'description': instance.description,
      'icon': instance.icon,
      'system_prompt': instance.systemPrompt,
      'provider_type': instance.providerType,
      'model_name': instance.modelName,
      'model_configuration': instance.modelConfiguration,
      'response_format': instance.responseFormat,
      'role_id': instance.roleId,
      'is_active': instance.isActive,
      'is_custom': instance.isCustom,
      'created_by': instance.createdBy,
      'created_at': instance.createdAt?.toIso8601String(),
      'updated_at': instance.updatedAt?.toIso8601String(),
      'skills': instance.skills,
    };

_$AIAgentConfigsPublicImpl _$$AIAgentConfigsPublicImplFromJson(
        Map<String, dynamic> json) =>
    _$AIAgentConfigsPublicImpl(
      data: (json['data'] as List<dynamic>)
          .map((e) => AIAgentConfigPublic.fromJson(e as Map<String, dynamic>))
          .toList(),
      count: (json['count'] as num).toInt(),
    );

Map<String, dynamic> _$$AIAgentConfigsPublicImplToJson(
        _$AIAgentConfigsPublicImpl instance) =>
    <String, dynamic>{
      'data': instance.data,
      'count': instance.count,
    };

_$AIAgentConfigCreateImpl _$$AIAgentConfigCreateImplFromJson(
        Map<String, dynamic> json) =>
    _$AIAgentConfigCreateImpl(
      name: json['name'] as String,
      label: json['label'] as String?,
      description: json['description'] as String?,
      icon: json['icon'] as String?,
      systemPrompt: json['system_prompt'] as String?,
      providerType: json['provider_type'] as String? ?? 'openai',
      modelName: json['model_name'] as String?,
      modelConfiguration: json['model_configuration'] as String?,
      responseFormat: json['response_format'] as String? ?? 'text',
      roleId: json['role_id'] as String?,
      isActive: json['is_active'] as bool? ?? true,
      skillIds: (json['skill_ids'] as List<dynamic>?)
              ?.map((e) => e as String)
              .toList() ??
          const [],
    );

Map<String, dynamic> _$$AIAgentConfigCreateImplToJson(
        _$AIAgentConfigCreateImpl instance) =>
    <String, dynamic>{
      'name': instance.name,
      'label': instance.label,
      'description': instance.description,
      'icon': instance.icon,
      'system_prompt': instance.systemPrompt,
      'provider_type': instance.providerType,
      'model_name': instance.modelName,
      'model_configuration': instance.modelConfiguration,
      'response_format': instance.responseFormat,
      'role_id': instance.roleId,
      'is_active': instance.isActive,
      'skill_ids': instance.skillIds,
    };

_$AIAgentConfigUpdateImpl _$$AIAgentConfigUpdateImplFromJson(
        Map<String, dynamic> json) =>
    _$AIAgentConfigUpdateImpl(
      name: json['name'] as String?,
      label: json['label'] as String?,
      description: json['description'] as String?,
      icon: json['icon'] as String?,
      systemPrompt: json['system_prompt'] as String?,
      providerType: json['provider_type'] as String?,
      modelName: json['model_name'] as String?,
      modelConfiguration: json['model_configuration'] as String?,
      responseFormat: json['response_format'] as String?,
      roleId: json['role_id'] as String?,
      isActive: json['is_active'] as bool?,
      skillIds: (json['skill_ids'] as List<dynamic>?)
          ?.map((e) => e as String)
          .toList(),
    );

Map<String, dynamic> _$$AIAgentConfigUpdateImplToJson(
        _$AIAgentConfigUpdateImpl instance) =>
    <String, dynamic>{
      'name': instance.name,
      'label': instance.label,
      'description': instance.description,
      'icon': instance.icon,
      'system_prompt': instance.systemPrompt,
      'provider_type': instance.providerType,
      'model_name': instance.modelName,
      'model_configuration': instance.modelConfiguration,
      'response_format': instance.responseFormat,
      'role_id': instance.roleId,
      'is_active': instance.isActive,
      'skill_ids': instance.skillIds,
    };
