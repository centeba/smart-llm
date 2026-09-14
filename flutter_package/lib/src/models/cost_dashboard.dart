/// AI usage cost dashboard (`GET /api/v1/ai-usage/cost-dashboard`).
///
/// Hand-written (not freezed) because the payload is provider-dependent and
/// loosely shaped; parsing is lenient so unknown/missing fields never throw.
class CostDashboard {
  const CostDashboard({
    this.totalCostUsd,
    this.budgetUsd,
    this.window,
    this.byModel = const {},
    this.byCompany = const {},
  });

  final double? totalCostUsd;
  final double? budgetUsd;
  final String? window;
  final Map<String, double> byModel;
  final Map<String, double> byCompany;

  double? get remainingUsd => (budgetUsd != null && totalCostUsd != null)
      ? budgetUsd! - totalCostUsd!
      : null;

  static double? _num(dynamic v) => v is num ? v.toDouble() : null;

  static Map<String, double> _map(dynamic v) {
    if (v is Map) {
      return v.map(
        (k, val) => MapEntry(k.toString(), val is num ? val.toDouble() : 0.0),
      );
    }
    return const {};
  }

  factory CostDashboard.fromJson(Map<String, dynamic> json) => CostDashboard(
        totalCostUsd: _num(json['total_cost_usd']),
        budgetUsd: _num(json['budget_usd']),
        window: json['window'] as String?,
        byModel: _map(json['by_model']),
        byCompany: _map(json['by_company']),
      );
}
