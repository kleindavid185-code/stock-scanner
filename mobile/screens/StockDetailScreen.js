import { useEffect, useState } from "react";
import { View, Text, ScrollView, StyleSheet, ActivityIndicator } from "react-native";
import { api } from "../api/client";
import { colors } from "../theme";

export default function StockDetailScreen({ route }) {
  const { symbol } = route.params;
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .quote(symbol)
      .then(setData)
      .finally(() => setLoading(false));
  }, [symbol]);

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  }

  const snap = data?.snapshot;
  const price = snap?.latestTrade?.p;
  const prevClose = snap?.prevDailyBar?.c;
  const changePct =
    price && prevClose ? (((price - prevClose) / prevClose) * 100).toFixed(2) : null;

  return (
    <ScrollView style={styles.container}>
      <Text style={styles.symbol}>{symbol}</Text>
      {price != null && (
        <View style={styles.priceRow}>
          <Text style={styles.price}>${price.toFixed(2)}</Text>
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
      )}

      {snap?.dailyBar && (
        <View style={styles.statsGrid}>
          <Stat label="Open" value={snap.dailyBar.o?.toFixed(2)} />
          <Stat label="High" value={snap.dailyBar.h?.toFixed(2)} />
          <Stat label="Low" value={snap.dailyBar.l?.toFixed(2)} />
          <Stat label="Volume" value={snap.dailyBar.v?.toLocaleString()} />
        </View>
      )}

      <Text style={styles.sectionTitle}>Recent daily bars</Text>
      {(data?.bars || []).slice().reverse().map((bar, i) => (
        <View key={i} style={styles.barRow}>
          <Text style={styles.barDate}>{bar.t?.slice(0, 10)}</Text>
          <Text style={styles.barText}>
            O {bar.o?.toFixed(2)} H {bar.h?.toFixed(2)} L {bar.l?.toFixed(2)} C{" "}
            {bar.c?.toFixed(2)}
          </Text>
        </View>
      ))}
    </ScrollView>
  );
}

function Stat({ label, value }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statLabel}>{label}</Text>
      <Text style={styles.statValue}>{value ?? "—"}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg, padding: 16 },
  center: {
    flex: 1,
    backgroundColor: colors.bg,
    justifyContent: "center",
    alignItems: "center",
  },
  symbol: { color: colors.text, fontSize: 26, fontWeight: "700" },
  priceRow: { flexDirection: "row", alignItems: "baseline", gap: 10, marginTop: 6 },
  price: { color: colors.text, fontSize: 20, fontWeight: "600" },
  change: { fontSize: 15 },
  statsGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    marginTop: 20,
    gap: 12,
  },
  stat: {
    backgroundColor: colors.card,
    borderRadius: 10,
    padding: 12,
    width: "47%",
    borderWidth: 1,
    borderColor: colors.border,
  },
  statLabel: { color: colors.muted, fontSize: 12 },
  statValue: { color: colors.text, fontSize: 16, fontWeight: "600", marginTop: 4 },
  sectionTitle: {
    color: colors.text,
    fontSize: 16,
    fontWeight: "600",
    marginTop: 28,
    marginBottom: 8,
  },
  barRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  barDate: { color: colors.muted, fontSize: 12 },
  barText: { color: colors.text, fontSize: 12 },
});
