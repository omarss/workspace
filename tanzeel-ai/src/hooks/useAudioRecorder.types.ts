export interface UseRecorderOptions {
  onAutoStop?: (uri: string) => void;
}

export interface UseRecorderReturn {
  isRecording: boolean;
  durationMs: number;
  metering: number;
  startRecording: () => Promise<void>;
  stopRecording: () => Promise<string | null>;
  error: string | null;
  /** True when recording is supported on this platform */
  isSupported: boolean;
}
