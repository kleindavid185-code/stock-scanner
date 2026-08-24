import { useState } from "react";
import {
  View,
  Text,
  TextInput,
  Pressable,
  FlatList,
  StyleSheet,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import { api } from "../api/client";
import { colors } from "../theme";

const EXAMPLES = [
  "cheap stocks with huge volume today",
  "biggest gap ups this morning",
  "high volatility names under $5",
];

export default function AISearchScreen({ navigation }) {
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [searchedFor, setSearchedFor] = useState(null);

  const runSearch = async (q) => {
    const text = (q ?? query).trim();
    if (!text) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.aiSearch(text);
      setMatches(data.matches || []);
      setSearchedFor(text);
    } catch (e) {
      setError(e.message);
      setMatches(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <Text style={styles.disclaimer}>
        Describe what you're looking for. AI filters today's active-stock
        scan against your description — it can't see anything outside that
        list, and it's not predicting future moves.
      </Text>

      <View style={styles.inputRow}>
        <TextInput
          style={styles.input}
          placeholder="e.g. penny stocks with volume surging"
          placeholderTextColor={colors.muted}
          value={query}
          onChangeText={setQuery}
          onSubmitEditing={() => runSearch()}
          returnKeyType="search"
        />
        <Pressable style={styles.searchBtn} onPress={() => runSearch()}>
          <Text style={styles.searchBtnText}>Go</Text>
        </Pressable>
      </View>

      {!matches && !loading && (
        <View style={styles.examples}>
          <Text style={styles.examplesLabel}>Try asking:</Text>
          {EXAMPLES.map((ex) => (
            <Pressable key={ex} onPress={() => runSearch(ex)}>
              <Text style={styles.exampleChip}>{ex}</Text>
            </Pressable>
          ))}
        </View>
      )}

      {loading && (
        <View style={styles.center}>
          <ActivityIndicator color={colors.accent} />
        </View>
      )}

      {error && <Text style={styles.error}>{error}</Text>}

      {matches && !loading && (
        <FlatList
          data={matches}
          keyExtractor={(item) => item.symbol}
          ListHeaderComponent={
            <Text style={styles.resultsHeader}>
              {matches.length
                ? `${matches.length} match${matches.length === 1 ? "" : "es"} for "${searchedFor}"`
                : `No matches for "${searchedFor}"`}
            </Text>
          }
          renderItem={({ item }) => (
            <Pressable
              style={styles.row}
              onPress={() =>
                navigation.navigate("StockDetail", { symbol: item.symbol })
              }
            >
              <View style={styles.rowTop}>
                <Text style={styles.symbol}>{item.symbol}</Text>
                <View style={styles.rowRight}>
                  <Text style={styles.price}>${item.price.toFixed(2)}</Text>
                  <Text
                    style={[
                      styles.change,
                      {
                        color:
                          item.changePct >= 0 ? colors.green : colors.red,
                      },
                    ]}
                  >
                    {item.changePct >= 0 ? "+" : ""}
                    {item.changePct}%
                  </Text>
                </View>
              </View>
              <Text style={styles.reason}>{item.reason}</Text>
            </Pressable>
          )}
        />
      )}
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  disclaimer: {
    color: colors.muted,
    fontSize: 12,
    padding: 12,
    paddingBottom: 8,
  },
  inputRow: {
    flexDirection: "row",
    paddingHorizontal: 12,
    gap: 8,
    marginBottom: 8,
  },
  input: {
    flex: 1,
    backgroundColor: colors.card,
    color: colors.text,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderWidth: 1,
    borderColor: colors.border,
  },
  searchBtn: {
    backgroundColor: colors.accent,
    borderRadius: 8,
    paddingHorizontal: 18,
    justifyContent: "center",
  },
  searchBtnText: { color: "#001320", fontWeight: "700" },
  examples: { paddingHorizontal: 12, marginTop: 8 },
  examplesLabel: { color: colors.muted, fontSize: 12, marginBottom: 8 },
  exampleChip: {
    color: colors.accent,
    fontSize: 14,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  center: { paddingTop: 30, alignItems: "center" },
  error: { color: colors.red, padding: 12 },
  resultsHeader: {
    color: colors.muted,
    fontSize: 12,
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  row: {
    padding: 14,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  rowTop: { flexDirection: "row", justifyContent: "space-between" },
  symbol: { color: colors.text, fontSize: 16, fontWeight: "600" },
  rowRight: { flexDirection: "row", alignItems: "baseline", gap: 8 },
  price: { color: colors.text, fontSize: 15, fontWeight: "600" },
  change: { fontSize: 13 },
  reason: { color: colors.muted, fontSize: 13, marginTop: 6 },
});
