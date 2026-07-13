import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { RequireAuth } from "./components/RequireAuth";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";
import { JobsListPage } from "./pages/JobsListPage";
import { JobDetailPage } from "./pages/JobDetailPage";
import { NewJobPage } from "./pages/NewJobPage";
import { ApiKeysPage } from "./pages/ApiKeysPage";

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route
          path="/jobs"
          element={
            <RequireAuth>
              <JobsListPage />
            </RequireAuth>
          }
        />
        <Route
          path="/jobs/new"
          element={
            <RequireAuth>
              <NewJobPage />
            </RequireAuth>
          }
        />
        <Route
          path="/jobs/:jobId"
          element={
            <RequireAuth>
              <JobDetailPage />
            </RequireAuth>
          }
        />
        <Route
          path="/api-keys"
          element={
            <RequireAuth>
              <ApiKeysPage />
            </RequireAuth>
          }
        />
        <Route path="/" element={<Navigate to="/jobs" replace />} />
        <Route path="*" element={<Navigate to="/jobs" replace />} />
      </Route>
    </Routes>
  );
}
