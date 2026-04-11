import React, { useState } from "react";
import {
  View,
  Text,
  TextInput,
  Pressable,
  KeyboardAvoidingView,
  Platform,
  ActivityIndicator,
} from "react-native";
import { useTranslation } from "react-i18next";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { useAuth } from "../../src/hooks/useAuth";

export default function RegisterScreen() {
  const { t } = useTranslation();
  const router = useRouter();
  const { register } = useAuth();

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const canSubmit =
    name.trim().length > 0 &&
    email.trim().length > 0 &&
    password.length > 0 &&
    confirmPassword.length > 0;

  const handleRegister = async () => {
    if (!name.trim()) {
      setError(t("auth.nameRequired"));
      return;
    }
    if (!email.trim()) {
      setError(t("auth.emailRequired"));
      return;
    }
    if (!password) {
      setError(t("auth.passwordRequired"));
      return;
    }
    if (password !== confirmPassword) {
      setError(t("auth.passwordsDoNotMatch"));
      return;
    }
    setError("");
    setLoading(true);
    try {
      await register(name.trim(), email.trim(), password);
    } catch {
      setError(t("auth.registerError"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView className="flex-1 bg-white dark:bg-slate-900">
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : "height"}
        className="flex-1 justify-center px-6"
      >
        {/* Header */}
        <View className="mb-10 items-center">
          <Text className="text-4xl font-bold text-primary-600">
            {t("common.appName")}
          </Text>
          <Text className="mt-2 text-gray-500 dark:text-gray-400">
            {t("auth.register")}
          </Text>
        </View>

        {/* Form */}
        <View className="gap-4">
          <TextInput
            placeholder={t("auth.name")}
            value={name}
            onChangeText={setName}
            className="rounded-xl border border-gray-300 bg-gray-50 px-4 py-4 text-base text-gray-900 dark:border-gray-600 dark:bg-slate-800 dark:text-white"
            placeholderTextColor="#9ca3af"
          />
          <TextInput
            placeholder={t("auth.email")}
            value={email}
            onChangeText={setEmail}
            autoCapitalize="none"
            keyboardType="email-address"
            className="rounded-xl border border-gray-300 bg-gray-50 px-4 py-4 text-base text-gray-900 dark:border-gray-600 dark:bg-slate-800 dark:text-white"
            placeholderTextColor="#9ca3af"
          />
          <TextInput
            placeholder={t("auth.password")}
            value={password}
            onChangeText={setPassword}
            secureTextEntry
            className="rounded-xl border border-gray-300 bg-gray-50 px-4 py-4 text-base text-gray-900 dark:border-gray-600 dark:bg-slate-800 dark:text-white"
            placeholderTextColor="#9ca3af"
          />
          <TextInput
            placeholder={t("auth.confirmPassword")}
            value={confirmPassword}
            onChangeText={setConfirmPassword}
            secureTextEntry
            className="rounded-xl border border-gray-300 bg-gray-50 px-4 py-4 text-base text-gray-900 dark:border-gray-600 dark:bg-slate-800 dark:text-white"
            placeholderTextColor="#9ca3af"
          />

          {error ? (
            <Text className="text-center text-sm text-red-500">{error}</Text>
          ) : null}

          <Pressable
            onPress={handleRegister}
            disabled={loading || !canSubmit}
            className={`items-center rounded-xl py-4 ${canSubmit ? "bg-primary-600 active:bg-primary-700" : "bg-gray-300 dark:bg-gray-700"}`}
          >
            {loading ? (
              <ActivityIndicator color="white" />
            ) : (
              <Text className="text-base font-semibold text-white">
                {t("auth.register")}
              </Text>
            )}
          </Pressable>
        </View>

        {/* Footer */}
        <View className="mt-6 items-center">
          <Pressable onPress={() => router.back()}>
            <Text className="text-primary-600 dark:text-primary-400">
              {t("auth.hasAccount")}{" "}
              <Text className="font-semibold">{t("auth.login")}</Text>
            </Text>
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
