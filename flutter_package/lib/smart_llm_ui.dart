/// Flutter UI package for smart-llm — agent configs, skills, and LLM keys.
///
/// The host application provides an authenticated [Dio] via
/// `smartLlmDioProvider.overrideWith(...)` so these screens share the same
/// auth/role context as the rest of the app.
library smart_llm_ui;

// Models
export 'src/models/ai_agent_config.dart';
export 'src/models/ai_skill.dart';
export 'src/models/company_llm_api_key.dart';
export 'src/models/cost_dashboard.dart';

// Services / providers
export 'src/services/ai_agents_service.dart';

// Screens
export 'src/screens/agent_detail_screen.dart';
export 'src/screens/agents_screen.dart';
export 'src/screens/llm_keys_screen.dart';
export 'src/screens/skills_screen.dart';
export 'src/screens/usage_screen.dart';

// Theming (so the host app can override palette tokens)
export 'src/theme/smart_llm_colors.dart';
