import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../i18n/translate.dart';
import '../models/company_llm_api_key.dart';
import '../services/ai_agents_service.dart';
import '../theme/smart_llm_colors.dart';

final _keysProvider = FutureProvider.autoDispose<CompanyLLMApiKeysPublic>(
  (ref) => ref.watch(aiAgentsServiceProvider).listLLMKeys(),
);

class LLMKeysScreen extends ConsumerWidget {
  const LLMKeysScreen({super.key});

  void _showAddDialog(BuildContext context, WidgetRef ref) {
    String provider = 'openai';
    final keyCtrl = TextEditingController();

    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          title: Text(context.tr('llm_keys.add_key')),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              DropdownButtonFormField<String>(
                initialValue: provider,
                items: const [
                  DropdownMenuItem(value: 'openai', child: Text('OpenAI')),
                  DropdownMenuItem(
                      value: 'anthropic', child: Text('Anthropic')),
                  DropdownMenuItem(value: 'gemini', child: Text('Gemini')),
                ],
                onChanged: (v) => setDialogState(() => provider = v!),
                decoration: InputDecoration(
                    labelText: context.tr('llm_keys.provider')),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: keyCtrl,
                obscureText: true,
                decoration: InputDecoration(
                  labelText: context.tr('llm_keys.api_key'),
                  hintText: context.tr('llm_keys.api_key_hint'),
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: Text(context.tr('common.cancel')),
            ),
            TextButton(
              onPressed: () async {
                if (keyCtrl.text.isEmpty) return;
                try {
                  await ref.read(aiAgentsServiceProvider).createLLMKey(
                        CompanyLLMApiKeyCreate(
                          provider: provider,
                          apiKey: keyCtrl.text,
                        ),
                      );
                  ref.invalidate(_keysProvider);
                  if (ctx.mounted) Navigator.pop(ctx);
                } catch (_) {}
              },
              child: Text(context.tr('common.add')),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final data = ref.watch(_keysProvider);

    return Scaffold(
      backgroundColor: SmartLlmColors.bgPage,
      appBar: AppBar(title: Text(context.tr('llm_keys.title'))),
      body: data.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('$e')),
        data: (result) {
          if (result.data.isEmpty) {
            return Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.key_outlined, size: 48, color: Colors.grey),
                  const SizedBox(height: 12),
                  Text(context.tr('llm_keys.no_keys')),
                  const SizedBox(height: 4),
                  Text(context.tr('llm_keys.no_keys_subtitle'),
                      style: TextStyle(color: SmartLlmColors.textMuted)),
                ],
              ),
            );
          }
          return ListView.builder(
            padding: const EdgeInsets.all(16),
            itemCount: result.data.length,
            itemBuilder: (_, i) {
              final key = result.data[i];
              return Container(
                margin: const EdgeInsets.only(bottom: 8),
                decoration: BoxDecoration(
                  color: SmartLlmColors.bgSurface,
                  border: Border.all(color: SmartLlmColors.borderSubtle),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: ListTile(
                  leading: const Icon(Icons.vpn_key),
                  title: Text(key.provider.toUpperCase(),
                      style: const TextStyle(fontWeight: FontWeight.w600)),
                  subtitle: Text(
                    key.isActive ? 'Active' : 'Inactive',
                    style: TextStyle(
                        color: key.isActive ? Colors.green : Colors.orange),
                  ),
                  trailing: IconButton(
                    icon: const Icon(Icons.delete_outline, color: Colors.red),
                    onPressed: () async {
                      final confirm = await showDialog<bool>(
                        context: context,
                        builder: (ctx) => AlertDialog(
                          title: Text(context.tr('llm_keys.delete_key')),
                          content: Text(
                              context.tr('llm_keys.delete_key_confirm')),
                          actions: [
                            TextButton(
                              onPressed: () => Navigator.pop(ctx, false),
                              child: Text(context.tr('common.cancel')),
                            ),
                            TextButton(
                              onPressed: () => Navigator.pop(ctx, true),
                              child: Text(context.tr('common.delete'),
                                  style:
                                      const TextStyle(color: Colors.red)),
                            ),
                          ],
                        ),
                      );
                      if (confirm == true) {
                        await ref
                            .read(aiAgentsServiceProvider)
                            .deleteLLMKey(key.id);
                        ref.invalidate(_keysProvider);
                      }
                    },
                  ),
                ),
              );
            },
          );
        },
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: () => _showAddDialog(context, ref),
        child: const Icon(Icons.add),
      ),
    );
  }
}
