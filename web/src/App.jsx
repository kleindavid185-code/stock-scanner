import { HashRouter, Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import ScannerPage from "./pages/ScannerPage";
import WatchlistsPage from "./pages/WatchlistsPage";
import WatchlistDetailPage from "./pages/WatchlistDetailPage";
import AISearchPage from "./pages/AISearchPage";
import StockDetailPage from "./pages/StockDetailPage";
import SignalsPage from "./pages/SignalsPage";
import EarningsPage from "./pages/EarningsPage";

export default function App() {
  return (
    <HashRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<ScannerPage />} />
          <Route path="/watchlists" element={<WatchlistsPage />} />
          <Route path="/watchlists/:name" element={<WatchlistDetailPage />} />
          <Route path="/ai-search" element={<AISearchPage />} />
          <Route path="/signals" element={<SignalsPage />} />
          <Route path="/earnings" element={<EarningsPage />} />
          <Route path="/stock/:symbol" element={<StockDetailPage />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}
