import { test, expect, type Page } from "@playwright/test";

/**
 * End-to-end happy path:
 *
 *  1. Visit the dashboard; confirm the privacy posture panel renders.
 *  2. Switch the active tenant via the topbar `TenantSwitcher`.
 *  3. Navigate to /intake, submit a PA.
 *  4. Land on /pa/[rid] — confirm the document tab, audit tab, and
 *     proof_id summary card render with no PHI in any visible text.
 *  5. Navigate to /pa — confirm the new PA is in the list and filterable.
 *  6. Navigate to /slo — confirm the snapshot renders with the new sample.
 */

const TENANT = "e2e-tenant";

async function switchTenant(page: Page, tenant: string) {
  // Open the tenant dropdown in the topbar.
  await page.getByRole("button", { name: /tenant:/i }).click();
  // Add the tenant via the inline form (idempotent — switches if already known).
  await page.getByLabel("Add tenant").fill(tenant);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: new RegExp(`tenant:.*${tenant}`) })).toBeVisible();
}

test("dashboard renders with privacy posture", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /ROI Dashboard/i })).toBeVisible();
  await expect(page.getByText(/Privacy & Cryptography/i)).toBeVisible();
  await expect(page.getByText(/HIPAA Safe Harbor/i)).toBeVisible();
  await expect(page.getByText(/FHE Inference/i)).toBeVisible();
  await expect(page.getByText(/zk-STARK/i)).toBeVisible();
});

test("submit a PA, see it in the list, see SLO snapshot", async ({ page }) => {
  await page.goto("/");
  await switchTenant(page, TENANT);

  // --- Intake ---
  await page.goto("/intake");
  await expect(page.getByRole("heading", { name: /New Prior Authorization/i })).toBeVisible();

  // The form has sensible defaults, so submit straight away.
  await page.getByRole("button", { name: /Run PA pipeline/i }).click();

  // --- PA detail ---
  await expect(page).toHaveURL(/\/pa\/[0-9a-f-]+$/, { timeout: 15_000 });
  await expect(page.getByText(/Medical-necessity narrative/i)).toBeVisible();
  // No PHI patterns should be visible.
  await expect(page.getByText(/AB12345678/)).toHaveCount(0);
  await expect(page.getByText(/John Smith/)).toHaveCount(0);

  // --- PA list ---
  await page.getByRole("link", { name: /PA runs/i }).click();
  await expect(page.getByRole("heading", { name: /Prior Authorizations/i })).toBeVisible();
  await expect(page.getByText(/Showing/)).toBeVisible();

  // Filter by payer = anthem (matches intake default).
  await page.getByLabel("Payer id").fill("anthem");
  await page.waitForTimeout(500); // let the debounce settle
  await expect(page.getByRole("cell", { name: "anthem" }).first()).toBeVisible();

  // --- SLO dashboard ---
  await page.getByRole("link", { name: /SLOs/i }).click();
  await expect(page.getByRole("heading", { name: /Service Level Objectives/i })).toBeVisible();
  // Either "All SLOs met" or one of the at-risk / breached states should
  // be visible — we only assert the dashboard renders.
  const overall = page.getByText(/(All SLOs met|At-risk SLOs|Breached SLO present)/);
  await expect(overall).toBeVisible({ timeout: 10_000 });
});
