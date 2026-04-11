/**
 * MSW request handlers for mocking API calls in tests.
 */

import { http, HttpResponse } from "msw";

const API_BASE = "http://localhost:8000";

export const handlers = [
  // Auth
  http.get(`${API_BASE}/api/v1/auth/me`, () => {
    return HttpResponse.json({
      id: "550e8400-e29b-41d4-a716-446655440000",
      github_id: 12345678,
      github_username: "testuser",
      email: "test@example.com",
      avatar_url: "https://avatars.githubusercontent.com/u/12345678",
      is_active: true,
      onboarding_completed: true,
      created_at: "2024-01-01T00:00:00Z",
    });
  }),

  // Onboarding options
  http.get(`${API_BASE}/api/v1/onboarding/options`, () => {
    return HttpResponse.json({
      roles: ["backend", "frontend", "fullstack"],
      interests: ["web_development", "cloud_infrastructure"],
      languages: ["python", "typescript", "go"],
      frameworks: ["fastapi", "nextjs", "react"],
    });
  }),

  // Onboarding profile
  http.get(`${API_BASE}/api/v1/onboarding/profile`, () => {
    return HttpResponse.json({
      id: "660e8400-e29b-41d4-a716-446655440000",
      user_id: "550e8400-e29b-41d4-a716-446655440000",
      primary_role: "backend",
      interests: ["web_development"],
      technologies: {
        languages: ["python", "typescript"],
        frameworks: ["fastapi"],
      },
      experience_years: 5,
      config_hash: "abc123",
    });
  }),

  // Assessments list
  http.get(`${API_BASE}/api/v1/assessments`, () => {
    return HttpResponse.json({
      assessments: [],
      total: 0,
    });
  }),

  // Health check
  http.get(`${API_BASE}/api/health`, () => {
    return HttpResponse.json({
      status: "healthy",
      version: "0.1.0",
    });
  }),
];
