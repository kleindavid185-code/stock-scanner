import { NavigationContainer, DarkTheme } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import { StatusBar } from "expo-status-bar";
import { View, Text, Pressable, StyleSheet } from "react-native";
import { useState } from "react";

import ScannerScreen from "./screens/ScannerScreen";
import WatchlistsScreen from "./screens/WatchlistsScreen";
import AISearchScreen from "./screens/AISearchScreen";
import WatchlistDetailScreen from "./screens/WatchlistDetailScreen";
import StockDetailScreen from "./screens/StockDetailScreen";
import { colors } from "./theme";

const Stack = createNativeStackNavigator();

const navTheme = {
  ...DarkTheme,
  colors: {
    ...DarkTheme.colors,
    background: colors.bg,
    card: colors.card,
    text: colors.text,
    border: colors.border,
    primary: colors.accent,
  },
};

// Simple top-level tab switcher (Scanner / Watchlists) implemented by hand
// to avoid pulling in @react-navigation/bottom-tabs as an extra dependency
// -- easy to swap for real tabs later if you want.
function Home({ navigation }) {
  const [tab, setTab] = useState("scanner");
  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <View style={styles.tabBar}>
        <Pressable onPress={() => setTab("scanner")} style={styles.tabBtn}>
          <Text style={[styles.tabText, tab === "scanner" && styles.tabTextActive]}>
            Scanner
          </Text>
        </Pressable>
        <Pressable onPress={() => setTab("aisearch")} style={styles.tabBtn}>
          <Text style={[styles.tabText, tab === "aisearch" && styles.tabTextActive]}>
            AI Search
          </Text>
        </Pressable>
        <Pressable onPress={() => setTab("watchlists")} style={styles.tabBtn}>
          <Text style={[styles.tabText, tab === "watchlists" && styles.tabTextActive]}>
            Watchlists
          </Text>
        </Pressable>
      </View>
      {tab === "scanner" && <ScannerScreen navigation={navigation} />}
      {tab === "aisearch" && <AISearchScreen navigation={navigation} />}
      {tab === "watchlists" && <WatchlistsScreen navigation={navigation} />}
    </View>
  );
}

export default function App() {
  return (
    <NavigationContainer theme={navTheme}>
      <StatusBar style="light" />
      <Stack.Navigator screenOptions={{ headerStyle: { backgroundColor: colors.card } }}>
        <Stack.Screen name="Home" component={Home} options={{ title: "Market Scanner" }} />
        <Stack.Screen
          name="WatchlistDetail"
          component={WatchlistDetailScreen}
          options={({ route }) => ({ title: route.params.name })}
        />
        <Stack.Screen
          name="StockDetail"
          component={StockDetailScreen}
          options={({ route }) => ({ title: route.params.symbol })}
        />
      </Stack.Navigator>
    </NavigationContainer>
  );
}

const styles = StyleSheet.create({
  tabBar: {
    flexDirection: "row",
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  tabBtn: { flex: 1, paddingVertical: 14, alignItems: "center" },
  tabText: { color: colors.muted, fontWeight: "600" },
  tabTextActive: { color: colors.accent },
});
