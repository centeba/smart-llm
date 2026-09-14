// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'ai_skill.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$AISkillPublicImpl _$$AISkillPublicImplFromJson(Map<String, dynamic> json) =>
    _$AISkillPublicImpl(
      id: json['id'] as String,
      companyId: json['company_id'] as String,
      name: json['name'] as String,
      label: json['label'] as String?,
      description: json['description'] as String?,
      icon: json['icon'] as String?,
      content: json['content'] as String?,
      isActive: json['is_active'] as bool? ?? true,
      createdBy: json['created_by'] as String?,
      createdAt: json['created_at'] == null
          ? null
          : DateTime.parse(json['created_at'] as String),
      updatedAt: json['updated_at'] == null
          ? null
          : DateTime.parse(json['updated_at'] as String),
    );

Map<String, dynamic> _$$AISkillPublicImplToJson(_$AISkillPublicImpl instance) =>
    <String, dynamic>{
      'id': instance.id,
      'company_id': instance.companyId,
      'name': instance.name,
      'label': instance.label,
      'description': instance.description,
      'icon': instance.icon,
      'content': instance.content,
      'is_active': instance.isActive,
      'created_by': instance.createdBy,
      'created_at': instance.createdAt?.toIso8601String(),
      'updated_at': instance.updatedAt?.toIso8601String(),
    };

_$AISkillsPublicImpl _$$AISkillsPublicImplFromJson(Map<String, dynamic> json) =>
    _$AISkillsPublicImpl(
      data: (json['data'] as List<dynamic>)
          .map((e) => AISkillPublic.fromJson(e as Map<String, dynamic>))
          .toList(),
      count: (json['count'] as num).toInt(),
    );

Map<String, dynamic> _$$AISkillsPublicImplToJson(
        _$AISkillsPublicImpl instance) =>
    <String, dynamic>{
      'data': instance.data,
      'count': instance.count,
    };

_$AISkillCreateImpl _$$AISkillCreateImplFromJson(Map<String, dynamic> json) =>
    _$AISkillCreateImpl(
      name: json['name'] as String,
      label: json['label'] as String?,
      description: json['description'] as String?,
      icon: json['icon'] as String?,
      content: json['content'] as String?,
      isActive: json['is_active'] as bool? ?? true,
    );

Map<String, dynamic> _$$AISkillCreateImplToJson(_$AISkillCreateImpl instance) =>
    <String, dynamic>{
      'name': instance.name,
      'label': instance.label,
      'description': instance.description,
      'icon': instance.icon,
      'content': instance.content,
      'is_active': instance.isActive,
    };

_$AISkillUpdateImpl _$$AISkillUpdateImplFromJson(Map<String, dynamic> json) =>
    _$AISkillUpdateImpl(
      name: json['name'] as String?,
      label: json['label'] as String?,
      description: json['description'] as String?,
      icon: json['icon'] as String?,
      content: json['content'] as String?,
      isActive: json['is_active'] as bool?,
    );

Map<String, dynamic> _$$AISkillUpdateImplToJson(_$AISkillUpdateImpl instance) =>
    <String, dynamic>{
      'name': instance.name,
      'label': instance.label,
      'description': instance.description,
      'icon': instance.icon,
      'content': instance.content,
      'is_active': instance.isActive,
    };
