import { useState } from "react";
import { AgentsPage } from "./pages/AgentsPage";
import { SkillsPage } from "./pages/SkillsPage";
import { KeysPage } from "./pages/KeysPage";
import { UsagePage } from "./pages/UsagePage";

const TABS = {
  agents: { label: "Agents", el: <AgentsPage /> },
  skills: { label: "Skills", el: <SkillsPage /> },
  keys: { label: "LLM Keys", el: <KeysPage /> },
  usage: { label: "Usage & Budgets", el: <UsagePage /> },
} as const;

type TabKey = keyof typeof TABS;

export function App() {
  const [tab, setTab] = useState<TabKey>("agents");
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">smart-llm</div>
        <nav className="nav">
          {(Object.keys(TABS) as TabKey[]).map((k) => (
            <button
              key={k}
              className={k === tab ? "active" : ""}
              onClick={() => setTab(k)}
            >
              {TABS[k].label}
            </button>
          ))}
        </nav>
      </aside>
      <main className="main">{TABS[tab].el}</main>
    </div>
  );
}
