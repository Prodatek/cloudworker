import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiKeysPage } from "./ApiKeysPage";
import { api } from "../api/client";

vi.mock("../api/client", () => ({ api: { GET: vi.fn(), POST: vi.fn() } }));

const existingKey = {
  id: "key-1",
  prefix: "cw_live_abc1",
  created_at: "2026-01-01T00:00:00Z",
  last_used_at: null,
  revoked_at: null,
};

beforeEach(() => {
  vi.mocked(api.GET).mockReset();
  vi.mocked(api.POST).mockReset();
});

describe("ApiKeysPage", () => {
  it("lists existing API keys", async () => {
    vi.mocked(api.GET).mockResolvedValueOnce({
      data: { api_keys: [existingKey] },
      error: undefined,
    } as never);

    render(<ApiKeysPage />);

    expect(await screen.findByText(/cw_live_abc1/)).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("creates a new key and shows it once", async () => {
    vi.mocked(api.GET)
      .mockResolvedValueOnce({ data: { api_keys: [] }, error: undefined } as never)
      .mockResolvedValueOnce({ data: { api_keys: [existingKey] }, error: undefined } as never);
    vi.mocked(api.POST).mockResolvedValueOnce({
      data: { ...existingKey, api_key: "cw_live_abc1_full_secret" },
      error: undefined,
    } as never);
    const user = userEvent.setup();

    render(<ApiKeysPage />);
    await screen.findByText(/loading/i, {}, { timeout: 100 }).catch(() => {});
    await user.click(await screen.findByRole("button", { name: /create new api key/i }));

    expect(await screen.findByText("cw_live_abc1_full_secret")).toBeInTheDocument();
  });

  it("revokes a key and refreshes the list", async () => {
    vi.mocked(api.GET)
      .mockResolvedValueOnce({ data: { api_keys: [existingKey] }, error: undefined } as never)
      .mockResolvedValueOnce({
        data: { api_keys: [{ ...existingKey, revoked_at: "2026-01-02T00:00:00Z" }] },
        error: undefined,
      } as never);
    vi.mocked(api.POST).mockResolvedValueOnce({ data: {}, error: undefined } as never);
    const user = userEvent.setup();

    render(<ApiKeysPage />);
    await user.click(await screen.findByRole("button", { name: /revoke/i }));

    await waitFor(() => expect(screen.getByText("Revoked")).toBeInTheDocument());
  });
});
