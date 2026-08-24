import { useCallback, useState } from "react";
import {
  View,
  Text,
  FlatList,
  Pressable,
  TextInput,
  StyleSheet,
} from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { api } from "../api/client";
import { colors } from "../theme";

export default function WatchlistDetailScreen({ route, navigation }) {
  const { name } = route.params;
  const [symbols, setSymbols] = useState([]);
  const [quotes, setQuotes] = useState({});
  const [newSymbol, setNewSymbol] = useState("");

  const load = useCallback(async () => {
    const lists = await api.getWatchlists();
    setSymbols(lists[name] || []);
    const q = await api.watchlistQuotes(name);
    setQuotes(q);
  }, [name]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  const addSymbol = async () => {
    if (!newSymbol.trim()) return;
    await api.addSymbol(name, newSymbol.trim().toUpperCase());
    setNewSymbol("");
    load();
  };

  const removeSymbol = async (symbol) => {
    await api.removeSymbol(name, symbol);
    load();
  };

  return (
    <View style={styles.container}>
      <View style={styles.addRow}>
        <TextInput
          style={styles.input}
          placeholder="Add symbol (e.g. AAPL)"
          placeholderTextColor={colors.muted}
          autoCapitalize="characters"
          value={newSymbol}
          onChangeText={setNewSymbol}
          onSubmitEditing={addSymbol}
        />
        <Pressable style={styles.addBtn} onPress={addSymbol}>
          <Text style={styles.addBtnText}>Add</Text>
        </Pressable>
      </View>

      <FlatList
        data={symbols}
        keyExtractor={(s) => s}
        renderItem={({ item }) => {
          const snap = quotes[item];
          const price = snap?.latestTrade?.p;
          const prevClose = snap?.prevDailyBar?.c;
          const changePct =
            price && prevClose
              ? (((price - prevClose) / prevClose) * 100).toFixed(2)
              : null;
          return (
            <Pressable
              style={styles.row}
              onPress={() =>
                navigation.navigate("StockDetail", { symbol: item })
              }
              onLongPress={() => removeSymbol(item)}
            >
              <Text style={styles.symbol}>{item}</Text>
              <View style={styles.rowRight}>
                {price != null && (
                  <Text style={styles.price}>${price.toFixed(2)}</Text>
                )}
                {changePct != null && (
                  <Text
                    style={[
                      styles.change,
                      { color: changePct >= 0 ? colors.green : colors.red },
                    ]}
                  >
                    {changePct >= 0 ? "+" : ""}
                    {changePct}%
                  </Text>
                )}
              </View>
            </Pressable>
          );
        }}
        ListEmptyComponent={
          <Text style={styles.empty}>
            No symbols yet — add one above. Long-press a symbol to remove it.
          </Text>
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  addRow: {
    flexDirection: "row",
    padding: 12,
    gap: 8,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
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
  addBtn: {
    backgroundColor: colors.accent,
    borderRadius: 8,
    paddingHorizontal: 16,
    justifyContent: "center",
  },
  addBtnText: { color: "#001320", fontWeight: "700" },
  row: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    padding: 16,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  symbol: { color: colors.text, fontSize: 16, fontWeight: "600" },
  rowRight: { alignItems: "flex-end" },
  price: { color: colors.text, fontSize: 15, fontWeight: "600" },
  change: { fontSize: 13, marginTop: 2 },
  empty: { color: colors.muted, textAlign: "center", marginTop: 40, padding: 20 },
});
