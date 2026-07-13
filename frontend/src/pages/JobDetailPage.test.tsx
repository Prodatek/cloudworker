import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { JobDetailPage } from "./JobDetailPage";
import { api } from "../api/client";

vi.mock("../api/client", () => ({ api: { GET: vi.fn(), POST: vi.fn() } }));

function renderAtJob(jobId: string) {
  return render(
    <MemoryRouter initialEntries={[`/jobs/${jobId}`]}>
      <Routes>
        <Route path="/jobs/:jobId" element={<JobDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function jobResponse(overrides: Partial<Record<string, unknown>>) {
  return {
    id: "job-1",
    job_type: "shell",
    status: "queued",
    payload: { command: "echo hi" },
    result: null,
    error_message: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    started_at: null,
    completed_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(api.GET).mockReset();
  vi.mocked(api.POST).mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("JobDetailPage", () => {
  it("polls again after the interval while the job is still running", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(api.GET)
      .mockResolvedValueOnce({ data: jobResponse({ status: "queued" }), error: undefined } as never)
      .mockResolvedValueOnce({ data: jobResponse({ status: "running" }), error: undefined } as never);

    renderAtJob("job-1");

    await waitFor(() => expect(api.GET).toHaveBeenCalledTimes(1));

    await vi.advanceTimersByTimeAsync(3000);

    await waitFor(() => expect(api.GET).toHaveBeenCalledTimes(2));
  });

  it("stops polling and fetches artifacts once the job reaches a terminal status", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(api.GET).mockImplementation((path: string) => {
      if (path === "/api/v1/jobs/{job_id}") {
        return Promise.resolve({
          data: jobResponse({ status: "succeeded", result: { exit_code: 0 } }),
          error: undefined,
        }) as never;
      }
      return Promise.resolve({ data: { artifacts: [] }, error: undefined }) as never;
    });

    renderAtJob("job-1");

    await waitFor(() => expect(screen.getByText(/succeeded/i)).toBeInTheDocument());
    await waitFor(() =>
      expect(api.GET).toHaveBeenCalledWith(
        "/api/v1/jobs/{job_id}/artifacts",
        expect.anything(),
      ),
    );

    const callsBefore = vi.mocked(api.GET).mock.calls.length;
    await vi.advanceTimersByTimeAsync(10000);
    expect(vi.mocked(api.GET).mock.calls.length).toBe(callsBefore);
  });

  it("cancels a running job", async () => {
    vi.mocked(api.GET).mockResolvedValue({
      data: jobResponse({ status: "running" }),
      error: undefined,
    } as never);
    vi.mocked(api.POST).mockResolvedValueOnce({
      data: jobResponse({ status: "cancelled" }),
      error: undefined,
    } as never);

    renderAtJob("job-1");

    const cancelButton = await screen.findByRole("button", { name: /cancel job/i });
    cancelButton.click();

    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
  });
});
