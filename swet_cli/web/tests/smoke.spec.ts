/**
 * Smoke tests — verify the deployed site and API are up and serving
 * correctly. No authentication needed; these hit public endpoints and
 * check that pages load without errors.
 *
 * Run: make smoke
 * Override URL: SMOKE_BASE_URL=http://localhost:5173 make smoke
 */
import { test, expect } from '@playwright/test';

// ---------------------------------------------------------------------------
// API health
// ---------------------------------------------------------------------------

test('API /health returns ok', async ({ request }) => {
	const resp = await request.get('/health');
	expect(resp.status()).toBe(200);
	const body = await resp.json();
	expect(body.status).toBe('ok');
});

test('API /docs (Swagger) is accessible', async ({ request }) => {
	const resp = await request.get('/docs');
	expect(resp.status()).toBe(200);
});

// ---------------------------------------------------------------------------
// SPA shell loads
// ---------------------------------------------------------------------------

test('SPA index serves HTML with correct meta', async ({ page }) => {
	const resp = await page.goto('/');
	expect(resp?.status()).toBe(200);
	await expect(page).toHaveTitle(/swet/i);
	// The SPA should have loaded its JS bundle
	await expect(page.locator('body')).toHaveAttribute('data-sveltekit-preload-data', 'hover');
});

// ---------------------------------------------------------------------------
// Unauthenticated routes redirect to /login
// ---------------------------------------------------------------------------

test('/ redirects unauthenticated user to /login', async ({ page }) => {
	await page.goto('/');
	await page.waitForURL('**/login');
	expect(page.url()).toContain('/login');
});

test('/today redirects to /login', async ({ page }) => {
	await page.goto('/today');
	await page.waitForURL('**/login');
	expect(page.url()).toContain('/login');
});

test('/train redirects to /login', async ({ page }) => {
	await page.goto('/train');
	await page.waitForURL('**/login');
	expect(page.url()).toContain('/login');
});

test('/review redirects to /login', async ({ page }) => {
	await page.goto('/review');
	await page.waitForURL('**/login');
	expect(page.url()).toContain('/login');
});

test('/library redirects to /login', async ({ page }) => {
	await page.goto('/library');
	await page.waitForURL('**/login');
	expect(page.url()).toContain('/login');
});

test('/progress redirects to /login', async ({ page }) => {
	await page.goto('/progress');
	await page.waitForURL('**/login');
	expect(page.url()).toContain('/login');
});

// ---------------------------------------------------------------------------
// Login page renders correctly
// ---------------------------------------------------------------------------

test('login page renders sign-in form', async ({ page }) => {
	await page.goto('/login');
	// Should have email/mobile input
	await expect(page.locator('input')).toBeVisible();
	// Should have the SWET branding
	await expect(page.locator('text=swet').first()).toBeVisible();
});

// ---------------------------------------------------------------------------
// Protected API endpoints require auth
// ---------------------------------------------------------------------------

test('API /preferences returns 401 without token', async ({ request }) => {
	const resp = await request.get('/preferences');
	expect(resp.status()).toBe(401);
});

test('API /questions/next returns 401 without token', async ({ request }) => {
	const resp = await request.get('/questions/next');
	expect(resp.status()).toBe(401);
});

test('API /stats returns 401 without token', async ({ request }) => {
	const resp = await request.get('/stats');
	expect(resp.status()).toBe(401);
});

test('API /dashboard returns 401 without token', async ({ request }) => {
	const resp = await request.get('/dashboard');
	expect(resp.status()).toBe(401);
});

test('API /sessions/current returns 401 without token', async ({ request }) => {
	const resp = await request.get('/sessions/current');
	expect(resp.status()).toBe(401);
});

test('API /reviews returns 401 without token', async ({ request }) => {
	const resp = await request.get('/reviews');
	expect(resp.status()).toBe(401);
});

test('API /bookmarks returns 401 without token', async ({ request }) => {
	const resp = await request.get('/bookmarks');
	expect(resp.status()).toBe(401);
});

// ---------------------------------------------------------------------------
// Auth endpoints accept requests (don't 404 or 500)
// ---------------------------------------------------------------------------

test('API /auth/otp/send returns 4xx for empty body (not 500)', async ({ request }) => {
	const resp = await request.post('/auth/otp/send', { data: {} });
	// Should be a validation error (422) or bad request (400), not a 500
	expect(resp.status()).toBeGreaterThanOrEqual(400);
	expect(resp.status()).toBeLessThan(500);
});

// ---------------------------------------------------------------------------
// Static assets
// ---------------------------------------------------------------------------

test('CSS and JS bundles load', async ({ page }) => {
	const failures: string[] = [];
	page.on('response', (resp) => {
		if (resp.url().includes('/_app/') && resp.status() >= 400) {
			failures.push(`${resp.status()} ${resp.url()}`);
		}
	});
	await page.goto('/login');
	await page.waitForLoadState('networkidle');
	expect(failures).toEqual([]);
});

// ---------------------------------------------------------------------------
// No console errors on page load
// ---------------------------------------------------------------------------

test('login page has no console errors', async ({ page }) => {
	const errors: string[] = [];
	page.on('console', (msg) => {
		if (msg.type() === 'error') errors.push(msg.text());
	});
	await page.goto('/login');
	await page.waitForLoadState('networkidle');
	expect(errors).toEqual([]);
});
