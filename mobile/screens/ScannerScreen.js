import { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  FlatList,
  RefreshControl,
  Pressable,
  StyleSheet,
  ActivityIndicator,
} from "react-native";
import { api } from "../api/client";
import { colors } from "../theme";

export default function ScannerScreen({ navigation }) {
  const [candidates, setCandidates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const data = await api.scan();
      setCandidates(data.candidates || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const onRefresh = () => {
    setRefreshing(true);
    load();
  };

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Text style={styles.disclaimer}>
        Ranked by volume surge, momentum & range. A screener, not a
        prediction — use your own judgment.
      </Text>
      {error && <Text style={styles.error}>{error}</Text>}
      <FlatList
        data={candidates}
        keyExtractor={(item) => item.symbol}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
        }
        renderItem={({ item, index }) => (
          <Pressable
            style={styles.row}
            onPress={() =>
              navigation.navigate("StockDetail", { symbol: item.symbol })
            }
          >
            <Text style={styles.rank}>{index + 1}</Text>
            <View style={styles.rowMain}>
              <Text style={styles.symbol}>{item.symbol}</Text>
              <Text style={styles.sub}>
                RVOL {item.rvol}x · Range {item.rangePct}%
              </Text>
            </View>
            <View style={styles.rowRight}>
              <Text style={styles.price}>${item.price.toFixed(2)}</Text>
              <Text
                style={[
                  styles.change,
                  { color: item.changePct >= 0 ? colors.green : colors.red },
                ]}
              >
                {item.changePct >= 0 ? "+" : ""}
                {item.changePct}%
              </Text>
            </View>
          </Pressable>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  center: {
    flex: 1,
    backgroundColor: colors.bg,
    justifyContent: "center",
    alignItems: "center",
  },
  disclaimer: {
    color: colors.muted,
    fontSize: 12,
    padding: 12,
    paddingBottom: 4,
  },
  error: { color: colors.red, padding: 12 },
  row: {
    flexDirection: "row",
    alignItems: "center",
    padding: 14,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  rank: { color: colors.muted, width: 28, fontSize: 13 },
  rowMain: { flex: 1 },
  symbol: { color: colors.text, fontSize: 16, fontWeight: "600" },
  sub: { color: colors.muted, fontSize: 12, marginTop: 2 },
  rowRight: { alignItems: "flex-end" },
  price: { color: colors.text, fontSize: 15, fontWeight: "600" },
  change: { fontSize: 13, marginTop: 2 },
});
