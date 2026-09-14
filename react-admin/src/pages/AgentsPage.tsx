import { api } from "../api";
import { useResource } from "../useResource";
import { Active, Async } from "../ui";

export function AgentsPage() {
  const state = useResource(api.agents);
  return (
    <>
      <h1>Agents</h1>
      <p className="muted">AI agent configurations and their attached skills.</p>
      <Async state={state}>
        {(page) => (
          <table>
            <thead>
              <tr>
                <th>Name</th><th>Provider</th><th>Model</th>
                <th>Skills</th><th>Status</th>
              </tr>
            </thead>
            <tbody>
              {page.data.map((a) => (
                <tr key={a.id}>
                  <td>
                    <div>{a.label || a.name}</div>
                    {a.description && <div className="muted">{a.description}</div>}
                  </td>
                  <td>{a.provider_type}</td>
                  <td>{a.model_name ? <code>{a.model_name}</code> : "—"}</td>
                  <td>{a.skills.length}</td>
                  <td><Active on={a.is_active} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Async>
    </>
  );
}
