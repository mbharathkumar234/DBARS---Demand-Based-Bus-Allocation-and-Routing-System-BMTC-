import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "react-hot-toast";
import { AuthProvider, useAuth } from "./contexts/AuthContext";
import { LanguageProvider } from "./contexts/LanguageContext";
import { AIProvider } from "./contexts/AIContext";
import { AIAssistantModal } from "./components/AIAssistantModal";
import { AIFloatingTrigger } from "./components/AIFloatingTrigger";

// Pages
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Register from "./pages/Register";
import CommuterDashboard from "./pages/CommuterDashboard";
import VotePage from "./pages/VotePage";
import PredictPage from "./pages/PredictPage";
import SharedTripView from "./pages/SharedTripView";
import LiveTracking from "./pages/LiveTracking";
import Tickets from "./pages/Tickets";
import ConductorScanner from "./pages/ConductorScanner";
import ConductorDuty from "./pages/ConductorDuty";
import AdminDashboard from "./pages/AdminDashboard";
import DepotDashboard from "./pages/DepotDashboard";
import Navbar from "./components/Navbar";

// A simple wrapper to keep unauthorized users out of sensitive pages
function ProtectedRoute({ children, roles }: { children: React.ReactNode; roles?: string[] }) {
  const { user, loading, isAuthenticated } = useAuth();

  if (loading) return <div className="page-loader">Loading...</div>;
  if (!isAuthenticated) return <Navigate to="/login" />;
  if (roles && user && !roles.includes(user.role)) return <Navigate to="/dashboard" />;

  return <>{children}</>;
}

// traffic cop component: sends you to the right dashboard based on your user role
function DashboardRouter() {
  const { user } = useAuth();
  if (user?.role === "admin") return <Navigate to="/admin" />;
  if (user?.role === "depot_manager") return <Navigate to="/depot" />;

  // default fallback is the commuter view
  return <CommuterDashboard />;
}

function AppRoutes() {
  const { isAuthenticated, user } = useAuth();

  return (
    <div className="app-shell">
      <Navbar />
      <main className="page-container">
        <Routes>
          <Route path="/" element={isAuthenticated ? <Navigate to="/dashboard" /> : <Landing />} />
          <Route path="/login" element={isAuthenticated ? <Navigate to="/dashboard" /> : <Login />} />
          <Route path="/register" element={isAuthenticated ? <Navigate to="/dashboard" /> : <Register />} />
          {/* Public: a trusted contact viewing a shared trip may not have
              an app account -- see SharedTripView.tsx and
              safety_service.py's create_trip_share docstring. */}
          <Route path="/trip/:code" element={<SharedTripView />} />

          {/* Commuter routes - basic stuff */}
          <Route path="/dashboard" element={<ProtectedRoute><DashboardRouter /></ProtectedRoute>} />
          <Route path="/vote" element={<ProtectedRoute><VotePage /></ProtectedRoute>} />
          <Route path="/predict" element={<ProtectedRoute><PredictPage /></ProtectedRoute>} />
          <Route path="/track" element={<ProtectedRoute><LiveTracking /></ProtectedRoute>} />
          <Route path="/tickets" element={<ProtectedRoute><Tickets /></ProtectedRoute>} />

          {/* Back-office admin views — admin only */}
          <Route path="/admin" element={<ProtectedRoute roles={["admin"]}><AdminDashboard /></ProtectedRoute>} />

          {/* Depot operations views — depot_manager only */}
          <Route path="/depot" element={<ProtectedRoute roles={["depot_manager"]}><DepotDashboard /></ProtectedRoute>} />
          <Route path="/scanner" element={<ProtectedRoute roles={["depot_manager", "conductor"]}><ConductorScanner /></ProtectedRoute>} />
          {/* The conductor's actual job: sign on, issue tickets, sign off,
              remit cash. The scanner above only verifies passes. */}
          <Route path="/duty" element={<ProtectedRoute roles={["conductor", "admin"]}><ConductorDuty /></ProtectedRoute>} />

          {/* Catch-all to keep people from hitting 404s */}
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <LanguageProvider>
          <AIProvider>
            <Toaster
              position="top-right"
              toastOptions={{
                duration: 3000,
                style: { background: "var(--surface-2)", color: "var(--text-1)", border: "1px solid var(--border)" },
              }}
            />
            <AppRoutes />
            <AIAssistantModal />
            <AIFloatingTrigger />
          </AIProvider>
        </LanguageProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}