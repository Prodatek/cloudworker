import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import type { components } from "../api/generated/schema";

type JobResponse = components["schemas"]["JobResponse"];
type ArtifactResponse = components["schemas"]["ArtifactResponse"];

const TERMINAL_STATUSES = new Set(["succeeded", "failed", "cancelled"]);
const POLL_INTERVAL_MS = 3000;

export function JobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const [job, setJob] = useState<JobResponse | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactResponse[] | null>(null);
  const [artifactsError, setArtifactsError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);

  const loadJob = useCallback(async () => {
    if (!jobId) return;
    const { data, error: fetchError } = await api.GET("/api/v1/jobs/{job_id}", {
      params: { path: { job_id: jobId } },
    });
    if (fetchError) {
      setError("Job not found");
      return;
    }
    setJob(data);
  }, [jobId]);

  const loadArtifacts = useCallback(async () => {
    if (!jobId) return;
    const { data, error: fetchError } = await api.GET("/api/v1/jobs/{job_id}/artifacts", {
      params: { path: { job_id: jobId } },
    });
    if (fetchError) {
      setArtifactsError(
        "status" in fetchError && (fetchError as { status?: number }).status === 503
          ? "Artifact storage isn't configured on this deployment"
          : "Failed to load artifacts",
      );
      return;
    }
    setArtifacts(data.artifacts);
  }, [jobId]);

  useEffect(() => {
    void loadJob();
  }, [loadJob]);

  useEffect(() => {
    if (!job || !TERMINAL_STATUSES.has(job.status)) return;
    void loadArtifacts();
  }, [job, loadArtifacts]);

  useEffect(() => {
    if (!job || TERMINAL_STATUSES.has(job.status)) return;
    const interval = setInterval(() => void loadJob(), POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [job, loadJob]);

  async function handleCancel() {
    if (!jobId) return;
    setCancelling(true);
    try {
      const { data, error: cancelError } = await api.POST("/api/v1/jobs/{job_id}/cancel", {
        params: { path: { job_id: jobId } },
      });
      if (!cancelError) {
        setJob(data);
      }
    } finally {
      setCancelling(false);
    }
  }

  if (error) return <p className="error-text">{error}</p>;
  if (!job) return <p className="muted">Loading…</p>;

  const canCancel = job.status === "queued" || job.status === "running";

  return (
    <div>
      <h1>
        Job <span className="muted">{job.id}</span>
      </h1>
      <div className="card">
        <p>
          <StatusBadge status={job.status} /> &nbsp;
          <span className="muted">{job.job_type}</span>
        </p>
        <p className="muted">Created {new Date(job.created_at).toLocaleString()}</p>
        {job.started_at && (
          <p className="muted">Started {new Date(job.started_at).toLocaleString()}</p>
        )}
        {job.completed_at && (
          <p className="muted">Completed {new Date(job.completed_at).toLocaleString()}</p>
        )}

        <h3>Payload</h3>
        <pre>{JSON.stringify(job.payload, null, 2)}</pre>

        {job.result && (
          <>
            <h3>Result</h3>
            <pre>{JSON.stringify(job.result, null, 2)}</pre>
          </>
        )}

        {job.error_message && (
          <>
            <h3>Error</h3>
            <p className="error-text">{job.error_message}</p>
          </>
        )}

        {canCancel && (
          <button type="button" className="danger" onClick={handleCancel} disabled={cancelling}>
            {cancelling ? "Cancelling…" : "Cancel job"}
          </button>
        )}
      </div>

      {TERMINAL_STATUSES.has(job.status) && (
        <div className="card">
          <h3>Artifacts</h3>
          {artifactsError && <p className="muted">{artifactsError}</p>}
          {artifacts && artifacts.length === 0 && <p className="muted">No artifacts.</p>}
          {artifacts && artifacts.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th>Key</th>
                  <th>Kind</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {artifacts.map((artifact) => (
                  <tr key={artifact.key}>
                    <td>{artifact.key}</td>
                    <td>{artifact.kind}</td>
                    <td>
                      <a href={artifact.url} target="_blank" rel="noreferrer">
                        Download
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
