import { Navigate, Route, Routes } from "react-router-dom";
import DashboardPage from "./routes/DashboardPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/paper/strategy/spy/strategy-1" replace />} />
      <Route path="/paper/strategy/:symbol/:strategyId" element={<DashboardPage />} />
      <Route path="*" element={<Navigate to="/paper/strategy/spy/strategy-1" replace />} />
    </Routes>
  );
}
