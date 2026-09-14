import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../i18n/translate.dart';
import '../models/ai_agent_config.dart';
import '../services/ai_agents_service.dart';
import '../theme/smart_llm_colors.dart';
import '../widgets/pagination_controls.dart';

final _agentsProvider = FutureProvider.autoDispose
    .family<AIAgentConfigsPublic, ({int skip, int limit, String? search})>(
  (ref, params) => ref
      .watch(aiAgentsServiceProvider)
      .listConfigs(skip: params.skip, limit: params.limit, search: params.search),
);

class AgentsScreen extends ConsumerStatefulWidget {
  const AgentsScreen({super.key});

  @override
  ConsumerState<AgentsScreen> createState() => _AgentsScreenState();
}

class _AgentsScreenState extends ConsumerState<AgentsScreen> {
  int _page = 0;
  final int _limit = 20;
  String? _search;

  @override
  Widget build(BuildContext context) {
    final data = ref.watch(
      _agentsProvider((skip: _page * _limit, limit: _limit, search: _search)),
    );

    return Scaffold(
      backgroundColor: SmartLlmColors.bgPage,
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: TextField(
              decoration: InputDecoration(
                hintText: context.tr('ai_agents.search_hint'),
                prefixIcon: const Icon(Icons.search, size: 20),
                filled: true,
                fillColor: SmartLlmColors.bgSurface,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                  borderSide: BorderSide(color: SmartLlmColors.borderSubtle),
                ),
              ),
              onChanged: (v) => setState(() {
                _search = v.isEmpty ? null : v;
                _page = 0;
              }),
            ),
          ),
          Expanded(
            child: data.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (e, _) => Center(child: Text('$e')),
              data: (result) {
                if (result.data.isEmpty) {
                  return Center(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(Icons.smart_toy_outlined,
                            size: 48, color: Colors.grey),
                        const SizedBox(height: 12),
                        Text(context.tr('ai_agents.no_agents'),
                            style: const TextStyle(fontSize: 16)),
                        const SizedBox(height: 4),
                        Text(context.tr('ai_agents.no_agents_subtitle'),
                            style: TextStyle(color: SmartLlmColors.textMuted)),
                      ],
                    ),
                  );
                }
                return ListView.builder(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  itemCount: result.data.length,
                  itemBuilder: (_, i) =>
                      _AgentCard(config: result.data[i]),
                );
              },
            ),
          ),
          data.whenData((d) => PaginationControls(
                currentPage: _page,
                pageSize: _limit,
                totalCount: d.count,
                onPageChanged: (p) => setState(() => _page = p),
              )).value ??
              const SizedBox.shrink(),
        ],
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: () => context.go('/ai-agents/new'),
        child: const Icon(Icons.add),
      ),
    );
  }
}

class _AgentCard extends StatelessWidget {
  final AIAgentConfigPublic config;
  const _AgentCard({required this.config});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        color: SmartLlmColors.bgSurface,
        border: Border.all(color: SmartLlmColors.borderSubtle),
        borderRadius: BorderRadius.circular(10),
      ),
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: _providerColor(config.providerType),
          child: const Icon(Icons.smart_toy, color: Colors.white, size: 20),
        ),
        title: Text(config.label ?? config.name,
            style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Text(
          '${config.providerType} · ${config.modelName ?? 'default'} · '
          '${config.skills.length} skills',
          style: TextStyle(color: SmartLlmColors.textMuted, fontSize: 12),
        ),
        trailing: config.isActive
            ? const Icon(Icons.check_circle, color: Colors.green, size: 18)
            : const Icon(Icons.pause_circle, color: Colors.orange, size: 18),
        onTap: () => context.go('/ai-agents/${config.id}'),
      ),
    );
  }

  Color _providerColor(String provider) {
    switch (provider) {
      case 'openai':
        return const Color(0xFF10A37F);
      case 'anthropic':
        return const Color(0xFFD4A574);
      case 'gemini':
        return const Color(0xFF4285F4);
      default:
        return Colors.grey;
    }
  }
}
