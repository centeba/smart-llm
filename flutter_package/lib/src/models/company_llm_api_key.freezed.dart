// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'company_llm_api_key.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

T _$identity<T>(T value) => value;

final _privateConstructorUsedError = UnsupportedError(
    'It seems like you constructed your class using `MyClass._()`. This constructor is only meant to be used by freezed and you are not supposed to need it nor use it.\nPlease check the documentation here for more information: https://github.com/rrousselGit/freezed#adding-getters-and-methods-to-our-models');

CompanyLLMApiKeyPublic _$CompanyLLMApiKeyPublicFromJson(
    Map<String, dynamic> json) {
  return _CompanyLLMApiKeyPublic.fromJson(json);
}

/// @nodoc
mixin _$CompanyLLMApiKeyPublic {
  String get id => throw _privateConstructorUsedError;
  String get companyId => throw _privateConstructorUsedError;
  String get provider => throw _privateConstructorUsedError;
  bool get isActive => throw _privateConstructorUsedError;
  DateTime? get createdAt => throw _privateConstructorUsedError;

  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;
  @JsonKey(ignore: true)
  $CompanyLLMApiKeyPublicCopyWith<CompanyLLMApiKeyPublic> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $CompanyLLMApiKeyPublicCopyWith<$Res> {
  factory $CompanyLLMApiKeyPublicCopyWith(CompanyLLMApiKeyPublic value,
          $Res Function(CompanyLLMApiKeyPublic) then) =
      _$CompanyLLMApiKeyPublicCopyWithImpl<$Res, CompanyLLMApiKeyPublic>;
  @useResult
  $Res call(
      {String id,
      String companyId,
      String provider,
      bool isActive,
      DateTime? createdAt});
}

/// @nodoc
class _$CompanyLLMApiKeyPublicCopyWithImpl<$Res,
        $Val extends CompanyLLMApiKeyPublic>
    implements $CompanyLLMApiKeyPublicCopyWith<$Res> {
  _$CompanyLLMApiKeyPublicCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? companyId = null,
    Object? provider = null,
    Object? isActive = null,
    Object? createdAt = freezed,
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
      provider: null == provider
          ? _value.provider
          : provider // ignore: cast_nullable_to_non_nullable
              as String,
      isActive: null == isActive
          ? _value.isActive
          : isActive // ignore: cast_nullable_to_non_nullable
              as bool,
      createdAt: freezed == createdAt
          ? _value.createdAt
          : createdAt // ignore: cast_nullable_to_non_nullable
              as DateTime?,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$CompanyLLMApiKeyPublicImplCopyWith<$Res>
    implements $CompanyLLMApiKeyPublicCopyWith<$Res> {
  factory _$$CompanyLLMApiKeyPublicImplCopyWith(
          _$CompanyLLMApiKeyPublicImpl value,
          $Res Function(_$CompanyLLMApiKeyPublicImpl) then) =
      __$$CompanyLLMApiKeyPublicImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {String id,
      String companyId,
      String provider,
      bool isActive,
      DateTime? createdAt});
}

/// @nodoc
class __$$CompanyLLMApiKeyPublicImplCopyWithImpl<$Res>
    extends _$CompanyLLMApiKeyPublicCopyWithImpl<$Res,
        _$CompanyLLMApiKeyPublicImpl>
    implements _$$CompanyLLMApiKeyPublicImplCopyWith<$Res> {
  __$$CompanyLLMApiKeyPublicImplCopyWithImpl(
      _$CompanyLLMApiKeyPublicImpl _value,
      $Res Function(_$CompanyLLMApiKeyPublicImpl) _then)
      : super(_value, _then);

  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? companyId = null,
    Object? provider = null,
    Object? isActive = null,
    Object? createdAt = freezed,
  }) {
    return _then(_$CompanyLLMApiKeyPublicImpl(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      companyId: null == companyId
          ? _value.companyId
          : companyId // ignore: cast_nullable_to_non_nullable
              as String,
      provider: null == provider
          ? _value.provider
          : provider // ignore: cast_nullable_to_non_nullable
              as String,
      isActive: null == isActive
          ? _value.isActive
          : isActive // ignore: cast_nullable_to_non_nullable
              as bool,
      createdAt: freezed == createdAt
          ? _value.createdAt
          : createdAt // ignore: cast_nullable_to_non_nullable
              as DateTime?,
    ));
  }
}

/// @nodoc

@JsonSerializable(fieldRename: FieldRename.snake)
class _$CompanyLLMApiKeyPublicImpl implements _CompanyLLMApiKeyPublic {
  const _$CompanyLLMApiKeyPublicImpl(
      {required this.id,
      required this.companyId,
      required this.provider,
      this.isActive = true,
      this.createdAt});

  factory _$CompanyLLMApiKeyPublicImpl.fromJson(Map<String, dynamic> json) =>
      _$$CompanyLLMApiKeyPublicImplFromJson(json);

  @override
  final String id;
  @override
  final String companyId;
  @override
  final String provider;
  @override
  @JsonKey()
  final bool isActive;
  @override
  final DateTime? createdAt;

  @override
  String toString() {
    return 'CompanyLLMApiKeyPublic(id: $id, companyId: $companyId, provider: $provider, isActive: $isActive, createdAt: $createdAt)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$CompanyLLMApiKeyPublicImpl &&
            (identical(other.id, id) || other.id == id) &&
            (identical(other.companyId, companyId) ||
                other.companyId == companyId) &&
            (identical(other.provider, provider) ||
                other.provider == provider) &&
            (identical(other.isActive, isActive) ||
                other.isActive == isActive) &&
            (identical(other.createdAt, createdAt) ||
                other.createdAt == createdAt));
  }

  @JsonKey(ignore: true)
  @override
  int get hashCode =>
      Object.hash(runtimeType, id, companyId, provider, isActive, createdAt);

  @JsonKey(ignore: true)
  @override
  @pragma('vm:prefer-inline')
  _$$CompanyLLMApiKeyPublicImplCopyWith<_$CompanyLLMApiKeyPublicImpl>
      get copyWith => __$$CompanyLLMApiKeyPublicImplCopyWithImpl<
          _$CompanyLLMApiKeyPublicImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$CompanyLLMApiKeyPublicImplToJson(
      this,
    );
  }
}

abstract class _CompanyLLMApiKeyPublic implements CompanyLLMApiKeyPublic {
  const factory _CompanyLLMApiKeyPublic(
      {required final String id,
      required final String companyId,
      required final String provider,
      final bool isActive,
      final DateTime? createdAt}) = _$CompanyLLMApiKeyPublicImpl;

  factory _CompanyLLMApiKeyPublic.fromJson(Map<String, dynamic> json) =
      _$CompanyLLMApiKeyPublicImpl.fromJson;

  @override
  String get id;
  @override
  String get companyId;
  @override
  String get provider;
  @override
  bool get isActive;
  @override
  DateTime? get createdAt;
  @override
  @JsonKey(ignore: true)
  _$$CompanyLLMApiKeyPublicImplCopyWith<_$CompanyLLMApiKeyPublicImpl>
      get copyWith => throw _privateConstructorUsedError;
}

CompanyLLMApiKeysPublic _$CompanyLLMApiKeysPublicFromJson(
    Map<String, dynamic> json) {
  return _CompanyLLMApiKeysPublic.fromJson(json);
}

/// @nodoc
mixin _$CompanyLLMApiKeysPublic {
  List<CompanyLLMApiKeyPublic> get data => throw _privateConstructorUsedError;
  int get count => throw _privateConstructorUsedError;

  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;
  @JsonKey(ignore: true)
  $CompanyLLMApiKeysPublicCopyWith<CompanyLLMApiKeysPublic> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $CompanyLLMApiKeysPublicCopyWith<$Res> {
  factory $CompanyLLMApiKeysPublicCopyWith(CompanyLLMApiKeysPublic value,
          $Res Function(CompanyLLMApiKeysPublic) then) =
      _$CompanyLLMApiKeysPublicCopyWithImpl<$Res, CompanyLLMApiKeysPublic>;
  @useResult
  $Res call({List<CompanyLLMApiKeyPublic> data, int count});
}

/// @nodoc
class _$CompanyLLMApiKeysPublicCopyWithImpl<$Res,
        $Val extends CompanyLLMApiKeysPublic>
    implements $CompanyLLMApiKeysPublicCopyWith<$Res> {
  _$CompanyLLMApiKeysPublicCopyWithImpl(this._value, this._then);

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
              as List<CompanyLLMApiKeyPublic>,
      count: null == count
          ? _value.count
          : count // ignore: cast_nullable_to_non_nullable
              as int,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$CompanyLLMApiKeysPublicImplCopyWith<$Res>
    implements $CompanyLLMApiKeysPublicCopyWith<$Res> {
  factory _$$CompanyLLMApiKeysPublicImplCopyWith(
          _$CompanyLLMApiKeysPublicImpl value,
          $Res Function(_$CompanyLLMApiKeysPublicImpl) then) =
      __$$CompanyLLMApiKeysPublicImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({List<CompanyLLMApiKeyPublic> data, int count});
}

/// @nodoc
class __$$CompanyLLMApiKeysPublicImplCopyWithImpl<$Res>
    extends _$CompanyLLMApiKeysPublicCopyWithImpl<$Res,
        _$CompanyLLMApiKeysPublicImpl>
    implements _$$CompanyLLMApiKeysPublicImplCopyWith<$Res> {
  __$$CompanyLLMApiKeysPublicImplCopyWithImpl(
      _$CompanyLLMApiKeysPublicImpl _value,
      $Res Function(_$CompanyLLMApiKeysPublicImpl) _then)
      : super(_value, _then);

  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? data = null,
    Object? count = null,
  }) {
    return _then(_$CompanyLLMApiKeysPublicImpl(
      data: null == data
          ? _value._data
          : data // ignore: cast_nullable_to_non_nullable
              as List<CompanyLLMApiKeyPublic>,
      count: null == count
          ? _value.count
          : count // ignore: cast_nullable_to_non_nullable
              as int,
    ));
  }
}

/// @nodoc

@JsonSerializable(fieldRename: FieldRename.snake)
class _$CompanyLLMApiKeysPublicImpl implements _CompanyLLMApiKeysPublic {
  const _$CompanyLLMApiKeysPublicImpl(
      {required final List<CompanyLLMApiKeyPublic> data, required this.count})
      : _data = data;

  factory _$CompanyLLMApiKeysPublicImpl.fromJson(Map<String, dynamic> json) =>
      _$$CompanyLLMApiKeysPublicImplFromJson(json);

  final List<CompanyLLMApiKeyPublic> _data;
  @override
  List<CompanyLLMApiKeyPublic> get data {
    if (_data is EqualUnmodifiableListView) return _data;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableListView(_data);
  }

  @override
  final int count;

  @override
  String toString() {
    return 'CompanyLLMApiKeysPublic(data: $data, count: $count)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$CompanyLLMApiKeysPublicImpl &&
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
  _$$CompanyLLMApiKeysPublicImplCopyWith<_$CompanyLLMApiKeysPublicImpl>
      get copyWith => __$$CompanyLLMApiKeysPublicImplCopyWithImpl<
          _$CompanyLLMApiKeysPublicImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$CompanyLLMApiKeysPublicImplToJson(
      this,
    );
  }
}

abstract class _CompanyLLMApiKeysPublic implements CompanyLLMApiKeysPublic {
  const factory _CompanyLLMApiKeysPublic(
      {required final List<CompanyLLMApiKeyPublic> data,
      required final int count}) = _$CompanyLLMApiKeysPublicImpl;

  factory _CompanyLLMApiKeysPublic.fromJson(Map<String, dynamic> json) =
      _$CompanyLLMApiKeysPublicImpl.fromJson;

  @override
  List<CompanyLLMApiKeyPublic> get data;
  @override
  int get count;
  @override
  @JsonKey(ignore: true)
  _$$CompanyLLMApiKeysPublicImplCopyWith<_$CompanyLLMApiKeysPublicImpl>
      get copyWith => throw _privateConstructorUsedError;
}

CompanyLLMApiKeyCreate _$CompanyLLMApiKeyCreateFromJson(
    Map<String, dynamic> json) {
  return _CompanyLLMApiKeyCreate.fromJson(json);
}

/// @nodoc
mixin _$CompanyLLMApiKeyCreate {
  String get provider => throw _privateConstructorUsedError;
  String get apiKey => throw _privateConstructorUsedError;

  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;
  @JsonKey(ignore: true)
  $CompanyLLMApiKeyCreateCopyWith<CompanyLLMApiKeyCreate> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $CompanyLLMApiKeyCreateCopyWith<$Res> {
  factory $CompanyLLMApiKeyCreateCopyWith(CompanyLLMApiKeyCreate value,
          $Res Function(CompanyLLMApiKeyCreate) then) =
      _$CompanyLLMApiKeyCreateCopyWithImpl<$Res, CompanyLLMApiKeyCreate>;
  @useResult
  $Res call({String provider, String apiKey});
}

/// @nodoc
class _$CompanyLLMApiKeyCreateCopyWithImpl<$Res,
        $Val extends CompanyLLMApiKeyCreate>
    implements $CompanyLLMApiKeyCreateCopyWith<$Res> {
  _$CompanyLLMApiKeyCreateCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? provider = null,
    Object? apiKey = null,
  }) {
    return _then(_value.copyWith(
      provider: null == provider
          ? _value.provider
          : provider // ignore: cast_nullable_to_non_nullable
              as String,
      apiKey: null == apiKey
          ? _value.apiKey
          : apiKey // ignore: cast_nullable_to_non_nullable
              as String,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$CompanyLLMApiKeyCreateImplCopyWith<$Res>
    implements $CompanyLLMApiKeyCreateCopyWith<$Res> {
  factory _$$CompanyLLMApiKeyCreateImplCopyWith(
          _$CompanyLLMApiKeyCreateImpl value,
          $Res Function(_$CompanyLLMApiKeyCreateImpl) then) =
      __$$CompanyLLMApiKeyCreateImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({String provider, String apiKey});
}

/// @nodoc
class __$$CompanyLLMApiKeyCreateImplCopyWithImpl<$Res>
    extends _$CompanyLLMApiKeyCreateCopyWithImpl<$Res,
        _$CompanyLLMApiKeyCreateImpl>
    implements _$$CompanyLLMApiKeyCreateImplCopyWith<$Res> {
  __$$CompanyLLMApiKeyCreateImplCopyWithImpl(
      _$CompanyLLMApiKeyCreateImpl _value,
      $Res Function(_$CompanyLLMApiKeyCreateImpl) _then)
      : super(_value, _then);

  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? provider = null,
    Object? apiKey = null,
  }) {
    return _then(_$CompanyLLMApiKeyCreateImpl(
      provider: null == provider
          ? _value.provider
          : provider // ignore: cast_nullable_to_non_nullable
              as String,
      apiKey: null == apiKey
          ? _value.apiKey
          : apiKey // ignore: cast_nullable_to_non_nullable
              as String,
    ));
  }
}

/// @nodoc

@JsonSerializable(fieldRename: FieldRename.snake)
class _$CompanyLLMApiKeyCreateImpl implements _CompanyLLMApiKeyCreate {
  const _$CompanyLLMApiKeyCreateImpl(
      {required this.provider, required this.apiKey});

  factory _$CompanyLLMApiKeyCreateImpl.fromJson(Map<String, dynamic> json) =>
      _$$CompanyLLMApiKeyCreateImplFromJson(json);

  @override
  final String provider;
  @override
  final String apiKey;

  @override
  String toString() {
    return 'CompanyLLMApiKeyCreate(provider: $provider, apiKey: $apiKey)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$CompanyLLMApiKeyCreateImpl &&
            (identical(other.provider, provider) ||
                other.provider == provider) &&
            (identical(other.apiKey, apiKey) || other.apiKey == apiKey));
  }

  @JsonKey(ignore: true)
  @override
  int get hashCode => Object.hash(runtimeType, provider, apiKey);

  @JsonKey(ignore: true)
  @override
  @pragma('vm:prefer-inline')
  _$$CompanyLLMApiKeyCreateImplCopyWith<_$CompanyLLMApiKeyCreateImpl>
      get copyWith => __$$CompanyLLMApiKeyCreateImplCopyWithImpl<
          _$CompanyLLMApiKeyCreateImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$CompanyLLMApiKeyCreateImplToJson(
      this,
    );
  }
}

abstract class _CompanyLLMApiKeyCreate implements CompanyLLMApiKeyCreate {
  const factory _CompanyLLMApiKeyCreate(
      {required final String provider,
      required final String apiKey}) = _$CompanyLLMApiKeyCreateImpl;

  factory _CompanyLLMApiKeyCreate.fromJson(Map<String, dynamic> json) =
      _$CompanyLLMApiKeyCreateImpl.fromJson;

  @override
  String get provider;
  @override
  String get apiKey;
  @override
  @JsonKey(ignore: true)
  _$$CompanyLLMApiKeyCreateImplCopyWith<_$CompanyLLMApiKeyCreateImpl>
      get copyWith => throw _privateConstructorUsedError;
}
