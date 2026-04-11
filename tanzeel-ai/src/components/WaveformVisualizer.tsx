import React, { useEffect, useRef } from "react";
import { View } from "react-native";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withTiming,
  type SharedValue,
} from "react-native-reanimated";

interface WaveformVisualizerProps {
  metering: number; // dBFS, typically -160 to 0
  isActive: boolean;
}

const BAR_COUNT = 30;

function WaveBar({ height }: { height: SharedValue<number> }) {
  const animatedStyle = useAnimatedStyle(() => ({
    height: height.value,
  }));

  return (
    <Animated.View
      style={animatedStyle}
      className="mx-0.5 w-1 rounded-full bg-primary-500"
    />
  );
}

function WaveBarWrapper({
  metering,
  isActive,
  index,
}: {
  metering: number;
  isActive: boolean;
  index: number;
}) {
  const height = useSharedValue(4);

  useEffect(() => {
    if (!isActive) {
      height.value = withTiming(4, { duration: 300 });
      return;
    }
    const amplitude = Math.max(0, Math.min(1, (metering + 60) / 60));
    const variance = 0.3 + Math.sin(index * 0.7 + metering * 0.1) * 0.35 + 0.35;
    const targetHeight = 4 + amplitude * 40 * variance;
    height.value = withTiming(targetHeight, { duration: 100 });
  }, [metering, isActive]);

  return <WaveBar height={height} />;
}

const barIndices = Array.from({ length: BAR_COUNT }, (_, i) => i);

export function WaveformVisualizer({ metering, isActive }: WaveformVisualizerProps) {
  return (
    <View className="h-12 flex-row items-center justify-center">
      {barIndices.map((i) => (
        <WaveBarWrapper key={i} metering={metering} isActive={isActive} index={i} />
      ))}
    </View>
  );
}
