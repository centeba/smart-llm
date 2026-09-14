import { api } from "../api";
import { useResource } from "../useResource";
import { Active, Async } from "../ui";

export function KeysPage() {
  const state = useResource(api.keys);
  return (
    <>
      <h1>LLM Keys</h1>
      <p className="muted">Provider API keys (values are never returned by the API).</p>
      <Async state={state}>
        {(page) => (
          <table>
            <thead>
              <tr><th>Provider</th><th>Status</th><th>ID</th></tr>
            </thead>
            <tbody>
              {page.data.map((k) => (
                <tr key={k.id}>
                  <td>{k.provider}</td>
                  <td><Active on={k.is_active} /></td>
                  <td className="muted"><code>{k.id}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Async>
    </>
  );
}
