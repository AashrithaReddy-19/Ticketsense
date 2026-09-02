import { useRef, type KeyboardEvent } from "react";

interface TabsProps {
  tabs: Array<{ key: string; label: string }>;
  active: string;
  onChange: (key: string) => void;
  idPrefix: string;
}

/** Accessible tab list: role=tablist/tab, roving tabindex, arrow-key + Home/End navigation. */
export function Tabs({ tabs, active, onChange, idPrefix }: TabsProps) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const index = tabs.findIndex(t => t.key === active);
    if (index === -1) return;
    let next = -1;
    if (e.key === "ArrowRight") next = (index + 1) % tabs.length;
    else if (e.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = tabs.length - 1;
    if (next >= 0) {
      e.preventDefault();
      const key = tabs[next].key;
      onChange(key);
      refs.current[key]?.focus();
    }
  }

  return (
    <div className="ui-tabs" role="tablist" aria-label="Ticket sections" onKeyDown={onKeyDown}>
      {tabs.map(tab => {
        const selected = tab.key === active;
        return (
          <button
            key={tab.key}
            ref={el => { refs.current[tab.key] = el; }}
            role="tab"
            id={`${idPrefix}-tab-${tab.key}`}
            aria-selected={selected}
            aria-controls={`${idPrefix}-panel-${tab.key}`}
            tabIndex={selected ? 0 : -1}
            className={selected ? "active" : ""}
            onClick={() => onChange(tab.key)}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

export function TabPanel({ id, tabKey, active, children }: { id: string; tabKey: string; active: string; children: React.ReactNode }) {
  if (tabKey !== active) return null;
  return (
    <div role="tabpanel" id={`${id}-panel-${tabKey}`} aria-labelledby={`${id}-tab-${tabKey}`} tabIndex={0}>
      {children}
    </div>
  );
}
