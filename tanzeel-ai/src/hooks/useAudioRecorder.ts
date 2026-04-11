import { useState, useRef, useCallback, useEffect } from "react";
import {
  useAudioRecorder,
  useAudioRecorderState,
  RecordingPresets,
  AudioModule,
} from "expo-audio";
import { AUDIO_CONFIG } from "../constants/config";
import type { UseRecorderOptions, UseRecorderReturn } from "./useAudioRecorder.types";

export type { UseRecorderOptions, UseRecorderReturn };

export function useRecorder(options?: UseRecorderOptions): UseRecorderReturn {
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const recorderState = useAudioRecorderState(recorder, 100);
  const [error, setError] = useState<string | null>(null);
  const autoStopRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onAutoStopRef = useRef(options?.onAutoStop);
  onAutoStopRef.current = options?.onAutoStop;

  // Clean up auto-stop timer on unmount
  useEffect(() => {
    return () => {
      if (autoStopRef.current) {
        clearTimeout(autoStopRef.current);
      }
    };
  }, []);

  const startRecording = useCallback(async () => {
    try {
      setError(null);
      const status = await AudioModule.requestRecordingPermissionsAsync();
      if (!status.granted) {
        setError("Microphone permission is required");
        return;
      }

      await AudioModule.setAudioModeAsync({
        allowsRecording: true,
        playsInSilentMode: true,
      });

      // Clear any lingering timer from a previous recording
      if (autoStopRef.current) {
        clearTimeout(autoStopRef.current);
        autoStopRef.current = null;
      }

      recorder.record();

      // Auto-stop after max duration, then trigger recognition via callback
      autoStopRef.current = setTimeout(async () => {
        if (recorder.isRecording) {
          await recorder.stop();
          const uri = recorder.uri;
          if (uri && onAutoStopRef.current) {
            onAutoStopRef.current(uri);
          }
        }
      }, AUDIO_CONFIG.maxDurationMs);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start recording");
    }
  }, [recorder]);

  const stopRecording = useCallback(async (): Promise<string | null> => {
    try {
      if (autoStopRef.current) {
        clearTimeout(autoStopRef.current);
        autoStopRef.current = null;
      }
      await recorder.stop();
      return recorder.uri;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to stop recording");
      return null;
    }
  }, [recorder]);

  return {
    isRecording: recorderState.isRecording,
    durationMs: recorderState.durationMillis,
    metering: recorderState.metering ?? -160,
    startRecording,
    stopRecording,
    error,
    isSupported: true,
  };
}
