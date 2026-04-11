# CLAUDE.md - Tanzeel AI

## What is this project?

Tanzeel AI is a cross-platform mobile app that identifies Quran verses from audio recitation. A user recites any passage, the app records it, sends the audio to a server for Arabic speech recognition (ASR), then matches the transcribed text against all 6,236 ayat of the Quran to identify the exact Surah and Ayah. The UI is bilingual (Arabic/English).

## Project structure

This is a **monorepo** with three deployable units:

```
tanzeel-ai/
├── app/              # Expo Router screens (file-based routing)
├── src/              # Mobile app source (components, hooks, stores, services, utils, i18n)
├── server/           # FastAPI backend (auth, recognition, progress tracking)
├── worker/           # RunPod serverless GPU worker (ASR inference)
├── assets/           # Fonts (Amiri Arabic, SpaceMono)
├── global.css        # Tailwind CSS entry point for NativeWind
├── metro.config.js   # Metro bundler config with NativeWind plugin
└── tailwind.config.js
```

## Tech stack

### Mobile (Expo/React Native)
- **Expo SDK 54**, React Native 0.81, React 19
- **Expo Router v6** - file-based routing in `app/`
- **NativeWind v4** + Tailwind CSS 3.4 - utility-first styling via `className` prop
- **expo-audio** - microphone recording (`useAudioRecorder` + `useAudioRecorderState` hooks)
- **Zustand 5** - state management (auth, recitation, settings stores)
- **i18next** + react-i18next - bilingual UI (English/Arabic)
- **React Native Reanimated v4** - animations (record button pulse, waveform)
- **expo-secure-store** - JWT token storage
- **Amiri** font (Google Fonts, open source) for Arabic Quranic text

### Server (FastAPI)
- **FastAPI** + Uvicorn - async Python web framework
- **PostgreSQL** + SQLAlchemy 2.0 (async) + asyncpg
- **Alembic** - database migrations
- **JWT auth** via python-jose + passlib/bcrypt
- **httpx** - async HTTP client for calling RunPod
- Custom **Quran text matching engine** (n-gram indexing + edit distance)

### Inference Worker (RunPod Serverless)
- **faster-whisper** - CTranslate2-based Whisper inference (4x faster than PyTorch)
- **tarteel-ai/whisper-base-ar-quran** - Whisper Base fine-tuned for Quranic Arabic (74M params, ~5.75% WER)
- **Silero VAD** - voice activity detection (built into faster-whisper)
- Runs on NVIDIA T4 GPU, scales to zero when idle

## Key commands

```bash
# Mobile
npm start               # Start Expo dev server
npm run web             # Start web version
npx expo start --clear  # Start with cache cleared (needed after NativeWind changes)

# Server
cd server
pip install -r requirements.txt
uvicorn app.main:app --reload               # Dev server on :8000
alembic upgrade head                         # Run migrations

# Worker (Docker build for RunPod)
cd worker
docker build -t tanzeel-worker .
```

## Important patterns and conventions

### NativeWind on web
After any change to `tailwind.config.js`, `global.css`, or `metro.config.js`, you MUST restart Metro with `--clear` flag. The NativeWind CSS is compiled by the `withNativeWind` Metro plugin and injected into the JS bundle at build time. Without clearing cache, style changes won't appear.

### expo-audio metering
Use `useAudioRecorderState(recorder, intervalMs)` to get live metering data. Do NOT access `recorder.currentMetering` directly - it doesn't exist in the type definition. The `RecorderState` object returned by the hook contains `{ isRecording, durationMillis, metering, url }`.

### Reanimated v4
Import `SharedValue` as a type: `import { type SharedValue } from 'react-native-reanimated'`. Do NOT use `Animated.SharedValue` - the namespace export doesn't include it in v4.

### Hooks rules in Reanimated
Never call `useSharedValue()` inside `useMemo`, `useEffect`, or loops. If you need multiple shared values for a dynamic list, create one component per item that calls `useSharedValue` at its own top level (see `WaveBarWrapper` pattern in `WaveformVisualizer.tsx`).

### Auth flow
The root layout (`app/_layout.tsx`) gates all navigation:
- `isLoading=true` → render nothing (splash screen stays)
- No auth and not guest → redirect to `/(auth)/login`
- Authenticated or guest → allow `/(tabs)` access
- `loadTokens()` is called on mount to hydrate from `expo-secure-store`

### Arabic text rendering
- Always set `writingDirection: 'rtl'` and `textAlign: 'right'` on Arabic text
- Use `fontFamily: 'Amiri'` for Quranic text with tashkeel (diacritics)
- Android needs larger `lineHeight` multiplier (~2.2x) vs iOS (~1.9x) for proper diacritic spacing
- Per-component RTL, NOT global `I18nManager.forceRTL` (breaks English UI)

### Quran data
- Source: `risan/quran-json` (MIT license) - 114 surahs with nested verses
- Flattened to 6,236 entries in `server/app/data/quran.json`
- Each entry: `{ surah, ayah, text, surah_name_ar, surah_name_en }`
- Text includes full Uthmani tashkeel for display, normalized version used for matching

### Arabic normalization
Both client (`src/utils/arabic.ts`) and server (`server/app/services/arabic_norm.py`) implement identical normalization:
1. Remove tashkeel (diacritics) - Unicode ranges U+0610-061A, U+064B-065F, etc.
2. Remove tatweel (kashida)
3. Normalize alef variants (إأآٱ → ا)
4. Taa marbuta → haa (ة → ه)
5. Alef maqsura → yaa (ى → ي)
6. Hamza carriers → base letter (ؤ → و, ئ → ي)
7. Collapse whitespace

### Matching engine
Two-stage pipeline in `server/app/services/matcher.py`:
1. **Candidate generation**: Word-level trigram overlap against a prebuilt index (53K entries). Returns top 20 candidates.
2. **Precise alignment**: Sliding-window word-level Levenshtein distance. Score = 1 - normalized_edit_distance. Handles partial ayah matches.
Fallback: simple word overlap ratio (Dice coefficient) if n-gram stage returns nothing.

## Known issues / current state

- **NativeWind web styles**: Require Metro cache clear (`--clear`) to take effect. First load after `npm install` may show unstyled content until cache is rebuilt.
- **Audio recording on web**: `expo-audio` recording doesn't work in the browser. The UI renders but microphone capture requires a native build (iOS/Android).
- **`props.pointerEvents` warning**: Comes from React Navigation internals, not our code. Harmless deprecation warning.
- **RunPod worker**: Not yet deployed. The Docker image needs to be built and pushed to a container registry, then configured as a RunPod serverless endpoint. Set `RUNPOD_API_KEY` and `RUNPOD_ENDPOINT_ID` in `server/.env`.
- **Database**: Migrations written but not yet applied. Needs a running PostgreSQL instance. Set `DATABASE_URL` in `server/.env`.
- **Surah viewer** (`app/surah/[id].tsx`): Shows metadata only, full ayah text loading from API not yet implemented.

## Environment variables

### Server (`server/.env`)
```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/tanzeel
JWT_SECRET_KEY=<random-secret>
RUNPOD_API_KEY=<your-key>
RUNPOD_ENDPOINT_ID=<your-endpoint>
```

### Mobile (`.env` or `app.json`)
```
EXPO_PUBLIC_API_URL=http://localhost:8000
```
