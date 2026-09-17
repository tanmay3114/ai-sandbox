import type { ReactNode } from "react";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";

interface AppLayoutProps {
  children: ReactNode;
}

export function AppLayout({ children }: AppLayoutProps) {
  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>
      <Sidebar />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <Header />
        <main
          style={{
            flex: 1,
            padding: 24,
            overflowY: "auto",
            backgroundColor: "var(--color-background)",
          }}
        >
          {children}
        </main>
      </div>
    </div>
  );
}
