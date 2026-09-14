import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../i18n/translate.dart';
import '../models/ai_skill.dart';
import '../services/ai_agents_service.dart';
import '../theme/smart_llm_colors.dart';
import '../widgets/pagination_controls.dart';

final _skillsProvider = FutureProvider.autoDispose
    .family<AISkillsPublic, ({int skip, int limit, String? search})>(
  (ref, params) => ref
      .watch(aiAgentsServiceProvider)
      .listSkills(skip: params.skip, limit: params.limit, search: params.search),
);

class SkillsScreen extends ConsumerStatefulWidget {
  const SkillsScreen({super.key});

  @override
  ConsumerState<SkillsScreen> createState() => _SkillsScreenState();
}

class _SkillsScreenState extends ConsumerState<SkillsScreen> {
  int _page = 0;
  final int _limit = 20;
  String? _search;

  void _showCreateDialog() {
    final nameCtrl = TextEditingController();
    final labelCtrl = TextEditingController();
    final contentCtrl = TextEditingController();
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(context.tr('ai_skills.create_skill')),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: nameCtrl,
                decoration: InputDecoration(
                    labelText: context.tr('ai_skills.skill_name')),
              ),
              const SizedBox(height: 8),
              TextField(
                controller: labelCtrl,
                decoration:
                    InputDecoration(labelText: context.tr('ai_skills.label')),
              ),
              const SizedBox(height: 8),
              TextField(
                controller: contentCtrl,
                maxLines: 5,
                decoration: InputDecoration(
                  labelText: context.tr('ai_skills.content'),
                  hintText: context.tr('ai_skills.content_hint'),
                ),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: Text(context.tr('common.cancel')),
          ),
          TextButton(
            onPressed: () async {
              if (nameCtrl.text.isEmpty) return;
              try {
                await ref.read(aiAgentsServiceProvider).createSkill(
                      AISkillCreate(
                        name: nameCtrl.text,
                        label:
                            labelCtrl.text.isEmpty ? null : labelCtrl.text,
                        content: contentCtrl.text.isEmpty
                            ? null
                            : contentCtrl.text,
                      ),
                    );
                if (mounted) {
                  Navigator.pop(ctx);
                  ref.invalidate(_skillsProvider);
                }
              } catch (_) {
                if (mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                        content:
                            Text(context.tr('ai_skills.create_failed'))),
                  );
                }
              }
            },
            child: Text(context.tr('common.create')),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final data = ref.watch(
        _skillsProvider((skip: _page * _limit, limit: _limit, search: _search)));

    return Scaffold(
      backgroundColor: SmartLlmColors.bgPage,
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: TextField(
              decoration: InputDecoration(
                hintText: context.tr('ai_skills.search_hint'),
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
                        const Icon(Icons.auto_fix_high_outlined,
                            size: 48, color: Colors.grey),
                        const SizedBox(height: 12),
                        Text(context.tr('ai_skills.no_skills')),
                        const SizedBox(height: 4),
                        Text(context.tr('ai_skills.no_skills_subtitle'),
                            style: TextStyle(color: SmartLlmColors.textMuted)),
                      ],
                    ),
                  );
                }
                return ListView.builder(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  itemCount: result.data.length,
                  itemBuilder: (_, i) {
                    final s = result.data[i];
                    return Container(
                      margin: const EdgeInsets.only(bottom: 8),
                      decoration: BoxDecoration(
                        color: SmartLlmColors.bgSurface,
                        border: Border.all(color: SmartLlmColors.borderSubtle),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: ListTile(
                        leading: CircleAvatar(
                          backgroundColor: SmartLlmColors.temporalBg,
                          child: const Icon(Icons.auto_fix_high,
                              color: Colors.white, size: 20),
                        ),
                        title: Text(s.label ?? s.name,
                            style:
                                const TextStyle(fontWeight: FontWeight.w600)),
                        subtitle: Text(
                          s.content != null && s.content!.length > 80
                              ? '${s.content!.substring(0, 80)}...'
                              : s.content ?? '',
                          style: TextStyle(
                              color: SmartLlmColors.textMuted, fontSize: 12),
                        ),
                        trailing: s.isActive
                            ? const Icon(Icons.check_circle,
                                color: Colors.green, size: 18)
                            : const Icon(Icons.pause_circle,
                                color: Colors.orange, size: 18),
                      ),
                    );
                  },
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
        onPressed: _showCreateDialog,
        child: const Icon(Icons.add),
      ),
    );
  }
}
