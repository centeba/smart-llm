import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../i18n/translate.dart';
import '../models/ai_agent_config.dart';
import '../models/ai_skill.dart';
import '../services/ai_agents_service.dart';
import '../theme/smart_llm_colors.dart';

class AgentDetailScreen extends ConsumerStatefulWidget {
  final String? configId;
  const AgentDetailScreen({super.key, this.configId});

  @override
  ConsumerState<AgentDetailScreen> createState() => _AgentDetailScreenState();
}

class _AgentDetailScreenState extends ConsumerState<AgentDetailScreen> {
  final _nameCtrl = TextEditingController();
  final _labelCtrl = TextEditingController();
  final _descCtrl = TextEditingController();
  final _promptCtrl = TextEditingController();
  final _modelCtrl = TextEditingController();
  final _configCtrl = TextEditingController();
  String _provider = 'openai';
  String _format = 'text';
  bool _isActive = true;
  List<String> _selectedSkillIds = [];
  List<AISkillPublic> _availableSkills = [];
  bool _loading = true;
  bool _saving = false;

  bool get _isEdit => widget.configId != null;

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  Future<void> _loadData() async {
    final svc = ref.read(aiAgentsServiceProvider);
    try {
      final skills = await svc.listSkills(limit: 200);
      _availableSkills = skills.data;

      if (_isEdit) {
        final config = await svc.getConfig(widget.configId!);
        _nameCtrl.text = config.name;
        _labelCtrl.text = config.label ?? '';
        _descCtrl.text = config.description ?? '';
        _promptCtrl.text = config.systemPrompt ?? '';
        _modelCtrl.text = config.modelName ?? '';
        _configCtrl.text = config.modelConfiguration ?? '';
        _provider = config.providerType;
        _format = config.responseFormat;
        _isActive = config.isActive;
        _selectedSkillIds = config.skills.map((s) => s.id).toList();
      }
    } catch (_) {}
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _save() async {
    if (_nameCtrl.text.isEmpty) return;
    setState(() => _saving = true);
    final svc = ref.read(aiAgentsServiceProvider);
    try {
      if (_isEdit) {
        await svc.updateConfig(
          widget.configId!,
          AIAgentConfigUpdate(
            name: _nameCtrl.text,
            label: _labelCtrl.text.isEmpty ? null : _labelCtrl.text,
            description: _descCtrl.text.isEmpty ? null : _descCtrl.text,
            systemPrompt: _promptCtrl.text.isEmpty ? null : _promptCtrl.text,
            providerType: _provider,
            modelName: _modelCtrl.text.isEmpty ? null : _modelCtrl.text,
            modelConfiguration:
                _configCtrl.text.isEmpty ? null : _configCtrl.text,
            responseFormat: _format,
            isActive: _isActive,
            skillIds: _selectedSkillIds,
          ),
        );
      } else {
        await svc.createConfig(AIAgentConfigCreate(
          name: _nameCtrl.text,
          label: _labelCtrl.text.isEmpty ? null : _labelCtrl.text,
          description: _descCtrl.text.isEmpty ? null : _descCtrl.text,
          systemPrompt: _promptCtrl.text.isEmpty ? null : _promptCtrl.text,
          providerType: _provider,
          modelName: _modelCtrl.text.isEmpty ? null : _modelCtrl.text,
          modelConfiguration:
              _configCtrl.text.isEmpty ? null : _configCtrl.text,
          responseFormat: _format,
          isActive: _isActive,
          skillIds: _selectedSkillIds,
        ));
      }
      if (mounted) context.go('/ai-agents');
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(context.tr('ai_agents.create_failed'))),
        );
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  void dispose() {
    _nameCtrl.dispose();
    _labelCtrl.dispose();
    _descCtrl.dispose();
    _promptCtrl.dispose();
    _modelCtrl.dispose();
    _configCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }

    return Scaffold(
      backgroundColor: SmartLlmColors.bgPage,
      appBar: AppBar(
        title: Text(_isEdit
            ? context.tr('ai_agents.edit_agent')
            : context.tr('ai_agents.create_agent')),
        actions: [
          TextButton(
            onPressed: _saving ? null : _save,
            child: _saving
                ? const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2))
                : Text(context.tr('common.save')),
          ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _field(context.tr('ai_agents.agent_name'), _nameCtrl),
            _field(context.tr('ai_agents.label'), _labelCtrl),
            _field(context.tr('ai_agents.description'), _descCtrl, maxLines: 2),
            _field(context.tr('ai_agents.system_prompt'), _promptCtrl,
                maxLines: 6, hint: context.tr('ai_agents.system_prompt_hint')),
            const SizedBox(height: 12),
            Text(context.tr('ai_agents.provider'),
                style: const TextStyle(fontWeight: FontWeight.w600)),
            const SizedBox(height: 4),
            DropdownButtonFormField<String>(
              initialValue: _provider,
              items: const [
                DropdownMenuItem(value: 'openai', child: Text('OpenAI')),
                DropdownMenuItem(value: 'anthropic', child: Text('Anthropic')),
                DropdownMenuItem(value: 'gemini', child: Text('Gemini')),
              ],
              onChanged: (v) => setState(() => _provider = v!),
              decoration: InputDecoration(
                border:
                    OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
                filled: true,
                fillColor: SmartLlmColors.bgSurface,
              ),
            ),
            const SizedBox(height: 12),
            _field(context.tr('ai_agents.model_name'), _modelCtrl),
            _field(context.tr('ai_agents.model_config'), _configCtrl,
                maxLines: 3),
            const SizedBox(height: 12),
            Text(context.tr('ai_agents.response_format'),
                style: const TextStyle(fontWeight: FontWeight.w600)),
            const SizedBox(height: 4),
            DropdownButtonFormField<String>(
              initialValue: _format,
              items: const [
                DropdownMenuItem(value: 'text', child: Text('Text')),
                DropdownMenuItem(value: 'json', child: Text('JSON')),
              ],
              onChanged: (v) => setState(() => _format = v!),
              decoration: InputDecoration(
                border:
                    OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
                filled: true,
                fillColor: SmartLlmColors.bgSurface,
              ),
            ),
            const SizedBox(height: 12),
            SwitchListTile(
              title: Text(context.tr('ai_agents.active')),
              value: _isActive,
              onChanged: (v) => setState(() => _isActive = v),
            ),
            const SizedBox(height: 12),
            Text(context.tr('ai_agents.skills'),
                style: const TextStyle(fontWeight: FontWeight.w600)),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 4,
              children: _availableSkills.map((skill) {
                final selected = _selectedSkillIds.contains(skill.id);
                return FilterChip(
                  label: Text(skill.label ?? skill.name),
                  selected: selected,
                  onSelected: (v) => setState(() {
                    if (v) {
                      _selectedSkillIds.add(skill.id);
                    } else {
                      _selectedSkillIds.remove(skill.id);
                    }
                  }),
                );
              }).toList(),
            ),
          ],
        ),
      ),
    );
  }

  Widget _field(String label, TextEditingController ctrl,
      {int maxLines = 1, String? hint}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: TextField(
        controller: ctrl,
        maxLines: maxLines,
        decoration: InputDecoration(
          labelText: label,
          hintText: hint,
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
          filled: true,
          fillColor: SmartLlmColors.bgSurface,
        ),
      ),
    );
  }
}
