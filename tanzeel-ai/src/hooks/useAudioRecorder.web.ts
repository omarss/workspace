import { useState, useRef, useCallback, useEffect } from "react";
import { AUDIO_CONFIG } from "../constants/config";
import type { UseRecorderOptions, UseRecorderReturn } from "./useAudioRecorder.types";

export type { UseRecorderOptions, UseRecorderReturn };

/**
 * Web implementation using MediaRecorder + AnalyserNode for metering.
 * Produces a webm/opus blob (widely supported by browsers and by faster-whisper).
 */
export function useRecorder(options?: UseRecorderOptions): UseRecorderReturn {
  const [isRecording, setIsRecording] = useState(false);
  const [durationMs, setDurationMs] = useState(0);
  const [metering, setMetering] = useState(-160);
  const [error, setError] = useState<string | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const rafRef = useRef<number>(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const autoStopRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startTimeRef = useRef(0);
  const onAutoStopRef = useRef(options?.onAutoStop);
  onAutoStopRef.current = options?.onAutoStop;

  // Clean up on unmount
  useEffect(() => {
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      if (timerRef.current) clearInterval(timerRef.current);
      if (autoStopRef.current) clearTimeout(autoStopRef.current);
      streamRef.current?.getTracks().forEach((t) => t.stop());
      audioCtxRef.current?.close();
    };
  }, []);

  const updateMetering = useCallback(() => {
    const analyser = analyserRef.current;
    if (!analyser) return;

    const data = new Float32Array(analyser.fftSize);
    analyser.getFloatTimeDomainData(data);

    // RMS → dBFS (clamped to -160..0)
    let sum = 0;
    for (let i = 0; i < data.length; i++) {
      sum += data[i] * data[i];
    }
    const rms = Math.sqrt(sum / data.length);
    const db = rms > 0 ? 20 * Math.log10(rms) : -160;
    setMetering(Math.max(-160, Math.min(0, db)));

    rafRef.current = requestAnimationFrame(updateMetering);
  }, []);

  const buildBlobUrl = useCallback((chunks: Blob[], mimeType: string): string => {
    const blob = new Blob(chunks, { type: mimeType });
    return URL.createObjectURL(blob);
  }, []);

  const stopInternal = useCallback((): Promise<string | null> => {
    return new Promise((resolve) => {
      const recorder = mediaRecorderRef.current;
      if (!recorder || recorder.state === "inactive") {
        resolve(null);
        return;
      }

      // Clear timers
      if (autoStopRef.current) {
        clearTimeout(autoStopRef.current);
        autoStopRef.current = null;
      }
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = 0;
      }

      recorder.onstop = () => {
        const url = buildBlobUrl(chunksRef.current, recorder.mimeType);
        chunksRef.current = [];

        // Stop mic stream
        streamRef.current?.getTracks().forEach((t) => t.stop());
        streamRef.current = null;

        // Close audio context
        audioCtxRef.current?.close();
        audioCtxRef.current = null;
        analyserRef.current = null;

        setIsRecording(false);
        setMetering(-160);
        resolve(url);
      };

      recorder.stop();
    });
  }, [buildBlobUrl]);

  const startRecording = useCallback(async () => {
    let stream: MediaStream | null = null;
    let audioCtx: AudioContext | null = null;
    try {
      setError(null);

      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: AUDIO_CONFIG.sampleRate,
          channelCount: AUDIO_CONFIG.channels,
          echoCancellation: false,
          noiseSuppression: false,
        },
      });
      streamRef.current = stream;

      // Set up AnalyserNode for metering
      audioCtx = new AudioContext();
      audioCtxRef.current = audioCtx;
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 2048;
      source.connect(analyser);
      analyserRef.current = analyser;

      // Pick best supported mime type
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : MediaRecorder.isTypeSupported("audio/webm")
          ? "audio/webm"
          : "";

      chunksRef.current = [];
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.start(250); // collect chunks every 250ms
      startTimeRef.current = Date.now();
      setIsRecording(true);

      // Duration timer
      timerRef.current = setInterval(() => {
        setDurationMs(Date.now() - startTimeRef.current);
      }, 100);

      // Start metering loop
      rafRef.current = requestAnimationFrame(updateMetering);

      // Auto-stop after max duration
      autoStopRef.current = setTimeout(async () => {
        const url = await stopInternal();
        if (url && onAutoStopRef.current) {
          onAutoStopRef.current(url);
        }
      }, AUDIO_CONFIG.maxDurationMs);
    } catch (e) {
      // Clean up acquired resources on failure
      stream?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      audioCtx?.close();
      audioCtxRef.current = null;
      analyserRef.current = null;

      const msg =
        e instanceof DOMException && e.name === "NotAllowedError"
          ? "Microphone permission is required"
          : e instanceof Error
            ? e.message
            : "Failed to start recording";
      setError(msg);
    }
  }, [updateMetering, stopInternal]);

  const stopRecording = useCallback(async (): Promise<string | null> => {
    return stopInternal();
  }, [stopInternal]);

  return {
    isRecording,
    durationMs,
    metering,
    startRecording,
    stopRecording,
    error,
    isSupported: true,
  };
}
