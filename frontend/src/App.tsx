import { Navigate, Route, Routes } from "react-router-dom";

import { BuilderPage } from "./builder/BuilderPage";
import { FlowsPage } from "./builder/FlowsPage";
import { SettingsPage } from "./settings/SettingsPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<FlowsPage />} />
      <Route path="/flows/:flowId" element={<BuilderPage />} />
      <Route path="/settings" element={<SettingsPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
