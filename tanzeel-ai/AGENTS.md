# AGENTS.md - Architecture & Design Decisions

## System Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    EXPO MOBILE APP                           │
│                                                              │
│  ┌─────────┐  ┌─────────┐  ┌──────────┐  ┌──────────┐     │
│  │  Home   │  │ Recite  │  │ Progress │  │ Settings │     │
│  │Dashboard│  │(Record) │  │ (Stats)  │  │(i18n/Auth)│     │
│  └─────────┘  └────┬────┘  └──────────┘  └──────────┘     │
│                     │ audio file (m4a)                       │
│  ┌──────────────────┴───────────────────────────────────┐   │
│  │  API Client (axios) + JWT Auth + Auto-refresh        │   │
│  └──────────────────┬───────────────────────────────────┘   │
│                     │ HTTPS REST                             │
└─────────────────────┼────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                 FASTAPI SERVER                               │
│                                                              │
│  ┌──────────┐  ┌────────────────┐  ┌────────────────────┐  │
│  │ Auth     │  │ Recognition    │  │ Progress Tracking   │  │
│  │ (JWT)    │  │ POST /recognize│  │ GET /progress/*     │  │
│  └──────────┘  └───────┬────────┘  └────────────────────┘  │
│                        │                                     │
│  ┌─────────────────────┼───────────────────────────────┐    │
│  │                     │  Internal Pipeline             │    │
│  │  1. Call RunPod ────┘                                │    │
│  │  2. ASR text ──→ Arabic Normalization                │    │
│  │  3. Normalized ──→ N-gram Candidate Generation       │    │
│  │  4. Candidates ──→ Edit Distance Ranking             │    │
│  │  5. Results ──→ Save to DB + Return                  │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌────────────────────────────────────────────────────┐     │
│  │ PostgreSQL (users, recitations, daily_progress)     │     │
│  └────────────────────────────────────────────────────┘     │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTPS (RunPod API)
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              RUNPOD SERVERLESS WORKER                        │
│                                                              │
│  faster-whisper + tarteel-ai/whisper-base-ar-quran          │
│  CTranslate2 float16 on NVIDIA T4 GPU                       │
│  Silero VAD → Whisper decode → word timestamps               │
│                                                              │
│  Input: base64 audio → Output: Arabic text + timestamps     │
└─────────────────────────────────────────────────────────────┘
```

## Design Decisions & Rationale

### 1. REST before WebSocket

**Decision**: Use synchronous REST (record → upload → wait → result) instead of WebSocket streaming.

**Why**: WebSocket streaming adds substantial complexity (connection management, partial result handling, mobile network recovery, server-side state). For the MVP flow — user records a short passage, taps stop, waits 2-3 seconds for the result — REST is simpler to build, debug, cache, and scale. The perceived latency is acceptable because Whisper processes at ~10x real-time on a T4 GPU (a 10-second clip processes in ~1 second).

**Trade-off**: No live "follow along" as the user recites. This is a v2 feature.

### 2. Server-side ASR over on-device

**Decision**: Run Whisper inference on RunPod GPU servers, not on the user's phone.

**Why**:
- **Accuracy**: `whisper-base-ar-quran` (74M params, ~5.75% WER) vs `whisper-tiny` (39M, ~7% WER). The base model is meaningfully more accurate for Quranic Arabic.
- **App size**: Bundling even the tiny model adds ~75MB to the app binary. The base model is ~145MB. This is unacceptable for a mobile download.
- **Iteration speed**: Updating the model (e.g., switching to whisper-small) requires only a Docker rebuild, not an App Store submission.
- **Battery/thermal**: Whisper inference is compute-heavy. On-device inference would drain battery and generate heat.

**Trade-off**: Requires internet. Offline mode is a future enhancement (with the tiny model on-device as a fallback).

### 3. Custom Arabic normalization (~20 lines) over npm/PyPI packages

**Decision**: Write normalization by hand in both TypeScript and Python.

**Why**:
- The normalization is Quran-specific. General Arabic NLP packages (e.g., `camel-tools`, `pyarabic`) include far more than needed and add heavy dependencies.
- Only 7 transformations needed: remove tashkeel, remove tatweel, normalize 4 alef variants, taa marbuta → haa, alef maqsura → yaa, hamza carriers → base letter, collapse whitespace.
- At ~20 lines of code per language, there's zero dependency risk, no version conflicts, and full control over the behavior.
- Both implementations are identical and tested against the same corpus, ensuring client-side preview matches server-side matching.

### 4. N-gram matching engine over full-text search or embedding similarity

**Decision**: Custom two-stage matching (trigram candidate generation → edit distance ranking) instead of PostgreSQL FTS, Elasticsearch, or vector embeddings.

**Why**:
- The corpus is fixed and tiny: 6,236 ayat, ~53K word trigrams. The entire index fits in a few MB of RAM. No database is needed for search.
- ASR output is noisy (wrong words, missing words, extra words). Traditional full-text search struggles with these errors. Edit distance gracefully handles insertions, deletions, and substitutions at the word level.
- Embedding-based similarity (e.g., Sentence-BERT) would require another ML model and wouldn't handle partial ayah matches well.
- The trigram index provides O(1) lookup for candidate generation; edit distance on 20 candidates is ~microseconds. Total matching time is <1ms.

**The algorithm**:
1. Preprocess: normalize all ayat, tokenize into words, build a `{trigram → [ayah_indices]}` dictionary.
2. Query: normalize ASR output, extract trigrams, count overlap with each ayah. Top 20 candidates.
3. Rank: sliding-window word-level Levenshtein distance. The window handles partial matches (user recited 3 words out of a 10-word ayah).
4. Fallback: Dice coefficient on word sets if trigrams find nothing (handles single-word queries).

### 5. Amiri font over KFGQPC Uthmanic Script

**Decision**: Use Amiri (Google Fonts, OFL license) for Quranic Arabic display.

**Why**:
- **License**: Amiri is under the SIL Open Font License, clearly permitting app bundling and distribution. KFGQPC fonts have ambiguous licensing for commercial app distribution.
- **Availability**: Amiri is on Google Fonts, widely tested, well-maintained. Easy to download and bundle.
- **Quality**: Amiri is a high-quality Naskh font with good tashkeel stacking. It handles complex diacritics (shaddah + fathah, etc.) correctly on both iOS and Android.
- **Trade-off**: Amiri is a Naskh typeface, not the traditional Uthmanic script used in printed mushafs. Some users may prefer the Uthmanic style. This can be added as an option later.

### 6. Zustand over Redux / Context API

**Decision**: Use Zustand 5 for all client state (auth, recitation, settings).

**Why**:
- This app has 3 stores with ~5 actions each. Redux's boilerplate (actions, reducers, selectors, middleware) is disproportionate to the state complexity.
- Zustand is 1.1KB gzipped, has zero dependencies, and requires no Provider wrappers. Stores are plain functions that can be used outside React components (e.g., in axios interceptors).
- The `persist` middleware integrates with AsyncStorage for settings and with expo-secure-store for tokens with minimal code.
- Context API causes unnecessary re-renders in all consumers when any value changes. Zustand's selector-based subscriptions avoid this.

### 7. expo-audio over expo-av

**Decision**: Use the new `expo-audio` module (Expo SDK 54) instead of the legacy `expo-av`.

**Why**:
- `expo-audio` is the actively maintained replacement. `expo-av` is in maintenance mode.
- Hooks-based API (`useAudioRecorder`, `useAudioRecorderState`) is more ergonomic than the class-based `Audio.Recording` API.
- `useAudioRecorderState` provides live metering, duration, and recording status via a single hook with configurable polling interval.
- **Caveat**: `expo-audio` is still file-based (no raw PCM streaming). For the REST-based MVP this is fine. If we add WebSocket streaming later, we'd need `react-native-live-audio-stream`.

### 8. Per-component RTL over global I18nManager.forceRTL

**Decision**: Apply `writingDirection: 'rtl'` and `textAlign: 'right'` per-component, not globally.

**Why**:
- The app is bilingual. English UI elements (navigation, buttons, labels) should remain LTR even when the user switches to Arabic.
- `I18nManager.forceRTL(true)` flips the ENTIRE layout and requires an app restart to take effect. This is hostile UX for a language toggle.
- Arabic Quran text always renders RTL regardless of app language. English translations render LTR. This is only possible with per-component direction.
- NativeWind supports `rtl:` variant classes for conditional RTL styling, making this ergonomic in Tailwind.

### 9. PostgreSQL over SQLite for the server

**Decision**: Use PostgreSQL (via asyncpg) for the server database, not SQLite.

**Why**:
- The server handles concurrent requests from multiple users. SQLite's single-writer lock is a bottleneck under load.
- PostgreSQL supports proper UUID primary keys, date/time functions for streak calculation, and `DISTINCT` counting for unique ayat tracking.
- Railway and Supabase offer managed PostgreSQL at $0-10/month, making operational cost negligible.
- SQLAlchemy's async dialect (`asyncpg`) integrates cleanly with FastAPI's async request handlers.
- **Note**: The mobile app uses `expo-sqlite` for local caching (offline history browsing), which is the right tool for embedded single-user storage.

### 10. quran-json (MIT) over Tanzil.net

**Decision**: Use `risan/quran-json` from GitHub as the Quran text source.

**Why**:
- **License**: MIT. Unambiguously allows modification, redistribution, and commercial use. We normalize the text for matching (removing diacritics, changing letter forms) — this constitutes modification.
- **Tanzil.net** has a "no modification" clause in their license. Building a normalized index from their text is arguably a modification, creating legal ambiguity.
- **Format**: The risan/quran-json repo provides a clean JSON structure (114 surahs, nested verses), easy to transform. Tanzil.net provides XML/SQL dumps that require more parsing.
- **Data**: All 6,236 ayat with full Uthmani tashkeel, surah names in Arabic and English, surah metadata.

### 11. tarteel-ai/whisper-base-ar-quran over generic Whisper

**Decision**: Use Tarteel AI's Quran-specific fine-tune instead of OpenAI's generic whisper-base.

**Why**:
- Generic Whisper on Quranic recitation: ~40-60% WER. The model wasn't trained on tajweed-style recitation, which has elongations, nasalizations, and classical Arabic phonology that differ significantly from Modern Standard Arabic.
- Tarteel's fine-tune: ~5.75% WER on Quran. They trained on thousands of hours of Quran recitation audio from multiple reciters.
- The model is Apache 2.0 licensed and available on HuggingFace. No API dependency on Tarteel.
- We use CTranslate2 format (via `ct2-transformers-converter`) for faster-whisper compatibility, getting ~4x speedup over native PyTorch.

## File-by-file guide

### Mobile app (`app/` + `src/`)

| File | Purpose |
|------|---------|
| `app/_layout.tsx` | Root layout. Loads fonts, hydrates auth, gates navigation (auth vs tabs). |
| `app/(auth)/login.tsx` | Email/password login + "Continue as Guest" button. |
| `app/(auth)/register.tsx` | Name/email/password registration form. |
| `app/(tabs)/_layout.tsx` | Tab navigator with 4 tabs: Home, Recite, Progress, Settings. |
| `app/(tabs)/index.tsx` | Home dashboard: greeting, today's stats, streak, recent history. |
| `app/(tabs)/recite.tsx` | Core screen: record button, waveform, upload, display results. |
| `app/(tabs)/progress.tsx` | Stats grid (total, unique ayat, streak) + full history list. |
| `app/(tabs)/settings.tsx` | Language toggle (EN/AR), theme picker, account info, logout. |
| `app/result/[id].tsx` | Detail view for a single recitation result. |
| `app/surah/[id].tsx` | Surah viewer (metadata only for now). |
| `src/components/RecordButton.tsx` | Animated circular button with Reanimated pulse effect. |
| `src/components/WaveformVisualizer.tsx` | 30-bar animated waveform driven by audio metering. |
| `src/components/AyahText.tsx` | Arabic verse display with Amiri font, proper RTL and line height. |
| `src/components/ResultCard.tsx` | Card showing matched surah/ayah, confidence badge, Arabic text. |
| `src/components/LanguageToggle.tsx` | EN/AR pill toggle that updates i18next + Zustand. |
| `src/hooks/useAudioRecorder.ts` | Wraps expo-audio: permissions, recording, metering, auto-stop. |
| `src/hooks/useRecognition.ts` | Sends audio to API, updates recitation store with results. |
| `src/hooks/useAuth.ts` | Login/register/logout/guest, hydrates user from token on mount. |
| `src/stores/authStore.ts` | Zustand: user, tokens, isAuthenticated, isGuest, isLoading. |
| `src/stores/recitationStore.ts` | Zustand: recording status, current result, history. |
| `src/stores/settingsStore.ts` | Zustand (persisted): language, theme. |
| `src/services/api.ts` | Axios instance with JWT interceptor and auto-refresh on 401. |
| `src/services/auth.ts` | API calls: login, register, refresh, getMe. |
| `src/services/recognition.ts` | API call: POST /api/recognize (multipart audio upload). |
| `src/utils/arabic.ts` | Client-side Arabic normalization (mirrors server version). |
| `src/utils/quranData.ts` | Static metadata for all 114 surahs (names, ayah counts). |
| `src/i18n/en.json` | English UI strings. |
| `src/i18n/ar.json` | Arabic UI strings. |
| `src/constants/config.ts` | API URL, audio limits, auth token keys. |
| `src/constants/theme.ts` | Color palette (light/dark), spacing, font sizes. |

### Server (`server/`)

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI app. Loads quran.json into matcher on startup. CORS enabled. |
| `app/config.py` | Pydantic Settings: DB URL, JWT config, RunPod keys, limits. |
| `app/database.py` | SQLAlchemy async engine + session factory. |
| `app/dependencies.py` | `get_current_user` (required auth) and `get_optional_user` (guest-ok). |
| `app/routers/auth.py` | Register, login, refresh, me. bcrypt + JWT. |
| `app/routers/recognition.py` | POST /api/recognize: validate audio → ASR → match → save → return. |
| `app/routers/progress.py` | Summary (streak calc), paginated history, daily heatmap. |
| `app/models/user.py` | User: id, email, password_hash, name, preferred_language. |
| `app/models/recitation.py` | Recitation (per-recognition record) + DailyProgress (aggregated). |
| `app/services/arabic_norm.py` | Arabic normalization (20 lines, identical logic to client). |
| `app/services/asr.py` | RunPod API client: base64 encode audio → POST → get transcription. |
| `app/services/matcher.py` | Quran matching engine: load, index, match (n-gram + edit distance). |
| `app/data/quran.json` | All 6,236 ayat (flat array, from risan/quran-json). |
| `alembic/versions/001_initial.py` | Initial migration: users, recitations, daily_progress tables. |

### Worker (`worker/`)

| File | Purpose |
|------|---------|
| `handler.py` | RunPod handler: decode base64 audio → faster-whisper transcribe → return text + timestamps. |
| `Dockerfile` | CUDA 12.1 + faster-whisper + model conversion (tarteel → CTranslate2 float16). |
| `requirements.txt` | faster-whisper, runpod, numpy. |

## Current state (as of initial implementation)

**What works**:
- Mobile app compiles with zero TypeScript errors
- All 7 screens render: login, register, home, recite, progress, settings, not-found
- Tab navigation with 4 tabs
- i18n: English and Arabic translations for all UI strings
- Language toggle persisted via Zustand + AsyncStorage
- Auth flow: login/register forms, guest mode, JWT token management
- Animated record button with Reanimated pulse effect
- Waveform visualizer with 30 animated bars
- Quran matcher engine tested and verified (Bismillah → Al-Fatihah 1:1 at 100%, Qul Huwa → Al-Ikhlas 112:1 at 100%)
- All 6,236 ayat indexed with 53K n-gram entries
- Server: full auth flow, recognition pipeline, progress tracking endpoints
- Database migrations written

**What needs deployment/integration**:
- RunPod worker: build Docker image, deploy, get endpoint ID
- PostgreSQL: provision database, run migrations
- Server: deploy to Railway/Fly.io, set env vars
- Mobile: set EXPO_PUBLIC_API_URL to deployed server
- End-to-end test with real audio

**Future enhancements (not started)**:
- WebSocket streaming for live "follow along" recitation
- On-device Whisper (tiny model) for offline mode
- Calendar heatmap visualization on progress screen
- Surah viewer with full ayah text
- Tajweed error detection
- Dark mode (theme toggle exists, dark styles partially applied)
