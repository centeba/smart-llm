import 'package:flutter/material.dart';

/// Private-use extension for smart_llm_ui screens to call `context.tr(key)`.
///
/// Self-contained: returns the key unchanged, so the package carries no i18n
/// backend dependency. A host app that wants real translations can register an
/// override via [SmartLlmUiL10n.translator].
extension SmartLlmUiTranslate on BuildContext {
  String tr(String key) => SmartLlmUiL10n.translator?.call(this, key) ?? key;
}

/// Optional hook: set [translator] once at startup to localize smart_llm_ui
/// strings against your app's own i18n (e.g. `(ctx, key) => myLookup(key)`).
class SmartLlmUiL10n {
  SmartLlmUiL10n._();

  static String Function(BuildContext context, String key)? translator;
}
