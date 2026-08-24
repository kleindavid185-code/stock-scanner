import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";

export default function WatchlistsPage() {
  const navigate = useNavigate();
  const [lists, setLists] = useState({});
  const [newName, setNewName] = useState("");

  const load = useCallback(async () => {
    const data = await api.getWatchlists();
    setLists(data);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const createList = async () => {
    if (!newName.trim()) return;
    await api.createWatchlist(newName.trim());
    setNewName("");
    load();
  };

  const names = Object.keys(lists);

  return (
    <div className="page">
      <div className="form-row">
        <input
          className="text-input"
          placeholder="New watchlist name"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && createList()}
        />
        <button className="btn" onClick={createList}>
          Add
        </button>
      </div>

      <ul className="list list--dense">
        {names.map((name) => (
          <li
            key={name}
            className="list-row"
            onClick={() => navigate(`/watchlists/${encodeURIComponent(name)}`)}
          >
            <div className="symbol">{name}</div>
            <div className="sub">
              <span className="mono">{lists[name].length}</span> symbols
            </div>
          </li>
        ))}
      </ul>
      {!names.length && (
        <div className="empty">No watchlists yet — create one above.</div>
      )}
    </div>
  );
}
