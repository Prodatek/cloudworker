import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NewJobPage } from "./NewJobPage";
import { api } from "../api/client";

const navigateMock = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useNavigate: () => navigateMock };
});

vi.mock("../api/client", () => ({ api: { POST: vi.fn(), GET: vi.fn() } }));

beforeEach(() => {
  navigateMock.mockReset();
  vi.mocked(api.POST).mockReset();
});

describe("NewJobPage", () => {
  it("defaults to a shell job and submits the command payload", async () => {
    vi.mocked(api.POST).mockResolvedValueOnce({
      data: { id: "job-1" },
      error: undefined,
      response: new Response(),
    } as never);
    const user = userEvent.setup();
    render(<NewJobPage />, { wrapper: MemoryRouter });

    await user.type(screen.getByLabelText(/shell command/i), "echo hi");
    await user.click(screen.getByRole("button", { name: /create job/i }));

    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/jobs",
      expect.objectContaining({
        body: { job_type: "shell", payload: { command: "echo hi" } },
      }),
    );
    expect(navigateMock).toHaveBeenCalledWith("/jobs/job-1");
  });

  it("switches to the script field for browser jobs", async () => {
    const user = userEvent.setup();
    render(<NewJobPage />, { wrapper: MemoryRouter });

    await user.selectOptions(screen.getByLabelText(/job type/i), "browser");

    expect(screen.getByLabelText(/playwright script/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/shell command/i)).not.toBeInTheDocument();
  });

  it("submits the script payload for browser jobs", async () => {
    vi.mocked(api.POST).mockResolvedValueOnce({
      data: { id: "job-2" },
      error: undefined,
      response: new Response(),
    } as never);
    const user = userEvent.setup();
    render(<NewJobPage />, { wrapper: MemoryRouter });

    await user.selectOptions(screen.getByLabelText(/job type/i), "browser");
    await user.type(screen.getByLabelText(/playwright script/i), "page.goto('x')");
    await user.click(screen.getByRole("button", { name: /create job/i }));

    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/jobs",
      expect.objectContaining({
        body: { job_type: "browser", payload: { script: "page.goto('x')" } },
      }),
    );
  });

  it("shows an error message when job creation is rejected", async () => {
    vi.mocked(api.POST).mockResolvedValueOnce({
      data: undefined,
      error: { detail: "invalid" },
      response: new Response(null, { status: 422 }),
    } as never);
    const user = userEvent.setup();
    render(<NewJobPage />, { wrapper: MemoryRouter });

    await user.type(screen.getByLabelText(/shell command/i), "echo hi");
    await user.click(screen.getByRole("button", { name: /create job/i }));

    expect(await screen.findByText(/rejected/i)).toBeInTheDocument();
    expect(navigateMock).not.toHaveBeenCalled();
  });
});
