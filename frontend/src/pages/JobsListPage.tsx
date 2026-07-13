import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import type { components } from "../api/generated/schema";

type JobResponse = components["schemas"]["JobResponse"];

export function JobsListPage() {
  const [jobs, setJobs] = useState<JobResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const { data, error: fetchError } = await api.GET("/api/v1/jobs", {
        params: { query: { limit: 50, offset: 0 } },
      });
      if (cancelled) return;
      if (fetchError) {
        setError("Failed to load jobs");
        return;
      }
      setJobs(data.jobs);
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <h1>Jobs</h1>
      {error && <p className="error-text">{error}</p>}
      {jobs === null && !error && <p className="muted">Loading…</p>}
      {jobs !== null && jobs.length === 0 && (
        <p className="muted">
          No jobs yet. <Link to="/jobs/new">Create one</Link>.
        </p>
      )}
      {jobs !== null && jobs.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Type</th>
              <th>Status</th>
              <th>Created</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr key={job.id}>
                <td>{job.job_type}</td>
                <td>
                  <StatusBadge status={job.status} />
                </td>
                <td className="muted">{new Date(job.created_at).toLocaleString()}</td>
                <td>
                  <Link to={`/jobs/${job.id}`}>View</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
