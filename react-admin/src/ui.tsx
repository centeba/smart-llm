import type { ReactNode } from "react";
import type { AsyncState } from "./useResource";

/** Renders loading / error / data states for a resource. */
export function Async<T>(props: {
  state: AsyncState<T>;
  children: (data: T) => ReactNode;
}) {
  const { state, children } = props;
  if (state.loading) return <p className="muted">Loading…</p>;
  if (state.error) return <p className="error">Error: {state.error}</p>;
  if (state.data === null) return null;
  return <>{children(state.data)}</>;
}

export function Active({ on }: { on: boolean }) {
  return <span className={`pill ${on ? "on" : "off"}`}>{on ? "active" : "inactive"}</span>;
}
