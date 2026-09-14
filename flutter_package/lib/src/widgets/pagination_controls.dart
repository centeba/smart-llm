import 'package:flutter/material.dart';

import '../i18n/translate.dart';
import '../theme/smart_llm_colors.dart';

class PaginationControls extends StatelessWidget {
  final int currentPage;
  final int totalCount;
  final int pageSize;
  final ValueChanged<int> onPageChanged;

  const PaginationControls({
    super.key,
    required this.currentPage,
    required this.totalCount,
    required this.pageSize,
    required this.onPageChanged,
  });

  int get totalPages => (totalCount / pageSize).ceil().clamp(1, 999999);

  @override
  Widget build(BuildContext context) {
    if (totalCount <= pageSize) return const SizedBox.shrink();

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          IconButton(
            icon: const Icon(Icons.chevron_left),
            color: SmartLlmColors.textMuted,
            onPressed: currentPage > 0
                ? () => onPageChanged(currentPage - 1)
                : null,
          ),
          const SizedBox(width: 8),
          Text(
            context
                .tr('pagination.page_of')
                .replaceAll('{current}', '${currentPage + 1}')
                .replaceAll('{total}', '$totalPages'),
            style: TextStyle(color: SmartLlmColors.textSecondary, fontSize: 13),
          ),
          const SizedBox(width: 8),
          IconButton(
            icon: const Icon(Icons.chevron_right),
            color: SmartLlmColors.textMuted,
            onPressed: currentPage < totalPages - 1
                ? () => onPageChanged(currentPage + 1)
                : null,
          ),
          const SizedBox(width: 16),
          Text(
            context
                .tr('pagination.total_count')
                .replaceAll('{count}', '$totalCount'),
            style: TextStyle(color: SmartLlmColors.textDim, fontSize: 12),
          ),
        ],
      ),
    );
  }
}
