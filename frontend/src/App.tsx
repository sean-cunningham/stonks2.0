import { Navigate, Route, Routes } from "react-router-dom";
import DashboardPage from "./routes/DashboardPage";
import StrategiesPage from "./routes/StrategiesPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/paper/strategies" replace />} />
      <Route path="/paper/strategies" element={<StrategiesPage />} />
      <Route path="/paper/strategy/:symbol/:strategyId" element={<DashboardPage />} />
      <Route path="*" element={<Navigate to="/paper/strategies" replace />} />
    </Routes>
  );
}
