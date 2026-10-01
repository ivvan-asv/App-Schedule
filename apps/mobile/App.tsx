import { StatusBar } from "expo-status-bar";
import { useState } from "react";
import { Pressable, SafeAreaView, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

const API_URL = "http://127.0.0.1:8000/api/v1";

export default function App() {
  const [text, setText] = useState("Agendá mañana a las 15 una reunión con Ana en Palermo");
  const [result, setResult] = useState("");
  const [busy, setBusy] = useState(false);

  async function parseAndSave() {
    setBusy(true);
    try {
      const parsedResponse = await fetch(`${API_URL}/intents/parse`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, timezone: "America/Argentina/Buenos_Aires" }),
      });
      const parsedJson = await parsedResponse.json();
      const eventResponse = await fetch(`${API_URL}/events`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...parsedJson.parsed,
          source_text: text,
          travel_before_minutes: parsedJson.travel_before_minutes,
          commit_to_calendar: true,
        }),
      });
      const eventJson = await eventResponse.json();
      setResult(`Listo: ${eventJson.title} · ${eventJson.start_time}`);
    } catch (error) {
      setResult(error instanceof Error ? error.message : "Error de red");
    } finally {
      setBusy(false);
    }
  }

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.container}>
        <Text style={styles.kicker}>SMART SCHEDULER AI</Text>
        <Text style={styles.title}>Captura de intención</Text>
        <Text style={styles.copy}>
          Esta pantalla es el puente de Expo. App Intents / Quick Settings van a mandar el mismo texto
          transcrito al endpoint /intents/transcribe.
        </Text>
        <TextInput
          style={styles.input}
          multiline
          value={text}
          onChangeText={setText}
        />
        <Pressable style={styles.button} onPress={parseAndSave} disabled={busy}>
          <Text style={styles.buttonText}>{busy ? "Agendando…" : "Interpretar y guardar"}</Text>
        </Pressable>
        {result ? <Text style={styles.result}>{result}</Text> : null}
        <StatusBar style="light" />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#020617" },
  container: { padding: 24, gap: 16 },
  kicker: { color: "#34d399", letterSpacing: 2, fontSize: 12 },
  title: { color: "white", fontSize: 32, fontWeight: "600" },
  copy: { color: "#94a3b8", fontSize: 16, lineHeight: 22 },
  input: {
    minHeight: 120,
    borderColor: "#1e293b",
    borderWidth: 1,
    borderRadius: 16,
    color: "white",
    padding: 16,
    textAlignVertical: "top",
  },
  button: {
    backgroundColor: "#34d399",
    borderRadius: 999,
    paddingVertical: 14,
    alignItems: "center",
  },
  buttonText: { color: "#022c22", fontWeight: "700" },
  result: { color: "#fde68a", fontSize: 16 },
});
