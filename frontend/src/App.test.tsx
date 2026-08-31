import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Protected, RoleRoute } from "./App";
import { useAuth } from "./auth/AuthContext";
import { navigationForRole } from "./components/Shell";

vi.mock("./auth/AuthContext", () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => children,
  useAuth: vi.fn(),
}));

const mockedUseAuth = vi.mocked(useAuth);

describe("authorization routes", () => {
  beforeEach(() => mockedUseAuth.mockReset());

  it("redirects an unauthenticated user away from a protected route", () => {
    mockedUseAuth.mockReturnValue({ user: null, loading: false, login: vi.fn(), logout: vi.fn(), hasPermission: vi.fn() });
    render(<MemoryRouter initialEntries={["/tickets"]}><Routes>
      <Route path="/login" element={<div>Login destination</div>} />
      <Route path="/*" element={<Protected />} />
    </Routes></MemoryRouter>);
    expect(screen.getByText("Login destination")).toBeTruthy();
  });

  it("denies a customer access to a reviewer-only route", () => {
    mockedUseAuth.mockReturnValue({
      user: { id: "1", email: "customer@example.test", full_name: "Customer", role: "customer", department_id: null, tenant_id: "tenant", permissions: [] },
      loading: false, login: vi.fn(), logout: vi.fn(), hasPermission: vi.fn(),
    });
    render(<RoleRoute roles={["reviewer"]}><div>Reviewer module</div></RoleRoute>);
    expect(screen.getByText("Access denied")).toBeTruthy();
  });
});

describe("role-gated navigation", () => {
  it.each([
    ["customer", "/tickets", "/audit"],
    ["support_agent", "/queue", "/admin"],
    ["reviewer", "/review", "/integrations"],
    ["knowledge_manager", "/knowledge", "/audit"],
    ["team_lead", "/operations", "/admin"],
    ["system_admin", "/admin", "/review"],
    ["auditor", "/audit", "/tickets"],
  ])("gives %s the expected module", (role, expectedPath, forbiddenPath) => {
    const paths = navigationForRole(role).map(([path]) => path);
    expect(paths).toContain(expectedPath);
    expect(paths).not.toContain(forbiddenPath);
  });
});
