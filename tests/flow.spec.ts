import { test, expect } from '@playwright/test';

// Login -> redirect -> dashboard flow
// Run with: npx playwright test flow.spec.ts
//
// Requires two env vars pointing at a real test account in the Django app:
//   TEST_USER_EMAIL, TEST_USER_PASSWORD
// Set these in a .env.local (never commit real credentials into this file).

const BASE_URL = process.env.TEST_BASE_URL || 'https://web-production-74dc0.up.railway.app';
const TEST_EMAIL = process.env.TEST_USER_EMAIL || '';
const TEST_PASSWORD = process.env.TEST_USER_PASSWORD || '';

test.describe('Login -> redirect -> dashboard flow', () => {
  test('successful login redirects to /accounts/dashboard/ and renders welcome message', async ({ page }) => {
    test.skip(!TEST_EMAIL || !TEST_PASSWORD, 'TEST_USER_EMAIL / TEST_USER_PASSWORD not set');

    await page.goto(`${BASE_URL}/accounts/login/`);
    await page.getByLabel('Email address').fill(TEST_EMAIL);
    await page.getByLabel('Password').fill(TEST_PASSWORD);
    await page.getByRole('button', { name: 'Log in' }).click();

    await page.waitForURL(/\/accounts\/dashboard\/?$/);
    await expect(page.getByText(/Welcome,/)).toBeVisible();
  });

  test('invalid credentials show a clear error and stay on the login page', async ({ page }) => {
    test.skip(!TEST_EMAIL, 'TEST_USER_EMAIL not set');

    await page.goto(`${BASE_URL}/accounts/login/`);
    await page.getByLabel('Email address').fill(TEST_EMAIL);
    await page.getByLabel('Password').fill('DefinitelyWrongPassword123!');
    await page.getByRole('button', { name: 'Log in' }).click();

    await expect(
      page.getByText('Please enter a correct email or password.')
    ).toBeVisible();
    await expect(page).toHaveURL(/\/accounts\/login\/?$/);
  });

  test('empty required fields are blocked from submission', async ({ page }) => {
    await page.goto(`${BASE_URL}/accounts/login/`);

    await page.getByRole('button', { name: 'Log in' }).click();

    // Browser-native "required" validation should keep the user on the
    // same page rather than submitting to the server.
    await expect(page).toHaveURL(/\/accounts\/login\/?$/);
  });

  test('accessing /accounts/dashboard/ without a session redirects to /accounts/login/', async ({ page, context }) => {
    await context.clearCookies();
    await page.goto(`${BASE_URL}/accounts/dashboard/`);
    await page.waitForURL(/\/accounts\/login\/?/);
    await expect(page).toHaveURL(/\/accounts\/login\//);
  });
});