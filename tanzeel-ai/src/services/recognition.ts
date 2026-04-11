import { Platform } from "react-native";
import api from "./api";
import { RecognitionResult } from "../stores/recitationStore";

export interface ProgressSummary {
  total_recitations: number;
  unique_ayat: number;
  current_streak: number;
  today_count: number;
}

export async function recognizeAudio(fileUri: string): Promise<RecognitionResult> {
  const formData = new FormData();

  if (Platform.OS === "web") {
    // Web: fileUri is a blob URL — fetch the blob and wrap as File
    const resp = await fetch(fileUri);
    if (!resp.ok) {
      throw new Error("Failed to read recorded audio");
    }
    const blob = await resp.blob();
    const ext = blob.type.includes("webm") ? "webm" : blob.type.includes("ogg") ? "ogg" : "wav";
    const mimeType = blob.type || "audio/webm";
    formData.append("file", new File([blob], `recitation.${ext}`, { type: mimeType }));
  } else {
    // Native: React Native FormData accepts { uri, name, type }
    formData.append("file", {
      uri: fileUri,
      name: "recitation.m4a",
      type: "audio/m4a",
    } as unknown as Blob);
  }

  const { data } = await api.post<RecognitionResult>("/api/recognize", formData, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 60_000,
  });

  return data;
}

export async function getRecitationHistory(
  page: number = 1,
  limit: number = 20
): Promise<RecognitionResult[]> {
  const { data } = await api.get<RecognitionResult[]>("/api/progress/history", {
    params: { page, limit },
  });
  return data;
}

export async function getProgressSummary(): Promise<ProgressSummary> {
  const { data } = await api.get<ProgressSummary>("/api/progress/summary");
  return data;
}
