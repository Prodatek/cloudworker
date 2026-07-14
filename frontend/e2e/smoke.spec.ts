import { test, expect } from "@playwright/test";

// Requires a running backend + Postgres reachable at the frontend's VITE_API_BASE_URL
// (default http://localhost:8000) — see e2e/README.md. Not run by CI or this project's
// automated verification for the same reason every Postgres-backed integration test isn't:
// no reachable database in the environment this was authored in.

function uniqueEmail(): string {
  return `e2e-${Date.now()}-${Math.random().toString(36).slice(2)}@example.com`;
}

test("register, log in, submit a shell job, and see it in the list", async ({ page }) => {
  const email = uniqueEmail();
  const password = "correct horse battery staple";

  await page.goto("/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Create account" }).click();

  // Registration logs the user in automatically (AuthContext.register calls login
  // internally) and redirects to /jobs.
  await expect(page).toHaveURL(/\/jobs$/);

  await page.getByRole("link", { name: "Create one" }).click();
  await expect(page).toHaveURL(/\/jobs\/new$/);

  await page.getByLabel("Shell command").fill("echo hello from e2e");
  await page.getByRole("button", { name: "Create job" }).click();

  // NewJobPage navigates to /jobs/:id on success.
  await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]+$/);

  await page.goto("/jobs");
  await expect(page.getByText("shell")).toBeVisible();
});

test("logging out and back in still shows the account's jobs", async ({ page }) => {
  const email = uniqueEmail();
  const password = "correct horse battery staple";

  await page.goto("/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/jobs$/);

  await page.getByRole("link", { name: "Create one" }).click();
  await page.getByLabel("Shell command").fill("echo persisted");
  await page.getByRole("button", { name: "Create job" }).click();
  await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]+$/);

  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/login$/);

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Log in" }).click();

  await expect(page).toHaveURL(/\/jobs$/);
  await expect(page.getByText("shell")).toBeVisible();
});
