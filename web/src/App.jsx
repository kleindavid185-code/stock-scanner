import { HashRouter, Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import ProtectedRoute from "./components/ProtectedRoute";
import OwnerRoute from "./components/OwnerRoute";
import LoginPage from "./pages/LoginPage";
import SignupPage from "./pages/SignupPage";
import ScannerPage from "./pages/ScannerPage";
import WatchlistsPage from "./pages/WatchlistsPage";
import WatchlistDetailPage from "./pages/WatchlistDetailPage";
import AISearchPage from "./pages/AISearchPage";
import StockDetailPage from "./pages/StockDetailPage";
import SignalsPage from "./pages/SignalsPage";
import EarningsPage from "./pages/EarningsPage";
import AdminPage from "./pages/AdminPage";

export default function App() {
  return (
    <HashRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route element={<ProtectedRoute />}>
          <Route element={<Layout />}>
            <Route path="/" element={<ScannerPage />} />
            <Route path="/watchlists" element={<WatchlistsPage />} />
            <Route path="/watchlists/:name" element={<WatchlistDetailPage />} />
            <Route path="/ai-search" element={<AISearchPage />} />
            <Route path="/signals" element={<SignalsPage />} />
            <Route path="/earnings" element={<EarningsPage />} />
            <Route path="/stock/:symbol" element={<StockDetailPage />} />
            <Route element={<OwnerRoute />}>
              <Route path="/admin" element={<AdminPage />} />
            </Route>
          </Route>
        </Route>
      </Routes>
    </HashRouter>
  );
}
