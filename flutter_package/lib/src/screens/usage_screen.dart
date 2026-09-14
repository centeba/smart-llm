import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../i18n/translate.dart';
import '../models/cost_dashboard.dart';
import '../services/ai_agents_service.dart';
import '../theme/smart_llm_colors.dart';

final _costDashboardProvider = FutureProvider.autoDispose<CostDashboard>(
  (ref) => ref.watch(aiAgentsServiceProvider).getCostDashboard(),
);

String _money(double? n) => n == null ? '—' : '\$${n.toStringAsFixed(2)}';

/// Usage & budgets — spend/budget from the AI usage cost dashboard. Web parity
/// with react-admin's UsagePage.
class UsageScreen extends ConsumerWidget {
  const UsageScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final data = ref.watch(_costDashboardProvider);

    return Scaffold(
      backgroundColor: SmartLlmColors.bgPage,
      body: data.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('$e')),
        data: (d) => RefreshIndicator(
          onRefresh: () async => ref.invalidate(_costDashboardProvider),
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Wrap(
                spacing: 12,
                runSpacing: 12,
                children: [
                  _StatCard(
                    label: d.window == null
                        ? context.tr('ai_usage.total_spend')
                        : '${context.tr('ai_usage.total_spend')} (${d.window})',
                    value: _money(d.totalCostUsd),
                  ),
                  _StatCard(
                    label: context.tr('ai_usage.budget'),
                    value: _money(d.budgetUsd),
                  ),
                  _StatCard(
                    label: context.tr('ai_usage.remaining'),
                    value: _money(d.remainingUsd),
                  ),
                ],
              ),
              if (d.byModel.isNotEmpty) ...[
                const SizedBox(height: 24),
                Text(
                  context.tr('ai_usage.by_model'),
                  style: TextStyle(
                    color: SmartLlmColors.textPrimary,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 8),
                for (final entry in d.byModel.entries)
                  Container(
                    margin: const EdgeInsets.only(bottom: 8),
                    decoration: BoxDecoration(
                      color: SmartLlmColors.bgSurface,
                      border: Border.all(color: SmartLlmColors.borderSubtle),
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: ListTile(
                      title: Text(entry.key,
                          style: TextStyle(color: SmartLlmColors.textPrimary)),
                      trailing: Text(_money(entry.value),
                          style: TextStyle(color: SmartLlmColors.textSecondary)),
                    ),
                  ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _StatCard extends StatelessWidget {
  const _StatCard({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 180,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: SmartLlmColors.bgSurface,
        border: Border.all(color: SmartLlmColors.borderSubtle),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label,
              style: TextStyle(color: SmartLlmColors.textMuted, fontSize: 12)),
          const SizedBox(height: 6),
          Text(value,
              style: TextStyle(
                color: SmartLlmColors.textPrimary,
                fontSize: 24,
                fontWeight: FontWeight.w700,
              )),
        ],
      ),
    );
  }
}
