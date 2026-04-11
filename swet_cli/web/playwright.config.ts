import { defineConfig } from '@playwright/test';

export default defineConfig({
	testDir: 'tests',
	timeout: 30_000,
	retries: 0,
	use: {
		baseURL: process.env.SMOKE_BASE_URL || 'https://swet.omarss.net',
		ignoreHTTPSErrors: true,
	},
	projects: [
		{
			name: 'smoke',
			testMatch: 'smoke.spec.ts',
		},
	],
});
