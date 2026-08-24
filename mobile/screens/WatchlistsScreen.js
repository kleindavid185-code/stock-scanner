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

export default function WatchlistsScreen({ navigation }) {
  const [lists, setLists] = useState({});
  const [newName, setNewName] = useState("");

  const load = useCallback(async () => {
    const data = await api.getWatchlists();
    setLists(data);
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  const createList = async () => {
    if (!newName.trim()) return;
    await api.createWatchlist(newName.trim());
    setNewName("");
    load();
  };

  const names = Object.keys(lists);

  return (
    <View style={styles.container}>
      <View style={styles.createRow}>
        <TextInput
          style={styles.input}
          placeholder="New watchlist name"
          placeholderTextColor={colors.muted}
          value={newName}
          onChangeText={setNewName}
          onSubmitEditing={createList}
        />
        <Pressable style={styles.createBtn} onPress={createList}>
          <Text style={styles.createBtnText}>Add</Text>
        </Pressable>
      </View>

      <FlatList
        data={names}
        keyExtractor={(n) => n}
        renderItem={({ item }) => (
          <Pressable
            style={styles.row}
            onPress={() =>
              navigation.navigate("WatchlistDetail", { name: item })
            }
          >
            <Text style={styles.name}>{item}</Text>
            <Text style={styles.count}>{lists[item].length} symbols</Text>
          </Pressable>
        )}
        ListEmptyComponent={
          <Text style={styles.empty}>No watchlists yet — create one above.</Text>
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  createRow: {
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
  createBtn: {
    backgroundColor: colors.accent,
    borderRadius: 8,
    paddingHorizontal: 16,
    justifyContent: "center",
  },
  createBtnText: { color: "#001320", fontWeight: "700" },
  row: {
    flexDirection: "row",
    justifyContent: "space-between",
    padding: 16,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  name: { color: colors.text, fontSize: 16, fontWeight: "600" },
  count: { color: colors.muted, fontSize: 13 },
  empty: { color: colors.muted, textAlign: "center", marginTop: 40 },
});
