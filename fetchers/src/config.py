from pathlib import Path
import os

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent


def load_backend_env(env_path: Path | str = BASE_DIR / ".env") -> None:
    load_dotenv(dotenv_path=env_path)


load_backend_env()

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
FAQ_UPLOAD_DIR = BASE_DIR / "uploads" / "faq"

DATABASE_PATH = DATA_DIR / "weather.db"
CWA_API_KEY = os.getenv("CWA_API_KEY", "")
RAINFALL_OBSERVATION_TTL_MINUTES = 11

DEFAULT_IMAGE_TTL_MINUTES = 24 * 60
IMAGE_TYPE_TTL_MINUTES = {
    "radar": 15,
    "satellite": 15,
    "temperature": 60,
    "rainfall": 30,
    "weather_chart": 12 * 60,
    "850hpa": 12 * 60,
    "cimss_wind_analysis": 3 * 60,
    "cimss_wind_shear": 3 * 60,
    "cimss_850mb_vorticity": 3 * 60,
    "cimss_steering_flow": 3 * 60,
    "cimss_steering_flow_700_850mb": 3 * 60,
    "cimss_steering_flow_500_850mb": 3 * 60,
    "cimss_steering_flow_400_850mb": 3 * 60,
    "cimss_steering_flow_300_850mb": 3 * 60,
    "cimss_steering_flow_250_850mb": 3 * 60,
    "cimss_steering_flow_200_700mb": 3 * 60,
    "sst": 24 * 60,
    "tchp": 24 *60,
    "seaice_arctic_extent": 24 * 60,
    "seaice_arctic_concentration": 24 * 60,
    "seaice_arctic_timeseries": 24 * 60,
    "seaice_antarctic_extent": 24 * 60,
    "seaice_antarctic_concentration": 24 * 60,
    "seaice_antarctic_timeseries": 24 * 60,
}
