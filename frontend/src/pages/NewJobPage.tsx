import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { components } from "../api/generated/schema";

type JobType = components["schemas"]["JobType"];
type JobCreateRequest = components["schemas"]["JobCreateRequest"];

export function NewJobPage() {
  const navigate = useNavigate();
  const [jobType, setJobType] = useState<JobType>("shell");
  const [command, setCommand] = useState("");
  const [script, setScript] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      // The backend's payload is a genuinely free-form dict (dict[str, Any]); FastAPI's
      // generated schema doesn't declare additionalProperties, so openapi-typescript
      // narrows it to an empty-object type. Cast rather than fight the codegen here.
      const payload = jobType === "shell" ? { command } : { script };
      const body = { job_type: jobType, payload } as unknown as JobCreateRequest;
      const { data, error: createError } = await api.POST("/api/v1/jobs", { body });
      if (createError) {
        throw new Error("Job creation was rejected — check the command/script isn't empty");
      }
      navigate(`/jobs/${data.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create job");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="card" style={{ maxWidth: 560 }}>
      <h1>New job</h1>
      <form onSubmit={handleSubmit}>
        <div className="form-field">
          <label htmlFor="job-type">Job type</label>
          <select
            id="job-type"
            value={jobType}
            onChange={(e) => setJobType(e.target.value as JobType)}
          >
            <option value="shell">Shell</option>
            <option value="browser">Browser (Playwright)</option>
          </select>
        </div>
        {jobType === "shell" ? (
          <div className="form-field">
            <label htmlFor="command">Shell command</label>
            <textarea
              id="command"
              required
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              placeholder="echo hello world"
            />
          </div>
        ) : (
          <div className="form-field">
            <label htmlFor="script">Playwright script (Python)</label>
            <textarea
              id="script"
              required
              value={script}
              onChange={(e) => setScript(e.target.value)}
              placeholder={
                'page.goto("https://example.com")\npage.screenshot(path=output_dir / "home.png")'
              }
            />
            <span className="muted">
              Runs with page/browser/context/output_dir available — see docs/api-examples.md.
            </span>
          </div>
        )}
        {error && <p className="error-text">{error}</p>}
        <button type="submit" disabled={submitting}>
          {submitting ? "Creating…" : "Create job"}
        </button>
      </form>
    </div>
  );
}
