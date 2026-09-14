import 'package:flutter/material.dart';

/// Lightweight, self-contained color tokens used by smart_llm_ui screens.
///
/// The consuming app can override these at startup by assigning the static
/// fields (e.g. from its own theme system).  Defaults match the user-master
/// dark palette so screens look consistent out of the box.
abstract final class SmartLlmColors {
  static Color bgPage       = const Color(0xFF0B1120);
  static Color bgSurface    = const Color(0xFF1E293B);
  static Color borderSubtle = const Color(0xFF334155);

  static Color textPrimary   = const Color(0xFFE2E8F0);
  static Color textSecondary = const Color(0xFF94A3B8);
  static Color textMuted     = const Color(0xFF64748B);
  static Color textDim       = const Color(0xFF475569);

  static const temporalBg = Color(0xFF2D1B5E);
}
