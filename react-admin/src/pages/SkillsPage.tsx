import { api } from "../api";
import { useResource } from "../useResource";
import { Async } from "../ui";

export function SkillsPage() {
  const state = useResource(api.skills);
  return (
    <>
      <h1>Skills</h1>
      <p className="muted">Tools / skills available to agents.</p>
      <Async state={state}>
        {(page) => (
          <table>
            <thead>
              <tr><th>Name</th><th>Description</th></tr>
            </thead>
            <tbody>
              {page.data.map((s) => (
                <tr key={s.id}>
                  <td>{s.label || s.name}</td>
                  <td className="muted">{s.description || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Async>
    </>
  );
}
