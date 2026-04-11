import React from "react";
import { View, Text, ScrollView, ActivityIndicator, Pressable } from "react-native";
import { useTranslation } from "react-i18next";
import { SafeAreaView } from "react-native-safe-area-context";
import { RecordButton } from "../../src/components/RecordButton";
import { WaveformVisualizer } from "../../src/components/WaveformVisualizer";
import { ResultCard } from "../../src/components/ResultCard";
import { useRecorder } from "../../src/hooks/useAudioRecorder";
import { useRecognition } from "../../src/hooks/useRecognition";
import { useRecitationStore } from "../../src/stores/recitationStore";

export default function ReciteScreen() {
  const { t } = useTranslation();
  const { recognize, reset } = useRecognition();
  const { isRecording, metering, startRecording, stopRecording, error: recorderError } =
    useRecorder({
      onAutoStop: (uri) => recognize(uri),
    });
  const { status, currentResult, error: recognitionError } = useRecitationStore();

  const handlePress = async () => {
    if (isRecording) {
      const uri = await stopRecording();
      if (uri) {
        await recognize(uri);
      }
    } else {
      reset();
      await startRecording();
    }
  };

  const error = recorderError || recognitionError;

  return (
    <SafeAreaView className="flex-1 bg-white dark:bg-slate-900" edges={["top"]}>
      <ScrollView
        className="flex-1"
        contentContainerClassName="flex-grow justify-center px-5 py-8"
      >
        {/* Waveform */}
        <View className="mb-8">
          <WaveformVisualizer metering={metering} isActive={isRecording} />
        </View>

        {/* Record Button */}
        <View className="items-center">
          <RecordButton
            isRecording={isRecording}
            onPress={handlePress}
            disabled={status === "processing"}
          />
        </View>

        {/* Processing indicator */}
        {status === "processing" && (
          <View className="mt-8 items-center">
            <ActivityIndicator size="large" color="#10b981" />
            <Text className="mt-3 text-base text-gray-500 dark:text-gray-400">
              {t("recite.processing")}
            </Text>
          </View>
        )}

        {/* Error */}
        {error && (
          <View className="mt-6 rounded-xl bg-red-50 p-4 dark:bg-red-950">
            <Text className="text-center text-red-600 dark:text-red-400">
              {error}
            </Text>
          </View>
        )}

        {/* Results */}
        {status === "done" && currentResult && (
          <View className="mt-8 gap-4">
            <Text className="text-xl font-bold text-gray-900 dark:text-white">
              {t("recite.result")}
            </Text>

            {currentResult.top_match ? (
              <>
                <ResultCard match={currentResult.top_match} isTopMatch />

                {currentResult.alternatives.length > 0 && (
                  <>
                    <Text className="mt-2 text-sm font-semibold text-gray-500 dark:text-gray-400">
                      {t("recite.alternatives")}
                    </Text>
                    {currentResult.alternatives.map((alt, i) => (
                      <ResultCard key={i} match={alt} />
                    ))}
                  </>
                )}
              </>
            ) : (
              <View className="rounded-xl bg-yellow-50 p-4 dark:bg-yellow-950">
                <Text className="text-center text-yellow-700 dark:text-yellow-300">
                  {t("recite.noMatch")}
                </Text>
              </View>
            )}

            <Pressable
              onPress={() => reset()}
              className="mt-4 items-center rounded-xl bg-primary-600 py-3 active:bg-primary-700"
            >
              <Text className="font-semibold text-white">
                {t("recite.tryAgain")}
              </Text>
            </Pressable>
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
