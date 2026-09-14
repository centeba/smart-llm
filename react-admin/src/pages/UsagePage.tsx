import { api } from "../api";
import { useResource } from "../useResource";
import { Async } from "../ui";

function money(n: number | null | undefined): string {
  return n == null ? "—" : `$${n.toFixed(2)}`;
}

export function UsagePage() {
  const state = useResource(api.costDashboard);
  return (
    <>
      <h1>Usage & Budgets</h1>
      <p className="muted">Spend and budget from the AI usage cost dashboard.</p>
      <Async state={state}>
        {(d) => (
          <>
            <div className="cards">
              <div className="card">
                <div className="k">Total spend{d.window ? ` (${d.window})` : ""}</div>
                <div className="v">{money(d.total_cost_usd)}</div>
              </div>
              <div className="card">
                <div className="k">Budget</div>
                <div className="v">{money(d.budget_usd)}</div>
              </div>
              <div className="card">
                <div className="k">Remaining</div>
                <div className="v">
                  {d.budget_usd != null && d.total_cost_usd != null
                    ? money(d.budget_usd - d.total_cost_usd)
                    : "—"}
                </div>
              </div>
            </div>
            {d.by_model && (
              <>
                <h1 style={{ fontSize: 15, marginTop: 28 }}>By model</h1>
                <table>
                  <thead><tr><th>Model</th><th>Cost</th></tr></thead>
                  <tbody>
                    {Object.entries(d.by_model).map(([m, c]) => (
                      <tr key={m}><td><code>{m}</code></td><td>{money(c)}</td></tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </>
        )}
      </Async>
    </>
  );
}
