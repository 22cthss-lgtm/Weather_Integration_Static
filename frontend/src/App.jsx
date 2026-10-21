import { Link, Route, Routes } from "react-router-dom";
import DashboardPage from "./pages/DashboardPage";
import ImagePage from "./pages/ImagePage";
import SeaIcePage from "./pages/SeaIcePage";
import CimssPage from "./pages/CimssPage";
import RainFallPage from "./pages/RainFallPage";
import RadarPage from "./pages/RadarPage";
import SatellitePage from "./pages/SatellitePage";

export default function App() {
  return (
    <div className="app-shell">
      <header>
        <h1>
          <Link className="site-title-link" to="/">
            Weather Integration
          </Link>
        </h1>
        <nav>
          <Link to="/">Dashboard</Link>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/images/seaice_arctic" element={<SeaIcePage type="seaice_arctic" />} />
          <Route path="/images/seaice_antarctic" element={<SeaIcePage type="seaice_antarctic" />} />
          <Route path="/images/cimss_wind_analysis" element={<CimssPage type="cimss_wind_analysis" />} />
          <Route path="/images/cimss_steering_flow" element={<CimssPage type="cimss_steering_flow" />} />
          <Route path="/images/rainfall" element={<RainFallPage />} />
          <Route path="/images/radar" element={<RadarPage />} />
          <Route path="/images/satellite" element={<SatellitePage />} />
          <Route path="/images/:type" element={<ImagePage />} />
        </Routes>
      </main>
    </div>
  );
}
