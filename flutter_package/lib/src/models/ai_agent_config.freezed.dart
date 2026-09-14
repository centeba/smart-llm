// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'ai_agent_config.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

T _$identity<T>(T value) => value;

final _privateConstructorUsedError = UnsupportedError(
    'It seems like you constructed your class using `MyClass._()`. This constructor is only meant to be used by freezed and you are not supposed to need it nor use it.\nPlease check the documentation here for more information: https://github.com/rrousselGit/freezed#adding-getters-and-methods-to-our-models');

AIAgentConfigPublic _$AIAgentConfigPublicFromJson(Map<String, dynamic> json) {
  return _AIAgentConfigPublic.fromJson(json);
}

/// @nodoc
mixin _$AIAgentConfigPublic {
  String get id => throw _privateConstructorUsedError;
  String get companyId => throw _privateConstructorUsedError;
  String get name => throw _privateConstructorUsedError;
  String? get label => throw _privateConstructorUsedError;
  String? get description => throw _privateConstructorUsedError;
  String? get icon => throw _privateConstructorUsedError;
  String? get systemPrompt => throw _privateConstructorUsedError;
  String get providerType => throw _privateConstructorUsedError;
  String? get modelName => throw _privateConstructorUsedError;
  String? get modelConfiguration => throw _privateConstructorUsedError;
  String get responseFormat => throw _privateConstructorUsedError;
  String? get roleId => throw _privateConstructorUsedError;
  bool get isActive => throw _privateConstructorUsedError;
  bool get isCustom => throw _privateConstructorUsedError;
  String? get createdBy => throw _privateConstructorUsedError;
  DateTime? get createdAt => throw _privateConstructorUsedError;
  DateTime? get updatedAt => throw _privateConstructorUsedError;
  List<AISkillPublic> get skills => throw _privateConstructorUsedError;

  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;
  @JsonKey(ignore: true)
  $AIAgentConfigPublicCopyWith<AIAgentConfigPublic> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $AIAgentConfigPublicCopyWith<$Res> {
  factory $AIAgentConfigPublicCopyWith(
          AIAgentConfigPublic value, $Res Function(AIAgentConfigPublic) then) =
      _$AIAgentConfigPublicCopyWithImpl<$Res, AIAgentConfigPublic>;
  @useResult
  $Res call(
      {String id,
      String companyId,
      String name,
      String? label,
      String? description,
      String? icon,
      String? systemPrompt,
      String providerType,
      String? modelName,
      String? modelConfiguration,
      String responseFormat,
      String? roleId,
      bool isActive,
      bool isCustom,
      String? createdBy,
      DateTime? createdAt,
      DateTime? updatedAt,
      List<AISkillPublic> skills});
}

/// @nodoc
class _$AIAgentConfigPublicCopyWithImpl<$Res, $Val extends AIAgentConfigPublic>
    implements $AIAgentConfigPublicCopyWith<$Res> {
  _$AIAgentConfigPublicCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? companyId = null,
    Object? name = null,
    Object? label = freezed,
    Object? description = freezed,
    Object? icon = freezed,
    Object? systemPrompt = freezed,
    Object? providerType = null,
    Object? modelName = freezed,
    Object? modelConfiguration = freezed,
    Object? responseFormat = null,
    Object? roleId = freezed,
    Object? isActive = null,
    Object? isCustom = null,
    Object? createdBy = freezed,
    Object? createdAt = freezed,
    Object? updatedAt = freezed,
    Object? skills = null,
  }) {
    return _then(_value.copyWith(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      companyId: null == companyId
          ? _value.companyId
          : companyId // ignore: cast_nullable_to_non_nullable
              as String,
      name: null == name
          ? _value.name
          : name // ignore: cast_nullable_to_non_nullable
              as String,
      label: freezed == label
          ? _value.label
          : label // ignore: cast_nullable_to_non_nullable
              as String?,
      description: freezed == description
          ? _value.description
          : description // ignore: cast_nullable_to_non_nullable
              as String?,
      icon: freezed == icon
          ? _value.icon
          : icon // ignore: cast_nullable_to_non_nullable
              as String?,
      systemPrompt: freezed == systemPrompt
          ? _value.systemPrompt
          : systemPrompt // ignore: cast_nullable_to_non_nullable
              as String?,
      providerType: null == providerType
          ? _value.providerType
          : providerType // ignore: cast_nullable_to_non_nullable
              as String,
      modelName: freezed == modelName
          ? _value.modelName
          : modelName // ignore: cast_nullable_to_non_nullable
              as String?,
      modelConfiguration: freezed == modelConfiguration
          ? _value.modelConfiguration
          : modelConfiguration // ignore: cast_nullable_to_non_nullable
              as String?,
      responseFormat: null == responseFormat
          ? _value.responseFormat
          : responseFormat // ignore: cast_nullable_to_non_nullable
              as String,
      roleId: freezed == roleId
          ? _value.roleId
          : roleId // ignore: cast_nullable_to_non_nullable
              as String?,
      isActive: null == isActive
          ? _value.isActive
          : isActive // ignore: cast_nullable_to_non_nullable
              as bool,
      isCustom: null == isCustom
          ? _value.isCustom
          : isCustom // ignore: cast_nullable_to_non_nullable
              as bool,
      createdBy: freezed == createdBy
          ? _value.createdBy
          : createdBy // ignore: cast_nullable_to_non_nullable
              as String?,
      createdAt: freezed == createdAt
          ? _value.createdAt
          : createdAt // ignore: cast_nullable_to_non_nullable
              as DateTime?,
      updatedAt: freezed == updatedAt
          ? _value.updatedAt
          : updatedAt // ignore: cast_nullable_to_non_nullable
              as DateTime?,
      skills: null == skills
          ? _value.skills
          : skills // ignore: cast_nullable_to_non_nullable
              as List<AISkillPublic>,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$AIAgentConfigPublicImplCopyWith<$Res>
    implements $AIAgentConfigPublicCopyWith<$Res> {
  factory _$$AIAgentConfigPublicImplCopyWith(_$AIAgentConfigPublicImpl value,
          $Res Function(_$AIAgentConfigPublicImpl) then) =
      __$$AIAgentConfigPublicImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {String id,
      String companyId,
      String name,
      String? label,
      String? description,
      String? icon,
      String? systemPrompt,
      String providerType,
      String? modelName,
      String? modelConfiguration,
      String responseFormat,
      String? roleId,
      bool isActive,
      bool isCustom,
      String? createdBy,
      DateTime? createdAt,
      DateTime? updatedAt,
      List<AISkillPublic> skills});
}

/// @nodoc
class __$$AIAgentConfigPublicImplCopyWithImpl<$Res>
    extends _$AIAgentConfigPublicCopyWithImpl<$Res, _$AIAgentConfigPublicImpl>
    implements _$$AIAgentConfigPublicImplCopyWith<$Res> {
  __$$AIAgentConfigPublicImplCopyWithImpl(_$AIAgentConfigPublicImpl _value,
      $Res Function(_$AIAgentConfigPublicImpl) _then)
      : super(_value, _then);

  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? companyId = null,
    Object? name = null,
    Object? label = freezed,
    Object? description = freezed,
    Object? icon = freezed,
    Object? systemPrompt = freezed,
    Object? providerType = null,
    Object? modelName = freezed,
    Object? modelConfiguration = freezed,
    Object? responseFormat = null,
    Object? roleId = freezed,
    Object? isActive = null,
    Object? isCustom = null,
    Object? createdBy = freezed,
    Object? createdAt = freezed,
    Object? updatedAt = freezed,
    Object? skills = null,
  }) {
    return _then(_$AIAgentConfigPublicImpl(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      companyId: null == companyId
          ? _value.companyId
          : companyId // ignore: cast_nullable_to_non_nullable
              as String,
      name: null == name
          ? _value.name
          : name // ignore: cast_nullable_to_non_nullable
              as String,
      label: freezed == label
          ? _value.label
          : label // ignore: cast_nullable_to_non_nullable
              as String?,
      description: freezed == description
          ? _value.description
          : description // ignore: cast_nullable_to_non_nullable
              as String?,
      icon: freezed == icon
          ? _value.icon
          : icon // ignore: cast_nullable_to_non_nullable
              as String?,
      systemPrompt: freezed == systemPrompt
          ? _value.systemPrompt
          : systemPrompt // ignore: cast_nullable_to_non_nullable
              as String?,
      providerType: null == providerType
          ? _value.providerType
          : providerType // ignore: cast_nullable_to_non_nullable
              as String,
      modelName: freezed == modelName
          ? _value.modelName
          : modelName // ignore: cast_nullable_to_non_nullable
              as String?,
      modelConfiguration: freezed == modelConfiguration
          ? _value.modelConfiguration
          : modelConfiguration // ignore: cast_nullable_to_non_nullable
              as String?,
      responseFormat: null == responseFormat
          ? _value.responseFormat
          : responseFormat // ignore: cast_nullable_to_non_nullable
              as String,
      roleId: freezed == roleId
          ? _value.roleId
          : roleId // ignore: cast_nullable_to_non_nullable
              as String?,
      isActive: null == isActive
          ? _value.isActive
          : isActive // ignore: cast_nullable_to_non_nullable
              as bool,
      isCustom: null == isCustom
          ? _value.isCustom
          : isCustom // ignore: cast_nullable_to_non_nullable
              as bool,
      createdBy: freezed == createdBy
          ? _value.createdBy
          : createdBy // ignore: cast_nullable_to_non_nullable
              as String?,
      createdAt: freezed == createdAt
          ? _value.createdAt
          : createdAt // ignore: cast_nullable_to_non_nullable
              as DateTime?,
      updatedAt: freezed == updatedAt
          ? _value.updatedAt
          : updatedAt // ignore: cast_nullable_to_non_nullable
              as DateTime?,
      skills: null == skills
          ? _value._skills
          : skills // ignore: cast_nullable_to_non_nullable
              as List<AISkillPublic>,
    ));
  }
}

/// @nodoc

@JsonSerializable(fieldRename: FieldRename.snake)
class _$AIAgentConfigPublicImpl implements _AIAgentConfigPublic {
  const _$AIAgentConfigPublicImpl(
      {required this.id,
      required this.companyId,
      required this.name,
      this.label,
      this.description,
      this.icon,
      this.systemPrompt,
      this.providerType = 'openai',
      this.modelName,
      this.modelConfiguration,
      this.responseFormat = 'text',
      this.roleId,
      this.isActive = true,
      this.isCustom = true,
      this.createdBy,
      this.createdAt,
      this.updatedAt,
      final List<AISkillPublic> skills = const []})
      : _skills = skills;

  factory _$AIAgentConfigPublicImpl.fromJson(Map<String, dynamic> json) =>
      _$$AIAgentConfigPublicImplFromJson(json);

  @override
  final String id;
  @override
  final String companyId;
  @override
  final String name;
  @override
  final String? label;
  @override
  final String? description;
  @override
  final String? icon;
  @override
  final String? systemPrompt;
  @override
  @JsonKey()
  final String providerType;
  @override
  final String? modelName;
  @override
  final String? modelConfiguration;
  @override
  @JsonKey()
  final String responseFormat;
  @override
  final String? roleId;
  @override
  @JsonKey()
  final bool isActive;
  @override
  @JsonKey()
  final bool isCustom;
  @override
  final String? createdBy;
  @override
  final DateTime? createdAt;
  @override
  final DateTime? updatedAt;
  final List<AISkillPublic> _skills;
  @override
  @JsonKey()
  List<AISkillPublic> get skills {
    if (_skills is EqualUnmodifiableListView) return _skills;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableListView(_skills);
  }

  @override
  String toString() {
    return 'AIAgentConfigPublic(id: $id, companyId: $companyId, name: $name, label: $label, description: $description, icon: $icon, systemPrompt: $systemPrompt, providerType: $providerType, modelName: $modelName, modelConfiguration: $modelConfiguration, responseFormat: $responseFormat, roleId: $roleId, isActive: $isActive, isCustom: $isCustom, createdBy: $createdBy, createdAt: $createdAt, updatedAt: $updatedAt, skills: $skills)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$AIAgentConfigPublicImpl &&
            (identical(other.id, id) || other.id == id) &&
            (identical(other.companyId, companyId) ||
                other.companyId == companyId) &&
            (identical(other.name, name) || other.name == name) &&
            (identical(other.label, label) || other.label == label) &&
            (identical(other.description, description) ||
                other.description == description) &&
            (identical(other.icon, icon) || other.icon == icon) &&
            (identical(other.systemPrompt, systemPrompt) ||
                other.systemPrompt == systemPrompt) &&
            (identical(other.providerType, providerType) ||
                other.providerType == providerType) &&
            (identical(other.modelName, modelName) ||
                other.modelName == modelName) &&
            (identical(other.modelConfiguration, modelConfiguration) ||
                other.modelConfiguration == modelConfiguration) &&
            (identical(other.responseFormat, responseFormat) ||
                other.responseFormat == responseFormat) &&
            (identical(other.roleId, roleId) || other.roleId == roleId) &&
            (identical(other.isActive, isActive) ||
                other.isActive == isActive) &&
            (identical(other.isCustom, isCustom) ||
                other.isCustom == isCustom) &&
            (identical(other.createdBy, createdBy) ||
                other.createdBy == createdBy) &&
            (identical(other.createdAt, createdAt) ||
                other.createdAt == createdAt) &&
            (identical(other.updatedAt, updatedAt) ||
                other.updatedAt == updatedAt) &&
            const DeepCollectionEquality().equals(other._skills, _skills));
  }

  @JsonKey(ignore: true)
  @override
  int get hashCode => Object.hash(
      runtimeType,
      id,
      companyId,
      name,
      label,
      description,
      icon,
      systemPrompt,
      providerType,
      modelName,
      modelConfiguration,
      responseFormat,
      roleId,
      isActive,
      isCustom,
      createdBy,
      createdAt,
      updatedAt,
      const DeepCollectionEquality().hash(_skills));

  @JsonKey(ignore: true)
  @override
  @pragma('vm:prefer-inline')
  _$$AIAgentConfigPublicImplCopyWith<_$AIAgentConfigPublicImpl> get copyWith =>
      __$$AIAgentConfigPublicImplCopyWithImpl<_$AIAgentConfigPublicImpl>(
          this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$AIAgentConfigPublicImplToJson(
      this,
    );
  }
}

abstract class _AIAgentConfigPublic implements AIAgentConfigPublic {
  const factory _AIAgentConfigPublic(
      {required final String id,
      required final String companyId,
      required final String name,
      final String? label,
      final String? description,
      final String? icon,
      final String? systemPrompt,
      final String providerType,
      final String? modelName,
      final String? modelConfiguration,
      final String responseFormat,
      final String? roleId,
      final bool isActive,
      final bool isCustom,
      final String? createdBy,
      final DateTime? createdAt,
      final DateTime? updatedAt,
      final List<AISkillPublic> skills}) = _$AIAgentConfigPublicImpl;

  factory _AIAgentConfigPublic.fromJson(Map<String, dynamic> json) =
      _$AIAgentConfigPublicImpl.fromJson;

  @override
  String get id;
  @override
  String get companyId;
  @override
  String get name;
  @override
  String? get label;
  @override
  String? get description;
  @override
  String? get icon;
  @override
  String? get systemPrompt;
  @override
  String get providerType;
  @override
  String? get modelName;
  @override
  String? get modelConfiguration;
  @override
  String get responseFormat;
  @override
  String? get roleId;
  @override
  bool get isActive;
  @override
  bool get isCustom;
  @override
  String? get createdBy;
  @override
  DateTime? get createdAt;
  @override
  DateTime? get updatedAt;
  @override
  List<AISkillPublic> get skills;
  @override
  @JsonKey(ignore: true)
  _$$AIAgentConfigPublicImplCopyWith<_$AIAgentConfigPublicImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

AIAgentConfigsPublic _$AIAgentConfigsPublicFromJson(Map<String, dynamic> json) {
  return _AIAgentConfigsPublic.fromJson(json);
}

/// @nodoc
mixin _$AIAgentConfigsPublic {
  List<AIAgentConfigPublic> get data => throw _privateConstructorUsedError;
  int get count => throw _privateConstructorUsedError;

  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;
  @JsonKey(ignore: true)
  $AIAgentConfigsPublicCopyWith<AIAgentConfigsPublic> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $AIAgentConfigsPublicCopyWith<$Res> {
  factory $AIAgentConfigsPublicCopyWith(AIAgentConfigsPublic value,
          $Res Function(AIAgentConfigsPublic) then) =
      _$AIAgentConfigsPublicCopyWithImpl<$Res, AIAgentConfigsPublic>;
  @useResult
  $Res call({List<AIAgentConfigPublic> data, int count});
}

/// @nodoc
class _$AIAgentConfigsPublicCopyWithImpl<$Res,
        $Val extends AIAgentConfigsPublic>
    implements $AIAgentConfigsPublicCopyWith<$Res> {
  _$AIAgentConfigsPublicCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? data = null,
    Object? count = null,
  }) {
    return _then(_value.copyWith(
      data: null == data
          ? _value.data
          : data // ignore: cast_nullable_to_non_nullable
              as List<AIAgentConfigPublic>,
      count: null == count
          ? _value.count
          : count // ignore: cast_nullable_to_non_nullable
              as int,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$AIAgentConfigsPublicImplCopyWith<$Res>
    implements $AIAgentConfigsPublicCopyWith<$Res> {
  factory _$$AIAgentConfigsPublicImplCopyWith(_$AIAgentConfigsPublicImpl value,
          $Res Function(_$AIAgentConfigsPublicImpl) then) =
      __$$AIAgentConfigsPublicImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({List<AIAgentConfigPublic> data, int count});
}

/// @nodoc
class __$$AIAgentConfigsPublicImplCopyWithImpl<$Res>
    extends _$AIAgentConfigsPublicCopyWithImpl<$Res, _$AIAgentConfigsPublicImpl>
    implements _$$AIAgentConfigsPublicImplCopyWith<$Res> {
  __$$AIAgentConfigsPublicImplCopyWithImpl(_$AIAgentConfigsPublicImpl _value,
      $Res Function(_$AIAgentConfigsPublicImpl) _then)
      : super(_value, _then);

  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? data = null,
    Object? count = null,
  }) {
    return _then(_$AIAgentConfigsPublicImpl(
      data: null == data
          ? _value._data
          : data // ignore: cast_nullable_to_non_nullable
              as List<AIAgentConfigPublic>,
      count: null == count
          ? _value.count
          : count // ignore: cast_nullable_to_non_nullable
              as int,
    ));
  }
}

/// @nodoc

@JsonSerializable(fieldRename: FieldRename.snake)
class _$AIAgentConfigsPublicImpl implements _AIAgentConfigsPublic {
  const _$AIAgentConfigsPublicImpl(
      {required final List<AIAgentConfigPublic> data, required this.count})
      : _data = data;

  factory _$AIAgentConfigsPublicImpl.fromJson(Map<String, dynamic> json) =>
      _$$AIAgentConfigsPublicImplFromJson(json);

  final List<AIAgentConfigPublic> _data;
  @override
  List<AIAgentConfigPublic> get data {
    if (_data is EqualUnmodifiableListView) return _data;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableListView(_data);
  }

  @override
  final int count;

  @override
  String toString() {
    return 'AIAgentConfigsPublic(data: $data, count: $count)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$AIAgentConfigsPublicImpl &&
            const DeepCollectionEquality().equals(other._data, _data) &&
            (identical(other.count, count) || other.count == count));
  }

  @JsonKey(ignore: true)
  @override
  int get hashCode => Object.hash(
      runtimeType, const DeepCollectionEquality().hash(_data), count);

  @JsonKey(ignore: true)
  @override
  @pragma('vm:prefer-inline')
  _$$AIAgentConfigsPublicImplCopyWith<_$AIAgentConfigsPublicImpl>
      get copyWith =>
          __$$AIAgentConfigsPublicImplCopyWithImpl<_$AIAgentConfigsPublicImpl>(
              this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$AIAgentConfigsPublicImplToJson(
      this,
    );
  }
}

abstract class _AIAgentConfigsPublic implements AIAgentConfigsPublic {
  const factory _AIAgentConfigsPublic(
      {required final List<AIAgentConfigPublic> data,
      required final int count}) = _$AIAgentConfigsPublicImpl;

  factory _AIAgentConfigsPublic.fromJson(Map<String, dynamic> json) =
      _$AIAgentConfigsPublicImpl.fromJson;

  @override
  List<AIAgentConfigPublic> get data;
  @override
  int get count;
  @override
  @JsonKey(ignore: true)
  _$$AIAgentConfigsPublicImplCopyWith<_$AIAgentConfigsPublicImpl>
      get copyWith => throw _privateConstructorUsedError;
}

AIAgentConfigCreate _$AIAgentConfigCreateFromJson(Map<String, dynamic> json) {
  return _AIAgentConfigCreate.fromJson(json);
}

/// @nodoc
mixin _$AIAgentConfigCreate {
  String get name => throw _privateConstructorUsedError;
  String? get label => throw _privateConstructorUsedError;
  String? get description => throw _privateConstructorUsedError;
  String? get icon => throw _privateConstructorUsedError;
  String? get systemPrompt => throw _privateConstructorUsedError;
  String get providerType => throw _privateConstructorUsedError;
  String? get modelName => throw _privateConstructorUsedError;
  String? get modelConfiguration => throw _privateConstructorUsedError;
  String get responseFormat => throw _privateConstructorUsedError;
  String? get roleId => throw _privateConstructorUsedError;
  bool get isActive => throw _privateConstructorUsedError;
  List<String> get skillIds => throw _privateConstructorUsedError;

  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;
  @JsonKey(ignore: true)
  $AIAgentConfigCreateCopyWith<AIAgentConfigCreate> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $AIAgentConfigCreateCopyWith<$Res> {
  factory $AIAgentConfigCreateCopyWith(
          AIAgentConfigCreate value, $Res Function(AIAgentConfigCreate) then) =
      _$AIAgentConfigCreateCopyWithImpl<$Res, AIAgentConfigCreate>;
  @useResult
  $Res call(
      {String name,
      String? label,
      String? description,
      String? icon,
      String? systemPrompt,
      String providerType,
      String? modelName,
      String? modelConfiguration,
      String responseFormat,
      String? roleId,
      bool isActive,
      List<String> skillIds});
}

/// @nodoc
class _$AIAgentConfigCreateCopyWithImpl<$Res, $Val extends AIAgentConfigCreate>
    implements $AIAgentConfigCreateCopyWith<$Res> {
  _$AIAgentConfigCreateCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? name = null,
    Object? label = freezed,
    Object? description = freezed,
    Object? icon = freezed,
    Object? systemPrompt = freezed,
    Object? providerType = null,
    Object? modelName = freezed,
    Object? modelConfiguration = freezed,
    Object? responseFormat = null,
    Object? roleId = freezed,
    Object? isActive = null,
    Object? skillIds = null,
  }) {
    return _then(_value.copyWith(
      name: null == name
          ? _value.name
          : name // ignore: cast_nullable_to_non_nullable
              as String,
      label: freezed == label
          ? _value.label
          : label // ignore: cast_nullable_to_non_nullable
              as String?,
      description: freezed == description
          ? _value.description
          : description // ignore: cast_nullable_to_non_nullable
              as String?,
      icon: freezed == icon
          ? _value.icon
          : icon // ignore: cast_nullable_to_non_nullable
              as String?,
      systemPrompt: freezed == systemPrompt
          ? _value.systemPrompt
          : systemPrompt // ignore: cast_nullable_to_non_nullable
              as String?,
      providerType: null == providerType
          ? _value.providerType
          : providerType // ignore: cast_nullable_to_non_nullable
              as String,
      modelName: freezed == modelName
          ? _value.modelName
          : modelName // ignore: cast_nullable_to_non_nullable
              as String?,
      modelConfiguration: freezed == modelConfiguration
          ? _value.modelConfiguration
          : modelConfiguration // ignore: cast_nullable_to_non_nullable
              as String?,
      responseFormat: null == responseFormat
          ? _value.responseFormat
          : responseFormat // ignore: cast_nullable_to_non_nullable
              as String,
      roleId: freezed == roleId
          ? _value.roleId
          : roleId // ignore: cast_nullable_to_non_nullable
              as String?,
      isActive: null == isActive
          ? _value.isActive
          : isActive // ignore: cast_nullable_to_non_nullable
              as bool,
      skillIds: null == skillIds
          ? _value.skillIds
          : skillIds // ignore: cast_nullable_to_non_nullable
              as List<String>,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$AIAgentConfigCreateImplCopyWith<$Res>
    implements $AIAgentConfigCreateCopyWith<$Res> {
  factory _$$AIAgentConfigCreateImplCopyWith(_$AIAgentConfigCreateImpl value,
          $Res Function(_$AIAgentConfigCreateImpl) then) =
      __$$AIAgentConfigCreateImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {String name,
      String? label,
      String? description,
      String? icon,
      String? systemPrompt,
      String providerType,
      String? modelName,
      String? modelConfiguration,
      String responseFormat,
      String? roleId,
      bool isActive,
      List<String> skillIds});
}

/// @nodoc
class __$$AIAgentConfigCreateImplCopyWithImpl<$Res>
    extends _$AIAgentConfigCreateCopyWithImpl<$Res, _$AIAgentConfigCreateImpl>
    implements _$$AIAgentConfigCreateImplCopyWith<$Res> {
  __$$AIAgentConfigCreateImplCopyWithImpl(_$AIAgentConfigCreateImpl _value,
      $Res Function(_$AIAgentConfigCreateImpl) _then)
      : super(_value, _then);

  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? name = null,
    Object? label = freezed,
    Object? description = freezed,
    Object? icon = freezed,
    Object? systemPrompt = freezed,
    Object? providerType = null,
    Object? modelName = freezed,
    Object? modelConfiguration = freezed,
    Object? responseFormat = null,
    Object? roleId = freezed,
    Object? isActive = null,
    Object? skillIds = null,
  }) {
    return _then(_$AIAgentConfigCreateImpl(
      name: null == name
          ? _value.name
          : name // ignore: cast_nullable_to_non_nullable
              as String,
      label: freezed == label
          ? _value.label
          : label // ignore: cast_nullable_to_non_nullable
              as String?,
      description: freezed == description
          ? _value.description
          : description // ignore: cast_nullable_to_non_nullable
              as String?,
      icon: freezed == icon
          ? _value.icon
          : icon // ignore: cast_nullable_to_non_nullable
              as String?,
      systemPrompt: freezed == systemPrompt
          ? _value.systemPrompt
          : systemPrompt // ignore: cast_nullable_to_non_nullable
              as String?,
      providerType: null == providerType
          ? _value.providerType
          : providerType // ignore: cast_nullable_to_non_nullable
              as String,
      modelName: freezed == modelName
          ? _value.modelName
          : modelName // ignore: cast_nullable_to_non_nullable
              as String?,
      modelConfiguration: freezed == modelConfiguration
          ? _value.modelConfiguration
          : modelConfiguration // ignore: cast_nullable_to_non_nullable
              as String?,
      responseFormat: null == responseFormat
          ? _value.responseFormat
          : responseFormat // ignore: cast_nullable_to_non_nullable
              as String,
      roleId: freezed == roleId
          ? _value.roleId
          : roleId // ignore: cast_nullable_to_non_nullable
              as String?,
      isActive: null == isActive
          ? _value.isActive
          : isActive // ignore: cast_nullable_to_non_nullable
              as bool,
      skillIds: null == skillIds
          ? _value._skillIds
          : skillIds // ignore: cast_nullable_to_non_nullable
              as List<String>,
    ));
  }
}

/// @nodoc

@JsonSerializable(fieldRename: FieldRename.snake)
class _$AIAgentConfigCreateImpl implements _AIAgentConfigCreate {
  const _$AIAgentConfigCreateImpl(
      {required this.name,
      this.label,
      this.description,
      this.icon,
      this.systemPrompt,
      this.providerType = 'openai',
      this.modelName,
      this.modelConfiguration,
      this.responseFormat = 'text',
      this.roleId,
      this.isActive = true,
      final List<String> skillIds = const []})
      : _skillIds = skillIds;

  factory _$AIAgentConfigCreateImpl.fromJson(Map<String, dynamic> json) =>
      _$$AIAgentConfigCreateImplFromJson(json);

  @override
  final String name;
  @override
  final String? label;
  @override
  final String? description;
  @override
  final String? icon;
  @override
  final String? systemPrompt;
  @override
  @JsonKey()
  final String providerType;
  @override
  final String? modelName;
  @override
  final String? modelConfiguration;
  @override
  @JsonKey()
  final String responseFormat;
  @override
  final String? roleId;
  @override
  @JsonKey()
  final bool isActive;
  final List<String> _skillIds;
  @override
  @JsonKey()
  List<String> get skillIds {
    if (_skillIds is EqualUnmodifiableListView) return _skillIds;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableListView(_skillIds);
  }

  @override
  String toString() {
    return 'AIAgentConfigCreate(name: $name, label: $label, description: $description, icon: $icon, systemPrompt: $systemPrompt, providerType: $providerType, modelName: $modelName, modelConfiguration: $modelConfiguration, responseFormat: $responseFormat, roleId: $roleId, isActive: $isActive, skillIds: $skillIds)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$AIAgentConfigCreateImpl &&
            (identical(other.name, name) || other.name == name) &&
            (identical(other.label, label) || other.label == label) &&
            (identical(other.description, description) ||
                other.description == description) &&
            (identical(other.icon, icon) || other.icon == icon) &&
            (identical(other.systemPrompt, systemPrompt) ||
                other.systemPrompt == systemPrompt) &&
            (identical(other.providerType, providerType) ||
                other.providerType == providerType) &&
            (identical(other.modelName, modelName) ||
                other.modelName == modelName) &&
            (identical(other.modelConfiguration, modelConfiguration) ||
                other.modelConfiguration == modelConfiguration) &&
            (identical(other.responseFormat, responseFormat) ||
                other.responseFormat == responseFormat) &&
            (identical(other.roleId, roleId) || other.roleId == roleId) &&
            (identical(other.isActive, isActive) ||
                other.isActive == isActive) &&
            const DeepCollectionEquality().equals(other._skillIds, _skillIds));
  }

  @JsonKey(ignore: true)
  @override
  int get hashCode => Object.hash(
      runtimeType,
      name,
      label,
      description,
      icon,
      systemPrompt,
      providerType,
      modelName,
      modelConfiguration,
      responseFormat,
      roleId,
      isActive,
      const DeepCollectionEquality().hash(_skillIds));

  @JsonKey(ignore: true)
  @override
  @pragma('vm:prefer-inline')
  _$$AIAgentConfigCreateImplCopyWith<_$AIAgentConfigCreateImpl> get copyWith =>
      __$$AIAgentConfigCreateImplCopyWithImpl<_$AIAgentConfigCreateImpl>(
          this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$AIAgentConfigCreateImplToJson(
      this,
    );
  }
}

abstract class _AIAgentConfigCreate implements AIAgentConfigCreate {
  const factory _AIAgentConfigCreate(
      {required final String name,
      final String? label,
      final String? description,
      final String? icon,
      final String? systemPrompt,
      final String providerType,
      final String? modelName,
      final String? modelConfiguration,
      final String responseFormat,
      final String? roleId,
      final bool isActive,
      final List<String> skillIds}) = _$AIAgentConfigCreateImpl;

  factory _AIAgentConfigCreate.fromJson(Map<String, dynamic> json) =
      _$AIAgentConfigCreateImpl.fromJson;

  @override
  String get name;
  @override
  String? get label;
  @override
  String? get description;
  @override
  String? get icon;
  @override
  String? get systemPrompt;
  @override
  String get providerType;
  @override
  String? get modelName;
  @override
  String? get modelConfiguration;
  @override
  String get responseFormat;
  @override
  String? get roleId;
  @override
  bool get isActive;
  @override
  List<String> get skillIds;
  @override
  @JsonKey(ignore: true)
  _$$AIAgentConfigCreateImplCopyWith<_$AIAgentConfigCreateImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

AIAgentConfigUpdate _$AIAgentConfigUpdateFromJson(Map<String, dynamic> json) {
  return _AIAgentConfigUpdate.fromJson(json);
}

/// @nodoc
mixin _$AIAgentConfigUpdate {
  String? get name => throw _privateConstructorUsedError;
  String? get label => throw _privateConstructorUsedError;
  String? get description => throw _privateConstructorUsedError;
  String? get icon => throw _privateConstructorUsedError;
  String? get systemPrompt => throw _privateConstructorUsedError;
  String? get providerType => throw _privateConstructorUsedError;
  String? get modelName => throw _privateConstructorUsedError;
  String? get modelConfiguration => throw _privateConstructorUsedError;
  String? get responseFormat => throw _privateConstructorUsedError;
  String? get roleId => throw _privateConstructorUsedError;
  bool? get isActive => throw _privateConstructorUsedError;
  List<String>? get skillIds => throw _privateConstructorUsedError;

  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;
  @JsonKey(ignore: true)
  $AIAgentConfigUpdateCopyWith<AIAgentConfigUpdate> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $AIAgentConfigUpdateCopyWith<$Res> {
  factory $AIAgentConfigUpdateCopyWith(
          AIAgentConfigUpdate value, $Res Function(AIAgentConfigUpdate) then) =
      _$AIAgentConfigUpdateCopyWithImpl<$Res, AIAgentConfigUpdate>;
  @useResult
  $Res call(
      {String? name,
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
      List<String>? skillIds});
}

/// @nodoc
class _$AIAgentConfigUpdateCopyWithImpl<$Res, $Val extends AIAgentConfigUpdate>
    implements $AIAgentConfigUpdateCopyWith<$Res> {
  _$AIAgentConfigUpdateCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? name = freezed,
    Object? label = freezed,
    Object? description = freezed,
    Object? icon = freezed,
    Object? systemPrompt = freezed,
    Object? providerType = freezed,
    Object? modelName = freezed,
    Object? modelConfiguration = freezed,
    Object? responseFormat = freezed,
    Object? roleId = freezed,
    Object? isActive = freezed,
    Object? skillIds = freezed,
  }) {
    return _then(_value.copyWith(
      name: freezed == name
          ? _value.name
          : name // ignore: cast_nullable_to_non_nullable
              as String?,
      label: freezed == label
          ? _value.label
          : label // ignore: cast_nullable_to_non_nullable
              as String?,
      description: freezed == description
          ? _value.description
          : description // ignore: cast_nullable_to_non_nullable
              as String?,
      icon: freezed == icon
          ? _value.icon
          : icon // ignore: cast_nullable_to_non_nullable
              as String?,
      systemPrompt: freezed == systemPrompt
          ? _value.systemPrompt
          : systemPrompt // ignore: cast_nullable_to_non_nullable
              as String?,
      providerType: freezed == providerType
          ? _value.providerType
          : providerType // ignore: cast_nullable_to_non_nullable
              as String?,
      modelName: freezed == modelName
          ? _value.modelName
          : modelName // ignore: cast_nullable_to_non_nullable
              as String?,
      modelConfiguration: freezed == modelConfiguration
          ? _value.modelConfiguration
          : modelConfiguration // ignore: cast_nullable_to_non_nullable
              as String?,
      responseFormat: freezed == responseFormat
          ? _value.responseFormat
          : responseFormat // ignore: cast_nullable_to_non_nullable
              as String?,
      roleId: freezed == roleId
          ? _value.roleId
          : roleId // ignore: cast_nullable_to_non_nullable
              as String?,
      isActive: freezed == isActive
          ? _value.isActive
          : isActive // ignore: cast_nullable_to_non_nullable
              as bool?,
      skillIds: freezed == skillIds
          ? _value.skillIds
          : skillIds // ignore: cast_nullable_to_non_nullable
              as List<String>?,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$AIAgentConfigUpdateImplCopyWith<$Res>
    implements $AIAgentConfigUpdateCopyWith<$Res> {
  factory _$$AIAgentConfigUpdateImplCopyWith(_$AIAgentConfigUpdateImpl value,
          $Res Function(_$AIAgentConfigUpdateImpl) then) =
      __$$AIAgentConfigUpdateImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {String? name,
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
      List<String>? skillIds});
}

/// @nodoc
class __$$AIAgentConfigUpdateImplCopyWithImpl<$Res>
    extends _$AIAgentConfigUpdateCopyWithImpl<$Res, _$AIAgentConfigUpdateImpl>
    implements _$$AIAgentConfigUpdateImplCopyWith<$Res> {
  __$$AIAgentConfigUpdateImplCopyWithImpl(_$AIAgentConfigUpdateImpl _value,
      $Res Function(_$AIAgentConfigUpdateImpl) _then)
      : super(_value, _then);

  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? name = freezed,
    Object? label = freezed,
    Object? description = freezed,
    Object? icon = freezed,
    Object? systemPrompt = freezed,
    Object? providerType = freezed,
    Object? modelName = freezed,
    Object? modelConfiguration = freezed,
    Object? responseFormat = freezed,
    Object? roleId = freezed,
    Object? isActive = freezed,
    Object? skillIds = freezed,
  }) {
    return _then(_$AIAgentConfigUpdateImpl(
      name: freezed == name
          ? _value.name
          : name // ignore: cast_nullable_to_non_nullable
              as String?,
      label: freezed == label
          ? _value.label
          : label // ignore: cast_nullable_to_non_nullable
              as String?,
      description: freezed == description
          ? _value.description
          : description // ignore: cast_nullable_to_non_nullable
              as String?,
      icon: freezed == icon
          ? _value.icon
          : icon // ignore: cast_nullable_to_non_nullable
              as String?,
      systemPrompt: freezed == systemPrompt
          ? _value.systemPrompt
          : systemPrompt // ignore: cast_nullable_to_non_nullable
              as String?,
      providerType: freezed == providerType
          ? _value.providerType
          : providerType // ignore: cast_nullable_to_non_nullable
              as String?,
      modelName: freezed == modelName
          ? _value.modelName
          : modelName // ignore: cast_nullable_to_non_nullable
              as String?,
      modelConfiguration: freezed == modelConfiguration
          ? _value.modelConfiguration
          : modelConfiguration // ignore: cast_nullable_to_non_nullable
              as String?,
      responseFormat: freezed == responseFormat
          ? _value.responseFormat
          : responseFormat // ignore: cast_nullable_to_non_nullable
              as String?,
      roleId: freezed == roleId
          ? _value.roleId
          : roleId // ignore: cast_nullable_to_non_nullable
              as String?,
      isActive: freezed == isActive
          ? _value.isActive
          : isActive // ignore: cast_nullable_to_non_nullable
              as bool?,
      skillIds: freezed == skillIds
          ? _value._skillIds
          : skillIds // ignore: cast_nullable_to_non_nullable
              as List<String>?,
    ));
  }
}

/// @nodoc

@JsonSerializable(fieldRename: FieldRename.snake)
class _$AIAgentConfigUpdateImpl implements _AIAgentConfigUpdate {
  const _$AIAgentConfigUpdateImpl(
      {this.name,
      this.label,
      this.description,
      this.icon,
      this.systemPrompt,
      this.providerType,
      this.modelName,
      this.modelConfiguration,
      this.responseFormat,
      this.roleId,
      this.isActive,
      final List<String>? skillIds})
      : _skillIds = skillIds;

  factory _$AIAgentConfigUpdateImpl.fromJson(Map<String, dynamic> json) =>
      _$$AIAgentConfigUpdateImplFromJson(json);

  @override
  final String? name;
  @override
  final String? label;
  @override
  final String? description;
  @override
  final String? icon;
  @override
  final String? systemPrompt;
  @override
  final String? providerType;
  @override
  final String? modelName;
  @override
  final String? modelConfiguration;
  @override
  final String? responseFormat;
  @override
  final String? roleId;
  @override
  final bool? isActive;
  final List<String>? _skillIds;
  @override
  List<String>? get skillIds {
    final value = _skillIds;
    if (value == null) return null;
    if (_skillIds is EqualUnmodifiableListView) return _skillIds;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableListView(value);
  }

  @override
  String toString() {
    return 'AIAgentConfigUpdate(name: $name, label: $label, description: $description, icon: $icon, systemPrompt: $systemPrompt, providerType: $providerType, modelName: $modelName, modelConfiguration: $modelConfiguration, responseFormat: $responseFormat, roleId: $roleId, isActive: $isActive, skillIds: $skillIds)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$AIAgentConfigUpdateImpl &&
            (identical(other.name, name) || other.name == name) &&
            (identical(other.label, label) || other.label == label) &&
            (identical(other.description, description) ||
                other.description == description) &&
            (identical(other.icon, icon) || other.icon == icon) &&
            (identical(other.systemPrompt, systemPrompt) ||
                other.systemPrompt == systemPrompt) &&
            (identical(other.providerType, providerType) ||
                other.providerType == providerType) &&
            (identical(other.modelName, modelName) ||
                other.modelName == modelName) &&
            (identical(other.modelConfiguration, modelConfiguration) ||
                other.modelConfiguration == modelConfiguration) &&
            (identical(other.responseFormat, responseFormat) ||
                other.responseFormat == responseFormat) &&
            (identical(other.roleId, roleId) || other.roleId == roleId) &&
            (identical(other.isActive, isActive) ||
                other.isActive == isActive) &&
            const DeepCollectionEquality().equals(other._skillIds, _skillIds));
  }

  @JsonKey(ignore: true)
  @override
  int get hashCode => Object.hash(
      runtimeType,
      name,
      label,
      description,
      icon,
      systemPrompt,
      providerType,
      modelName,
      modelConfiguration,
      responseFormat,
      roleId,
      isActive,
      const DeepCollectionEquality().hash(_skillIds));

  @JsonKey(ignore: true)
  @override
  @pragma('vm:prefer-inline')
  _$$AIAgentConfigUpdateImplCopyWith<_$AIAgentConfigUpdateImpl> get copyWith =>
      __$$AIAgentConfigUpdateImplCopyWithImpl<_$AIAgentConfigUpdateImpl>(
          this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$AIAgentConfigUpdateImplToJson(
      this,
    );
  }
}

abstract class _AIAgentConfigUpdate implements AIAgentConfigUpdate {
  const factory _AIAgentConfigUpdate(
      {final String? name,
      final String? label,
      final String? description,
      final String? icon,
      final String? systemPrompt,
      final String? providerType,
      final String? modelName,
      final String? modelConfiguration,
      final String? responseFormat,
      final String? roleId,
      final bool? isActive,
      final List<String>? skillIds}) = _$AIAgentConfigUpdateImpl;

  factory _AIAgentConfigUpdate.fromJson(Map<String, dynamic> json) =
      _$AIAgentConfigUpdateImpl.fromJson;

  @override
  String? get name;
  @override
  String? get label;
  @override
  String? get description;
  @override
  String? get icon;
  @override
  String? get systemPrompt;
  @override
  String? get providerType;
  @override
  String? get modelName;
  @override
  String? get modelConfiguration;
  @override
  String? get responseFormat;
  @override
  String? get roleId;
  @override
  bool? get isActive;
  @override
  List<String>? get skillIds;
  @override
  @JsonKey(ignore: true)
  _$$AIAgentConfigUpdateImplCopyWith<_$AIAgentConfigUpdateImpl> get copyWith =>
      throw _privateConstructorUsedError;
}
