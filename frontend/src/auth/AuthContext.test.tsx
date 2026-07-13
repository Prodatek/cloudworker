import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "./AuthContext";
import { api } from "../api/client";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    api: { POST: vi.fn(), GET: vi.fn() },
  };
});

function wrapper({ children }: { children: React.ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>;
}

beforeEach(() => {
  localStorage.clear();
  vi.mocked(api.POST).mockReset();
});

describe("AuthContext", () => {
  it("starts unauthenticated with no stored token", () => {
    const { result } = renderHook(() => useAuth(), { wrapper });

    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.user).toBeNull();
  });

  it("login stores the token and marks the user authenticated", async () => {
    vi.mocked(api.POST).mockResolvedValueOnce({
      data: { access_token: "jwt-token", token_type: "bearer", user_id: "u1", email: "a@b.com" },
      error: undefined,
      response: new Response(),
    } as never);
    const { result } = renderHook(() => useAuth(), { wrapper });

    await act(async () => {
      await result.current.login("a@b.com", "password");
    });

    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.user).toEqual({ userId: "u1", email: "a@b.com" });
    expect(localStorage.getItem("cloudworker.token")).toBe("jwt-token");
  });

  it("login throws and stays unauthenticated on invalid credentials", async () => {
    vi.mocked(api.POST).mockResolvedValueOnce({
      data: undefined,
      error: { detail: "Invalid credentials" },
      response: new Response(null, { status: 401 }),
    } as never);
    const { result } = renderHook(() => useAuth(), { wrapper });

    await expect(
      act(async () => {
        await result.current.login("a@b.com", "wrong");
      }),
    ).rejects.toThrow();
    expect(result.current.isAuthenticated).toBe(false);
  });

  it("logout clears the stored token and user", async () => {
    vi.mocked(api.POST).mockResolvedValueOnce({
      data: { access_token: "jwt-token", token_type: "bearer", user_id: "u1", email: "a@b.com" },
      error: undefined,
      response: new Response(),
    } as never);
    const { result } = renderHook(() => useAuth(), { wrapper });
    await act(async () => {
      await result.current.login("a@b.com", "password");
    });

    act(() => {
      result.current.logout();
    });

    expect(result.current.isAuthenticated).toBe(false);
    expect(localStorage.getItem("cloudworker.token")).toBeNull();
  });

  it("register calls register then logs in automatically", async () => {
    vi.mocked(api.POST)
      .mockResolvedValueOnce({
        data: { user_id: "u2", email: "c@d.com", api_key: "cw_live_x" },
        error: undefined,
        response: new Response(),
      } as never)
      .mockResolvedValueOnce({
        data: { access_token: "jwt-token-2", token_type: "bearer", user_id: "u2", email: "c@d.com" },
        error: undefined,
        response: new Response(),
      } as never);
    const { result } = renderHook(() => useAuth(), { wrapper });

    await act(async () => {
      await result.current.register("c@d.com", "password123");
    });

    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));
    expect(api.POST).toHaveBeenCalledTimes(2);
  });
});
