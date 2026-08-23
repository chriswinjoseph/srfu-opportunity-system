import { test, expect } from '@playwright/test';

// Edge case: password reset request
// Run with: npx playwright test edge.spec.ts
//
// Verifies the forgot-password request flow and its confirmation message.
// Does NOT verify actual email delivery/inbox arrival — that requires a
// real inbox check and was verified manually (see Task 6 write-up).

const BASE_URL = process.env.TEST_BASE_URL || 'https://web-production-74dc0.up.railway.app';
const TEST_EMAIL = process.env.TEST_USER_EMAIL || '';

test.describe('Edge case: password reset request', () => {
  test('requesting a reset for a known email shows the confirmation message', async ({ page }) => {
    test.skip(!TEST_EMAIL, 'TEST_USER_EMAIL not set');

    await page.goto(`${BASE_URL}/accounts/forgot-password/`);
    await page.getByLabel('Email address').fill(TEST_EMAIL);
    await page.getByRole('button', { name: 'Send reset link' }).click();

    await expect(
      page.getByText(/if an account exists with that email, a password reset link has been sent/i)
    ).toBeVisible();
  });

  test('requesting a reset for a non-existent email shows the SAME confirmation (no info leak)', async ({ page }) => {
    await page.goto(`${BASE_URL}/accounts/forgot-password/`);
    await page.getByLabel('Email address').fill('definitely-not-a-real-account@example.com');
    await page.getByRole('button', { name: 'Send reset link' }).click();

    await expect(
      page.getByText(/if an account exists with that email, a password reset link has been sent/i)
    ).toBeVisible();
  });
});