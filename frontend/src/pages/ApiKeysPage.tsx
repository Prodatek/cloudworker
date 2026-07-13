import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { components } from "../api/generated/schema";

type ApiKeyResponse = components["schemas"]["ApiKeyResponse"];

export function ApiKeysPage() {
  const [keys, setKeys] = useState<ApiKeyResponse[] | null>(null);
  const [newlyCreatedKey, setNewlyCreatedKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const loadKeys = useCallback(async () => {
    const { data, error: fetchError } = await api.GET("/api/v1/api-keys");
    if (fetchError) {
      setError("Failed to load API keys");
      return;
    }
    setKeys(data.api_keys);
  }, []);

  useEffect(() => {
    void loadKeys();
  }, [loadKeys]);

  async function handleCreate() {
    setCreating(true);
    setNewlyCreatedKey(null);
    try {
      const { data, error: createError } = await api.POST("/api/v1/api-keys");
      if (createError) {
        setError("Failed to create API key");
        return;
      }
      setNewlyCreatedKey(data.api_key);
      await loadKeys();
    } finally {
      setCreating(false);
    }
  }

  async function handleRevoke(id: string) {
    const { error: revokeError } = await api.POST("/api/v1/api-keys/{api_key_id}/revoke", {
      params: { path: { api_key_id: id } },
    });
    if (!revokeError) {
      await loadKeys();
    }
  }

  return (
    <div>
      <h1>API Keys</h1>
      <p className="muted">
        Use an API key as an <code>Authorization: Bearer &lt;key&gt;</code> header for
        programmatic access — see docs/api-examples.md.
      </p>

      {newlyCreatedKey && (
        <div className="card">
          <strong>New API key (shown once — copy it now):</strong>
          <pre>{newlyCreatedKey}</pre>
        </div>
      )}

      <button type="button" onClick={handleCreate} disabled={creating}>
        {creating ? "Creating…" : "Create new API key"}
      </button>

      {error && <p className="error-text">{error}</p>}
      {keys === null && !error && <p className="muted">Loading…</p>}

      {keys !== null && keys.length > 0 && (
        <table style={{ marginTop: "1rem" }}>
          <thead>
            <tr>
              <th>Prefix</th>
              <th>Created</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {keys.map((key) => (
              <tr key={key.id}>
                <td>
                  <code>{key.prefix}…</code>
                </td>
                <td className="muted">{new Date(key.created_at).toLocaleString()}</td>
                <td>{key.revoked_at ? "Revoked" : "Active"}</td>
                <td>
                  {!key.revoked_at && (
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => void handleRevoke(key.id)}
                    >
                      Revoke
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
