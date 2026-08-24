import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";

// Small "add to watchlist" control: click to open a menu of existing
// watchlists, pick one to add `symbol` to it. Reuses api.getWatchlists /
// api.addSymbol — the same calls WatchlistsPage and WatchlistDetailPage
// already use — rather than any new watchlist-mutation logic.
export default function AddToWatchlistButton({ symbol }) {
  const [open, setOpen] = useState(false);
  const [watchlists, setWatchlists] = useState(null);
  const [addingTo, setAddingTo] = useState(null);
  const [addedTo, setAddedTo] = useState(null);
  const containerRef = useRef(null);

  useEffect(() => {
    if (!open || watchlists) return;
    api.getWatchlists().then((data) => setWatchlists(Object.keys(data)));
  }, [open, watchlists]);

  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  const handleAdd = async (name) => {
    setAddingTo(name);
    try {
      await api.addSymbol(name, symbol);
      setAddedTo(name);
      setTimeout(() => setAddedTo(null), 1800);
    } finally {
      setAddingTo(null);
      setOpen(false);
    }
  };

  return (
    <div className="add-watchlist" ref={containerRef} onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        className={`add-watchlist-btn${addedTo ? " added" : ""}`}
        onClick={() => setOpen((v) => !v)}
      >
        {addedTo ? `✓ Added to ${addedTo}` : "+ Watchlist"}
      </button>
      {open && (
        <div className="add-watchlist-menu">
          {watchlists === null && <div className="add-watchlist-empty">Loading…</div>}
          {watchlists?.length === 0 && (
            <div className="add-watchlist-empty">No watchlists yet</div>
          )}
          {watchlists?.map((name) => (
            <button
              key={name}
              type="button"
              className="add-watchlist-option"
              disabled={addingTo === name}
              onClick={() => handleAdd(name)}
            >
              {name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
