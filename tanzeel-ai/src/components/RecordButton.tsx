import React from "react";
import { Platform, Pressable, View, Text } from "react-native";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withRepeat,
  withTiming,
  withSequence,
  Easing,
} from "react-native-reanimated";
import * as Haptics from "expo-haptics";
import { useTranslation } from "react-i18next";

interface RecordButtonProps {
  isRecording: boolean;
  onPress: () => void;
  disabled?: boolean;
}

const AnimatedPressable = Animated.createAnimatedComponent(Pressable);

export function RecordButton({ isRecording, onPress, disabled }: RecordButtonProps) {
  const { t } = useTranslation();
  const scale = useSharedValue(1);
  const pulseScale = useSharedValue(1);
  const pulseOpacity = useSharedValue(0);

  React.useEffect(() => {
    if (isRecording) {
      pulseScale.value = withRepeat(
        withTiming(1.8, { duration: 1200, easing: Easing.out(Easing.ease) }),
        -1,
        false
      );
      pulseOpacity.value = withRepeat(
        withSequence(
          withTiming(0.4, { duration: 0 }),
          withTiming(0, { duration: 1200, easing: Easing.out(Easing.ease) })
        ),
        -1,
        false
      );
    } else {
      pulseScale.value = withTiming(1, { duration: 300 });
      pulseOpacity.value = withTiming(0, { duration: 300 });
    }
  }, [isRecording]);

  const buttonStyle = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
  }));

  const pulseStyle = useAnimatedStyle(() => ({
    transform: [{ scale: pulseScale.value }],
    opacity: pulseOpacity.value,
  }));

  return (
    <View className="items-center justify-center">
      {/* Pulse ring */}
      <Animated.View
        style={pulseStyle}
        className="absolute h-36 w-36 rounded-full bg-primary-500"
      />

      {/* Main button - 144px for child-friendly tap target */}
      <AnimatedPressable
        style={buttonStyle}
        onPressIn={() => {
          scale.value = withTiming(0.92, { duration: 100 });
        }}
        onPressOut={() => {
          scale.value = withTiming(1, { duration: 100 });
        }}
        onPress={() => {
          if (Platform.OS !== "web") {
            try {
              Haptics.impactAsync(
                isRecording
                  ? Haptics.ImpactFeedbackStyle.Medium
                  : Haptics.ImpactFeedbackStyle.Heavy
              );
            } catch {
              // Haptics not available on this device — ignore
            }
          }
          onPress();
        }}
        disabled={disabled}
        accessibilityRole="button"
        accessibilityLabel={
          isRecording ? t("accessibility.stopRecording") : t("accessibility.startRecording")
        }
        accessibilityHint={t("accessibility.recordButtonHint")}
        accessibilityState={{ disabled: !!disabled }}
        className={`h-36 w-36 items-center justify-center rounded-full shadow-lg ${
          isRecording ? "bg-red-500" : "bg-primary-600"
        } ${disabled ? "opacity-50" : ""}`}
      >
        <View
          className={`h-14 w-14 ${
            isRecording ? "rounded-lg" : "rounded-full"
          } bg-white`}
        />
      </AnimatedPressable>

      {/* Label */}
      <Text className="mt-6 text-center text-base text-gray-600 dark:text-gray-400">
        {isRecording ? t("recite.recording") : t("recite.tapToRecord")}
      </Text>
    </View>
  );
}
